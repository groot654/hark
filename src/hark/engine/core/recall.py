"""Answers direct questions about the user ("what's my name?", "where do I live?") from saved memories.

Done without the language model on purpose: a small model confuses "I" and "you" when restating
facts about the person it's talking to, while a keyword match plus a pronoun swap is reliable.
"""

from __future__ import annotations

import re

QUESTION = re.compile(
    r"^(?:what|what's|whats|who|where|where's|when|when's|which|how|do|did|does|am|is|was)\b.*\b(?:i|my|me|mine)\b",
    re.I,
)
STOPWORDS = {
    "what", "whats", "who", "where", "when", "which", "how", "do", "did", "does", "am", "is", "was", "are", "the",
    "a", "an", "of", "to", "in", "on", "at", "for", "i", "my", "me", "mine", "you", "your", "it", "that", "this",
    "again", "remember", "know", "tell", "please", "hark",
}
# Question words that stand in for the fact they ask about.
HINTS = {"who": {"name"}, "called": {"name"}, "old": {"age", "born", "birthday"}, "born": {"born", "birthday"}}
TO_SECOND_PERSON = [
    (r"\bI am\b", "you are"), (r"\bI'm\b", "you're"), (r"\bI've\b", "you've"), (r"\bI'll\b", "you'll"),
    (r"\bmyself\b", "yourself"), (r"\bmine\b", "yours"), (r"\bmy\b", "your"), (r"\bme\b", "you"), (r"\bI\b", "you"),
]


def recall(question: str, memories: list[dict]) -> str | None:
    """The best-matching memory restated to the user, or None when nothing fits."""
    text = question.strip().rstrip("?.!")
    if not memories or not QUESTION.match(text):
        return None
    words = re.findall(r"[a-z']+", text.lower())
    wanted = {_stem(w) for w in words if w not in STOPWORDS}
    for word in words:
        wanted |= {_stem(h) for h in HINTS.get(word, ())}
    if not wanted:
        return None
    scored = [(len(wanted & {_stem(w) for w in re.findall(r"[a-z']+", m["value"].lower())}), m["value"])
              for m in memories]
    score, fact = max(scored, key=lambda s: s[0])
    return second_person(fact) if score else None


def second_person(fact: str) -> str:
    for pattern, repl in TO_SECOND_PERSON:
        fact = re.sub(pattern, repl, fact, flags=re.I)
    fact = fact.strip().rstrip(".")
    return fact[:1].upper() + fact[1:] + "."


def _stem(word: str) -> str:
    word = word.removesuffix("'s")
    for suffix in ("ing", "es", "ed", "s", "d"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word.removesuffix("e") if len(word) > 3 else word
