"""Parse spoken times: "in 10 minutes", "in an hour and a half", "at 6pm", "tomorrow at 9:30"."""

from __future__ import annotations

import datetime as dt
import re

UNITS = {
    "zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "a couple of": 2,
    "a few": 3, "couple of": 2, "few": 3,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}

NUM = r"(\d+(?:\.\d+)?|a couple of|couple of|a few|few|an?|(?:twenty|thirty|forty|fifty|sixty)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"

RELATIVE = re.compile(
    rf"\b(?:in|after)\s+{NUM}\s*(?:and a half\s+)?(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)(\s+and a half)?\b",
    re.I,
)
HALF_HOUR = re.compile(r"\bin\s+(?:half an hour|a half hour|30 min)\b", re.I)
CLOCK = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2})|\s+(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|o'?clock)?\b", re.I
)
AT_CLOCK = re.compile(
    r"\b(?P<day>tomorrow|tonight|today|this evening|this afternoon|this morning)?\s*(?:at\s+)"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?(?:\s*(?P<ampm>a\.?m\.?|p\.?m\.?|o'?clock))?"
    r"(?:\s+(?P<day2>tomorrow|tonight|today))?\b",
    re.I,
)
NOON = re.compile(r"\b(?:at\s+)?(noon|midday|midnight)\b", re.I)


def words_to_number(token: str) -> float:
    token = token.lower().strip()
    try:
        return float(token)
    except ValueError:
        pass
    if token in UNITS:
        return UNITS[token]
    parts = re.split(r"[ -]", token)
    total = 0
    for part in parts:
        total += TENS.get(part, UNITS.get(part, 0))
    return total


def parse_when(text: str, now: dt.datetime | None = None) -> tuple[dt.datetime, str] | None:
    """Return (due time, the matched phrase) or None."""
    now = now or dt.datetime.now()
    if m := HALF_HOUR.search(text):
        return now + dt.timedelta(minutes=30), m.group(0)
    if m := RELATIVE.search(text):
        amount = words_to_number(m.group(1))
        if "and a half" in m.group(0).lower():
            amount += 0.5
        unit = m.group(2).lower()
        if unit.startswith("s"):
            delta = dt.timedelta(seconds=amount)
        elif unit.startswith("m"):
            delta = dt.timedelta(minutes=amount)
        elif unit.startswith("h"):
            delta = dt.timedelta(hours=amount)
        else:
            delta = dt.timedelta(days=amount)
        return now + delta, m.group(0)
    if m := NOON.search(text):
        hour = 0 if m.group(1).lower() == "midnight" else 12
        due = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if due <= now:
            due += dt.timedelta(days=1)
        return due, m.group(0)
    if m := AT_CLOCK.search(text):
        hour, minute = int(m.group("h")), int(m.group("m") or 0)
        ampm = (m.group("ampm") or "").lower().replace(".", "")
        day = (m.group("day") or m.group("day2") or "").lower()
        if hour > 23 or minute > 59:
            return None
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif not ampm.endswith("m") and hour < 12 and day in ("tonight", "this evening", "this afternoon"):
            hour += 12
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day == "tomorrow":
            due += dt.timedelta(days=1)
        elif due <= now:
            # "at 6" with no am/pm: take the next 6 o'clock that's still ahead.
            if not ampm.endswith("m") and hour < 12 and due + dt.timedelta(hours=12) > now:
                due += dt.timedelta(hours=12)
            else:
                due += dt.timedelta(days=1)
        return due, m.group(0)
    return None


def describe(due: dt.datetime, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    clock = due.strftime("%I:%M %p").lstrip("0")
    delta = due - now
    if delta < dt.timedelta(hours=1):
        minutes = max(1, round(delta.total_seconds() / 60))
        return f"in {minutes} minute{'s' if minutes != 1 else ''} ({clock})"
    if due.date() == now.date():
        return f"at {clock}"
    if due.date() == (now + dt.timedelta(days=1)).date():
        return f"tomorrow at {clock}"
    return due.strftime("%a %d %b at ") + clock
