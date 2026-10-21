"""Dictation formatting.

exact    – the recogniser's words as heard
clean    – fillers removed, spoken punctuation and repairs applied, dictionary and snippets
polished – clean, then tidied by the local model (falls back to clean if the model is
           unavailable or its output changes protected values such as URLs or numbers)

Per-app styles adjust the result: chat apps drop the final full stop, code editors
keep text literal.
"""

from __future__ import annotations

import logging
import re

from hark.engine.core import prompts
from hark.engine.core.llm import LLMClient, LLMUnavailable

log = logging.getLogger(__name__)

FILLERS = re.compile(r"\b(?:um+|uh+|erm*|uhm+|hmm+|mm+|ah+)\b[,.]?\s*", re.I)
STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b)+", re.I)

SPOKEN_PUNCTUATION = [
    (r"\s*\b(?:new paragraph|next paragraph)\b[,.]?\s*", "\n\n"),
    (r"\s*\b(?:new line|next line|line break)\b[,.]?\s*", "\n"),
    (r"\s*\b(?:full stop|period)\b[,.]?", "."),
    (r"\s*\bcomma\b[,.]?", ","),
    (r"\s*\bquestion mark\b[,.]?", "?"),
    (r"\s*\bexclamation (?:mark|point)\b[,.]?", "!"),
    (r"\s*\bcolon\b[,.]?", ":"),
    (r"\s*\bsemicolon\b[,.]?", ";"),
    (r"\s*\b(?:dash|hyphen)\b\s*", " - "),
    (r"\b(?:open (?:bracket|paren(?:thesis)?))\s*", "("),
    (r"\s*\b(?:close (?:bracket|paren(?:thesis)?))\b", ")"),
    (r"\s*\b(?:close quote|end quote|unquote)\b", "”"),
    (r"\b(?:open quote|quote)\s*", "“"),
]

# "see you at 5, scratch that, see you at 6" -> "see you at 6": drops the clause before the marker
SCRATCH = re.compile(r"[,.!?]?\s*\b(?:scratch that|delete that|strike that)\b[,.!?]?\s*", re.I)
CLAUSE_END = re.compile(r"[,.!?\n]")
# "meet at 5 make that 6" -> "meet at 6": replace the last word before the marker
MAKE_THAT = re.compile(r"(\S+)[,.]?\s+\b(?:make that|no,? i mean|i mean,|sorry,? i mean)\b[,]?\s+(\S+)", re.I)
# "at 5, actually, 6" -> "at 6" (only with punctuation around "actually")
ACTUALLY = re.compile(r"(\S+),\s*actually,\s+(\S+)", re.I)

BULLET = re.compile(r"(?:^|\s)\b(?:bullet(?: point)?|next bullet)\b[,.:]?\s*", re.I)
NUMBERED = re.compile(r"(?:^|\s)\b(?:number|point|item) (one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b[,.:]?\s*", re.I)
ORDINALS = {w: i for i, w in enumerate("one two three four five six seven eight nine ten".split(), start=1)}

CHAT_APPS = {"whatsapp", "telegram", "discord", "slack", "signal", "messenger", "teams", "ms-teams"}
CODE_APPS = {"code", "cursor", "devenv", "pycharm64", "idea64", "windowsterminal", "cmd", "powershell", "pwsh",
             "wezterm-gui", "alacritty", "sublime_text", "notepad++"}
PROTECTED = re.compile(r"https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.]+\b|\b\d[\d,.:/-]*\b|[A-Za-z]:\\\S+|`[^`]+`")


def app_style(app: str) -> str:
    app = app.lower()
    if app in CODE_APPS:
        return "code"
    if app in CHAT_APPS:
        return "casual"
    return "formal"


def _scratch(text: str) -> str:
    while m := SCRATCH.search(text):
        before = text[:m.start()].rstrip()
        cut = max((c.end() for c in CLAUSE_END.finditer(before)), default=0)
        kept, rest = before[:cut], text[m.end():]
        text = f"{kept} {rest}".strip() if rest else kept.rstrip(" ,")
    return text


