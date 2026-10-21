"""Drops recogniser artefacts: phantom phrases heard in silence or noise."""

from __future__ import annotations

import re

_PHANTOMS = {
    "thanks for watching", "thank you for watching", "please subscribe", "subscribe",
    "you", "bye", "uh", "um", "hmm", "mm", "ah", "oh", "beep", "ding", "music",
}
_BRACKETED = re.compile(r"^\s*[\[(].*[\])]\s*$")


def is_noise(text: str) -> bool:
    cleaned = re.sub(r"[^\w' ]", "", text.lower()).strip()
    if not cleaned or _BRACKETED.match(text):
        return True
    if cleaned in _PHANTOMS:
        return True
    words = cleaned.split()
    # Repetition loops ("the the the the ...") are a decoder failure mode.
    return len(words) >= 6 and len(set(words)) <= 2
