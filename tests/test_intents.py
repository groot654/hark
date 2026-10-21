import pytest

from hark.engine.core.intents import match, match_one, normalise


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("Hey Hark, could you open Spotify please?", "open Spotify"),
        ("hark can you please mute", "mute"),
        ("what time is it now?", "what time is it"),
        ("  lock the screen, thanks.  ", "lock the screen"),
    ],
)
def test_normalise_strips_wake_word_and_politeness(spoken, expected):
    assert normalise(spoken) == expected


@pytest.mark.parametrize(
    ("spoken", "tool", "args"),
    [
        ("open spotify", "app.open", {"name": "spotify"}),
        ("launch the calculator app", "app.open", {"name": "calculator"}),
        ("close chrome", "app.close", {"name": "chrome"}),
        ("go to github.com/anthropics", "web.open", {"url": "github.com/anthropics"}),
        ("search for lo-fi beats on youtube", "web.search", {"query": "lo-fi beats", "engine": "youtube"}),
        ("google best pizza near me", "web.search", {"query": "best pizza near me", "engine": "google"}),
        ("set the volume to fifty percent", "volume.set", {"percent": 50}),
        ("turn the volume down by 20", "volume.change", {"delta": -20}),
        ("louder", "volume.change", {"delta": 10}),
        ("it's way too loud in here", "volume.change", {"delta": -20}),
        ("I can barely hear this", "volume.change", {"delta": 20}),
        ("jot down that the plumber comes Friday", "note.add", {"body": "the plumber comes Friday"}),
        ("ping me in a quarter of an hour about the laundry", "reminder.add",
         {"text": "in a quarter of an hour about the laundry"}),
        ("mute", "volume.mute", {"muted": True}),
        ("unmute the sound", "volume.mute", {"muted": False}),
        ("next song", "media.key", {"action": "next"}),
        ("pause the music", "media.key", {"action": "play_pause"}),
        ("what's playing", "media.now_playing", {}),
        ("press control shift t", "input.keys", {"keys": "control shift t", "times": 1}),
        ("press tab three times", "input.keys", {"keys": "tab", "times": 3}),
        ("close this tab", "input.keys", {"keys": "ctrl w"}),
        ("type hello world", "input.type", {"text": "hello world"}),
        ("press enter", "input.keys", {"keys": "enter"}),
        ("press control s", "input.keys", {"keys": "control s"}),
        ("press the save button", "ui.click", {"name": "save button"}),
        ("press save", "ui.click", {"name": "save"}),
        ("click send", "ui.click", {"name": "send"}),
        ("click on the File menu", "ui.click", {"name": "File menu"}),
        ("open the file menu", "ui.click", {"name": "file menu"}),
        ("open the start menu", "input.keys", {"keys": "windows"}),
        ("select the bold tab", "ui.click", {"name": "bold tab"}),
        ("point at the search box", "ui.point", {"name": "search box"}),
        ("where's the send button", "ui.point", {"name": "send button"}),
        ("remember that my sister's name is Ayesha", "memory.remember", {"fact": "my sister's name is Ayesha"}),
        ("forget about my sister", "memory.forget", {"needle": "my sister"}),
        ("remind me in 10 minutes to call mum", "reminder.add", {"text": "in 10 minutes to call mum"}),
        ("set a timer for five minutes", "reminder.add", {"text": "in five minutes timer done"}),
        ("create a routine called wind down to mute and then add stretch to my list", "routine.save",
         {"name": "wind down", "steps": "mute and then add stretch to my list"}),
        ("make a routine named work: open slack", "routine.save", {"name": "work", "steps": "open slack"}),
        ("add buy milk to my to-do list", "task.add", {"title": "buy milk"}),
        ("mark buy milk as done", "task.complete", {"needle": "buy milk"}),
        ("what's on my to-do list", "task.list", {}),
        ("what have I got to do today", "task.list", {}),
        ("what do I need to do", "task.list", {}),
        ("show me what's in my notes", "note.list", {}),
        ("take a note that the wifi password is on the fridge", "note.add",
         {"body": "the wifi password is on the fridge"}),
        ("search my notes for wifi", "note.search", {"query": "wifi"}),
        ("log my reading habit", "habit.log", {"name": "reading"}),
        ("start a 50 minute focus session", "focus.start", {"minutes": 50, "label": None}),
        ("start focus", "focus.start", {"minutes": 25, "label": None}),
        ("stop focus", "focus.stop", {}),
        ("finish my focus session", "focus.stop", {}),
        ("run my morning routine", "routine.run", {"name": "morning"}),
        ("shut down the computer", "system.shutdown", {}),
        ("how's my battery", "system.stats", {}),
        ("good morning", "briefing.daily", {}),
        ("thank you so much", "persona.thanks", {}),
        ("change your colour to ember", "look.set", {"look": "ember"}),
    ],
)
def test_commands(spoken, tool, args):
    intent = match_one(spoken)
    assert intent is not None, spoken
    assert intent.tool == tool
    for key, value in args.items():
        assert intent.args.get(key) == value, (key, intent.args)


def test_timer_text_parses_as_a_relative_time():
    from hark.engine.tools.timeparse import parse_when

    intent = match_one("set a timer for five minutes")
    assert parse_when(intent.args["text"]) is not None


def test_unknown_phrase_falls_through():
    assert match("what is the meaning of life") == []


def test_dictated_text_about_volume_is_not_a_volume_command():
    assert match_one("type the music is too loud").tool == "input.type"


def test_compound_command_splits_when_every_part_is_a_command():
    steps = match("open notepad and then type hello")
    assert [s.tool for s in steps] == ["app.open", "input.type"]
    assert steps[0].args["name"] == "notepad"


def test_compound_split_rejected_when_a_part_is_not_a_command():
    steps = match("remember that I like salt and pepper")
    assert len(steps) == 1
    assert steps[0].tool == "memory.remember"
    assert steps[0].args["fact"] == "I like salt and pepper"


def test_searches_are_never_split():
    steps = match("search for cats and dogs")
    assert [s.tool for s in steps] == ["web.search"]
    assert steps[0].args["query"] == "cats and dogs"


def test_where_is_a_place_is_not_a_control():
    assert match_one("where is the Eiffel Tower") is None
