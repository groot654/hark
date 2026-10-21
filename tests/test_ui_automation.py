import pytest

from hark.engine.tools import ui_automation as ui
from hark.engine.tools.ui_automation import Control, pick, split_role

WINDOW = [
    Control("Send", "Button", (10, 10, 60, 30)),
    Control("Send later", "MenuItem", (10, 40, 90, 60)),
    Control("Seven", "Button", (0, 100, 40, 140)),
    Control("Plus", "Button", (50, 100, 90, 140)),
    Control("Search", "Edit", (100, 0, 300, 24)),
    Control("Search the web", "Hyperlink", (100, 30, 220, 50)),
    Control("File", "MenuItem", (0, 0, 30, 20)),
    Control("Bold", "TabItem", (0, 200, 40, 220)),
    Control("Bold", "Button", (50, 200, 70, 220)),
]


@pytest.mark.parametrize(("spoken", "text", "role"), [
    ("the send button", "send", "button"), ("File menu", "file", "menu"), ("search box", "search", "box"),
    ("seven", "seven", None), ("button", "button", None),
])
def test_split_role(spoken, text, role):
    assert split_role(spoken) == (text, role)


def test_digits_match_number_words():
    assert pick("7", WINDOW).control.name == "Seven"


def test_exact_name_is_clear():
    choice = pick("send", WINDOW)
    assert choice.control.name == "Send" and choice.clear


def test_role_word_steers_the_choice():
    assert pick("search box", WINDOW).control.kind == "Edit"
    assert pick("the bold tab", WINDOW).control.kind == "TabItem"
    assert pick("the bold button", WINDOW).control.kind == "Button"


def test_partial_name_is_not_clear():
    choice = pick("later", WINDOW)
    assert choice.control.name == "Send later" and not choice.clear


def test_close_spelling_is_found_but_asked_about():
    choice = pick("plas", WINDOW)
    assert choice.control is None or not choice.clear


def test_nothing_matches():
    assert pick("checkout", WINDOW).control is None


@pytest.fixture
def fake_window(monkeypatch):
    pressed = []
    monkeypatch.setattr(ui, "foreground_window", lambda: 4242)
    monkeypatch.setattr(ui, "is_own_window", lambda hwnd: False)
    monkeypatch.setattr(ui, "list_controls", lambda hwnd: list(WINDOW))
    monkeypatch.setattr(ui, "press", lambda control: pressed.append(control.name) or "invoke")
    return pressed


def test_click_presses_and_shows_where(store, fake_window):
    from conftest import FakeLLM, NoApps
    from hark.engine.core.orchestrator import Orchestrator
    from hark.engine.eventbus import EventBus

    o = Orchestrator(store, FakeLLM(), NoApps(), EventBus())
    out = o.handle("click send", target={"hwnd": 4242})
    assert fake_window == ["Send"]
    assert out["client_actions"][0] == {"type": "point", "rect": [10, 10, 60, 30], "duration_ms": 900}


def test_unclear_click_asks_first(store, fake_window):
    from conftest import FakeLLM, NoApps
    from hark.engine.core.orchestrator import Orchestrator
    from hark.engine.eventbus import EventBus

    o = Orchestrator(store, FakeLLM(), NoApps(), EventBus())
    out = o.handle("click later")
    assert out["say"] == "Click “Send later”?" and "confirm_id" in out
    assert fake_window == []
    o.handle("yes")
    assert fake_window == ["Send later"]


def test_missing_control_says_so(store, fake_window):
    from conftest import FakeLLM, NoApps
    from hark.engine.core.orchestrator import Orchestrator
    from hark.engine.eventbus import EventBus

    o = Orchestrator(store, FakeLLM(), NoApps(), EventBus())
    out = o.handle("click checkout")
    assert out["status"] == "error" and "can't see" in out["say"]


def test_never_clicks_inside_hark(store, monkeypatch):
    from conftest import FakeLLM, NoApps
    from hark.engine.core.orchestrator import Orchestrator
    from hark.engine.eventbus import EventBus

    monkeypatch.setattr(ui, "is_own_window", lambda hwnd: True)
    o = Orchestrator(store, FakeLLM(), NoApps(), EventBus())
    assert "Click into the app" in o.handle("click send", target={"hwnd": 1})["say"]


WINDOWS = [
    (1, "CalculatorApp.exe", "Calculator"),
    (2, "ApplicationFrameHost.exe", "Calculator"),
    (3, "notepad.exe", "Untitled - Notepad"),
    (4, "chrome.exe", "New Tab - Google Chrome"),
    (5, "KeePass.exe", "Password manager"),
    (6, "WINWORD.EXE", "Report.docx - Word"),
]


@pytest.mark.parametrize(("names", "expected"), [
    (["calculator"], [1, 2]), (["notepad"], [3]), (["chrome"], [4]), (["word"], [6]),
    (["Google Chrome", "chrome"], [4]), (["spotify"], []),
])
def test_windows_matching(names, expected):
    from hark.engine.tools.system import windows_matching

    assert windows_matching(WINDOWS, names) == expected
