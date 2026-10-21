"""Wake phrase matching on a transcript ("Hey Hark, open Spotify" -> "open Spotify").

There's no separate keyword model: the client sends each burst of speech it hears, the engine
transcribes it, and this checks whether it *opens* with the wake phrase. A greeting word is required
for two-part phrases ("hey", "hi", "okay"…) and the name must match closely, so "Hark the herald",
"hey Mark" and "I parked" don't trigger.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

DEFAULT_PHRASE = "hey hark"
GREETINGS = {"hey", "hay", "hei", "heya", "hi", "ok", "okay", "a", "ay", "eh", "ey", "yo"}
FILLERS = {"um", "umm", "uh", "uhm", "er", "erm", "so", "well", "oh"}
# Mishearings of a name that are too far off for the similarity check but still clearly meant.
NAME_ALIASES = {"hark": {"harke", "harc", "haak", "haark", "hawk", "hork", "harck", "hart", "hardt", "harth"}}
NAME_SIMILARITY = 0.85  # "harke" passes; "mark" and "park" (0.75) don't
MAX_FILLERS = 2
WORD = re.compile(r"[a-z0-9']+")


def match(transcript: str, phrase: str = DEFAULT_PHRASE) -> str | None:
    """What was said after the wake phrase ("" for the phrase alone), or None if it doesn't open with it."""
    phrase_words = phrase.lower().split()
    if not phrase_words:
        return None
    tokens = list(WORD.finditer(transcript.lower()))
    i = 0
    while i < len(tokens) and i < MAX_FILLERS and tokens[i].group(0) in FILLERS:
        i += 1

    needs_greeting = len(phrase_words) > 1 and phrase_words[0] in GREETINGS
    name_words = phrase_words[1:] if needs_greeting else phrase_words
    if needs_greeting:
        if i >= len(tokens):
            return None
        first = tokens[i].group(0)
        if first in GREETINGS:
            i += 1
        else:
            # The recogniser sometimes runs them together: "heyhark".
            merged = next((first[len(g):] for g in sorted(GREETINGS, key=len, reverse=True)
                           if first.startswith(g) and len(first) > len(g)), None)
            if merged is None or len(name_words) != 1 or not _name_matches(merged, name_words[0]):
                return None
            return _rest(transcript, tokens[i].end())

    heard = tokens[i:i + len(name_words)]
    if len(heard) < len(name_words):
        return None
    if not all(_name_matches(t.group(0), w) for t, w in zip(heard, name_words)):
        return None
    return _rest(transcript, heard[-1].end())


def _name_matches(heard: str, name: str) -> bool:
    return heard == name or heard in NAME_ALIASES.get(name, ()) or SequenceMatcher(None, heard, name).ratio() >= NAME_SIMILARITY


def _rest(transcript: str, end: int) -> str:
    return transcript[end:].lstrip(" ,.!?;:-–—").strip()
