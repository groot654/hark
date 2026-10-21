import pytest

from hark.engine.core.wake import match


@pytest.mark.parametrize(
    ("heard", "rest"),
    [
        ("Hey Hark", ""),
        ("Hey Hark!", ""),
        ("Hey hark, open Spotify!", "open Spotify!"),
        ("Hey hark! What's the time?", "What's the time?"),
        ("Okay hark. Set a timer for five minutes.", "Set a timer for five minutes."),
        ("Hi Hark, add milk to my list.", "add milk to my list."),
        ("Um, hey hark. Mute", "Mute"),
        ("Heyhark open notepad", "open notepad"),
        ("Hey harke, lock the screen", "lock the screen"),
        ("Hey hawk, play music", "play music"),
        ("Eyhardt, yes.", "yes."),  # how one real user's "Hey Hark, yes" was heard
    ],
)
def test_wake_phrase_is_found_and_stripped(heard, rest):
    assert match(heard) == rest


@pytest.mark.parametrize(
    "heard",
    [
        "Hey Mark, are you coming tonight?",
        "Hey Park Ranger, where is the trail?",
        "I parked the car over there.",
        "Hey, how are you doing?",
        "Hark the Herald Angels sing.",
        "My heart rate is high.",
        "So I said hey hark to him",  # the phrase has to open the burst
        "",
        "hey",
    ],
)
def test_look_alikes_do_not_trigger(heard):
    assert match(heard) is None


def test_custom_phrase():
    assert match("Computer, dim the lights", "computer") == "dim the lights"
    assert match("Hey Jarvis open mail", "hey jarvis") == "open mail"
    assert match("Hey Hark open mail", "hey jarvis") is None
