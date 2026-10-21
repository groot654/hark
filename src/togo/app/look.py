"""Colour schemes for the notch and Togo's eyes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Look:
    name: str
    notch: str
    eyes: str
    accent: str
    dictation: str
    text: str = "#eef2f7"


LOOKS = {
    "arc": Look("Arc", notch="#0a0d12", eyes="#5fd7ff", accent="#5fd7ff", dictation="#ffd166"),
    "ember": Look("Ember", notch="#120b0a", eyes="#ff9f5f", accent="#ff9f5f", dictation="#ffe08a"),
    "mint": Look("Mint", notch="#08110e", eyes="#6bf0b5", accent="#6bf0b5", dictation="#c3f584"),
    "violet": Look("Violet", notch="#0e0a14", eyes="#b49bff", accent="#b49bff", dictation="#ff9bd2"),
    "mono": Look("Mono", notch="#0b0b0b", eyes="#f2f2f2", accent="#f2f2f2", dictation="#bdbdbd"),
}
DEFAULT_LOOK = "arc"


def get_look(name: str) -> Look:
    return LOOKS.get(name, LOOKS[DEFAULT_LOOK])
