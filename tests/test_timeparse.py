import datetime as dt

import pytest

from hark.engine.tools.timeparse import describe, parse_when, words_to_number

NOW = dt.datetime(2026, 10, 21, 10, 0, 0)


@pytest.mark.parametrize(
    ("token", "value"),
    [("5", 5), ("2.5", 2.5), ("an", 1), ("a couple of", 2), ("twenty-five", 25), ("thirty one", 31)],
)
def test_words_to_number(token, value):
    assert words_to_number(token) == value


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("in 10 minutes", dt.timedelta(minutes=10)),
        ("in ten minutes", dt.timedelta(minutes=10)),
        ("in an hour and a half", dt.timedelta(minutes=90)),
        ("in 2 and a half hours", dt.timedelta(minutes=150)),
        ("in half an hour", dt.timedelta(minutes=30)),
        ("after 30 seconds", dt.timedelta(seconds=30)),
        ("in a couple of days", dt.timedelta(days=2)),
    ],
)
def test_relative_times(text, delta):
    due, _ = parse_when(f"remind me {text} to stretch", NOW)
    assert due == NOW + delta


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at 6pm", dt.datetime(2026, 10, 21, 18, 0)),
        ("at 6", dt.datetime(2026, 10, 21, 18, 0)),          # 6am already passed -> 6pm
        ("at 11", dt.datetime(2026, 10, 21, 11, 0)),
        ("at 9:30 tomorrow", dt.datetime(2026, 10, 22, 9, 30)),
        ("tomorrow at 7 am", dt.datetime(2026, 10, 22, 7, 0)),
        ("tonight at 8", dt.datetime(2026, 10, 21, 20, 0)),
        ("at 12 am", dt.datetime(2026, 10, 22, 0, 0)),
        ("at noon", dt.datetime(2026, 10, 21, 12, 0)),
        ("at midnight", dt.datetime(2026, 10, 22, 0, 0)),
    ],
)
def test_clock_times(text, expected):
    due, _ = parse_when(f"remind me {text} to call mum", NOW)
    assert due == expected


def test_returns_matched_phrase():
    _, phrase = parse_when("remind me in 5 minutes to check the oven", NOW)
    assert phrase == "in 5 minutes"


def test_no_time():
    assert parse_when("remind me to call mum", NOW) is None


def test_describe():
    assert describe(NOW + dt.timedelta(minutes=5), NOW).startswith("in 5 minutes")
    assert describe(dt.datetime(2026, 10, 21, 18, 0), NOW) == "at 6:00 PM"
    assert describe(dt.datetime(2026, 10, 22, 9, 30), NOW) == "tomorrow at 9:30 AM"