def apply_repairs(text: str) -> str:
    text = _scratch(text)
    text = MAKE_THAT.sub(r"\2", text)
    text = ACTUALLY.sub(r"\2", text)
    return text


def apply_punctuation(text: str) -> str:
    for pattern, repl in SPOKEN_PUNCTUATION:
        text = re.sub(pattern, repl, text, flags=re.I)
    # The recogniser often adds its own punctuation next to spoken punctuation.
    text = re.sub(r"([,.?!:;])[,.](?=\s|$)", r"\1", text)
    text = re.sub(r"[ \t]+([,.?!:;)”])", r"\1", text)
    text = re.sub(r"([(“])\s+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def apply_lists(text: str) -> str:
    if BULLET.search(text):
        parts = [p.strip(" ,.") for p in BULLET.split(text)]
        head, items = parts[0], [p for p in parts[1:] if p]
        return (head + "\n" if head else "") + "\n".join(f"- {_cap(i)}" for i in items)
    if len(NUMBERED.findall(text)) >= 2:
        pieces = NUMBERED.split(text)
        head, rest = pieces[0].strip(" ,."), pieces[1:]
        lines = []
        for num, body in zip(rest[0::2], rest[1::2]):
            n = ORDINALS.get(num.lower(), num)
            lines.append(f"{n}. {_cap(body.strip(' ,.'))}")
        return (head + "\n" if head else "") + "\n".join(lines)
    return text


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def capitalise_sentences(text: str) -> str:
    text = _cap(text)
    text = re.sub(r"([.?!]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return re.sub(r"\bi\b", "I", text)


def apply_dictionary(text: str, entries: dict[str, str]) -> str:
    for heard, wanted in sorted(entries.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{re.escape(heard)}\b", wanted, text, flags=re.I)
    return text


def expand_snippet(text: str, snippets: dict[str, str]) -> str | None:
    """A snippet fires only when its trigger is said alone, or after "insert"/"type"."""
    spoken = re.sub(r"^(?:insert|type|paste)\s+", "", text.strip().rstrip(".!?").lower())
    return snippets.get(spoken)


def clean(text: str, style: str, dictionary: dict[str, str] | None = None) -> str:
    text = FILLERS.sub("", text)
    text = STUTTER.sub(r"\1", text)
    text = apply_repairs(text)
    if dictionary:
        text = apply_dictionary(text, dictionary)
    if style == "code":
        return apply_punctuation(text).rstrip(".")
    text = apply_punctuation(text)
    text = apply_lists(text)
    text = capitalise_sentences(text)
    if style == "casual":
        text = text.rstrip(".")
    elif text and (text[-1].isalnum() or text[-1] in "”)") and "\n" not in text:
        text += "."
    return text


def _protected_values(text: str) -> set[str]:
    return {v.rstrip(".,") for v in PROTECTED.findall(text)}


def polish(text: str, llm: LLMClient, timeout: float = 8.0) -> str | None:
    try:
        out = llm.chat([{"role": "system", "content": prompts.POLISH}, {"role": "user", "content": text}],
                       temperature=0.1, max_tokens=max(120, len(text)), timeout=timeout)
    except LLMUnavailable:
        return None
    out = out.strip().strip('"')
    if not out or len(out) > len(text) * 1.6 + 40:
        log.info("polish rejected: unexpected expansion")
        return None
    if not _protected_values(text) <= _protected_values(out):
        log.info("polish rejected: protected value changed")
        return None
    return out


def format_dictation(transcript: str, mode: str, app: str, store=None, llm: LLMClient | None = None) -> str:
    if mode == "exact":
        return transcript
    snippets = store.get_setting("dictation.snippets", {}) if store else {}
    if snippets and (expanded := expand_snippet(transcript, snippets)):
        return expanded
    dictionary = store.get_setting("dictation.dictionary", {}) if store else {}
    style = store.get_setting(f"dictation.style.{app.lower()}", app_style(app)) if store else app_style(app)
    cleaned = clean(transcript, style, dictionary)
    if mode == "polished" and llm is not None and style != "code":
        polished = polish(cleaned, llm)
        if polished:
            return polished.rstrip(".") if style == "casual" else polished
    return cleaned
