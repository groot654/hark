import pytest

from togo.engine.core.wake import match


@pytest.mark.parametrize(
    ("heard", "rest"),
    [
        ("Hey Togo", ""),
        ("Hey Togo!", ""),
        ("Hey Togo, open Spotify!", "open Spotify!"),
        ("Hey Togo! What's the time?", "What's the time?"),
        ("Okay Togo. Set a timer for 5 minutes.", "Set a timer for 5 minutes."),
        ("Hi Togo, add milk to my list.", "add milk to my list."),
        ("Um, hey Togo. Mute", "Mute"),
        ("Heytogo open notepad", "open notepad"),
        # how Parakeet sometimes hears "Hey Togo"
        ("Hey to go", ""),
        ("Um, hey to go, mute.", "mute."),
        ("Hey Toco, what's the time?", "what's the time?"),
        ("Hey Chogo", ""),
        ("Hey Choko.", ""),
        ("Hey toggo, lock the screen", "lock the screen"),
    ],
)
def test_wake_phrase_is_found_and_stripped(heard, rest):
    assert match(heard) == rest


@pytest.mark.parametrize(
    "heard",
    [
        "Hey Tom, go and get the car.",
        "Can I get that to go?",
        "Togo is a country in West Africa.",
        "Hey, Tokyo was amazing.",
        "Hey, are you going to go?",
        "Take it to go please.",
        "So I said hey Togo to him",  # the phrase has to open the burst
        "",
        "hey",
    ],
)
def test_look_alikes_do_not_trigger(heard):
    assert match(heard) is None


def test_custom_phrase():
    assert match("Computer, dim the lights", "computer") == "dim the lights"
    assert match("Hey Jarvis open mail", "hey jarvis") == "open mail"
    assert match("Hey Togo open mail", "hey jarvis") is None
