import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hark.app.hud import MOODS, TICK_S, Card, Hud, HudState  # noqa: E402
from hark.app.look import get_look  # noqa: E402


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def hud(qt):
    h = Hud(get_look("arc"))
    h._tick.stop()
    h._blink_timer.stop()
    yield h
    h.deleteLater()


def run_for(hud, seconds):
    for _ in range(int(seconds / TICK_S) + 1):
        hud._on_tick()


@pytest.mark.parametrize("mood", sorted(MOODS))
def test_reaction_plays_then_ends(hud, mood):
    hud.react(mood)
    assert hud.mood == mood
    assert hud._hop() == 0.0 or hud._hop() <= 0  # the hop only ever lifts the eyes
    run_for(hud, MOODS[mood] / 2)
    assert hud.mood == mood
    run_for(hud, MOODS[mood])
    assert hud.mood is None
    assert hud._hearts == []


def test_love_brings_hearts(hud):
    hud.react("love")
    assert len(hud._hearts) == 5


def test_unknown_mood_is_ignored(hud):
    hud.react("furious")
    assert hud.mood is None


@pytest.mark.parametrize("mood", [None, *sorted(MOODS)])
@pytest.mark.parametrize("state", [HudState.REST, HudState.LISTENING, HudState.THINKING, "card"])
def test_every_mood_paints_in_every_state(hud, mood, state):
    if state == "card":
        hud.show_card(Card(title="Today", body="Any time.", items=["one", "two"]))
    else:
        hud.set_state(state)
    if mood:
        hud.react(mood)
        run_for(hud, 0.5)
    assert not hud.grab().isNull()


@pytest.mark.parametrize(("seconds", "text"), [(1499.2, "25:00"), (59.9, "1:00"), (5, "0:05"), (0, "0:00"),
                                                 (-3, "0:00"), (3900, "1:05:00")])
def test_format_remaining(seconds, text):
    from hark.app.hud import format_remaining

    assert format_remaining(seconds) == text


def test_focus_widens_the_resting_pill_and_clears_itself(hud):
    import time

    from hark.app.hud import REST_FOCUS_SIZE, SIZES

    hud.set_state(HudState.REST)
    hud.set_focus(time.time() + 600, 1500)
    assert hud._target.toSize() == REST_FOCUS_SIZE
    assert 590 < hud.focus_remaining <= 600
    assert not hud.grab().isNull()
    hud._focus_ends = time.time() - 1  # time's up
    hud._on_tick()
    assert hud.focus_remaining is None
    assert hud._target.toSize() == SIZES[HudState.REST]


def test_focus_in_the_past_is_ignored(hud):
    import time

    hud.set_focus(time.time() - 5, 60)
    assert hud.focus_remaining is None
