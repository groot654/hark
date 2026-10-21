"""Find and press controls in the window in front ("click send", "press the save button").

Windows UI Automation lists the window's clickable controls in one cached query; spoken names are
matched against them; the chosen control is pressed through its own automation pattern (invoke,
toggle, select, expand), falling back to a mouse click at its centre.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher

log = logging.getLogger(__name__)

SEARCH_TIMEOUT_S = 2.5
MAX_CONTROLS = 3000
CLEAR_WIN = 0.9  # below this, or with a close runner-up, ask before clicking
RUNNER_UP_GAP = 0.05

# Spoken role words -> control type names (see _TYPES).
ROLES = {
    "button": {"Button", "SplitButton"}, "link": {"Hyperlink"}, "tab": {"TabItem"},
    "menu": {"MenuItem"}, "menu item": {"MenuItem"}, "checkbox": {"CheckBox"}, "check box": {"CheckBox"},
    "option": {"RadioButton", "ListItem", "MenuItem"}, "radio button": {"RadioButton"},
    "box": {"Edit", "ComboBox"}, "field": {"Edit", "ComboBox"}, "text box": {"Edit"}, "search box": {"Edit", "ComboBox"},
    "item": {"ListItem", "TreeItem"}, "icon": {"Button", "ListItem"}, "dropdown": {"ComboBox"},
}
ROLE_SUFFIX = re.compile(r"\s+(?:" + "|".join(sorted(map(re.escape, ROLES), key=len, reverse=True)) + r")$")
TYPE_PRIORITY = ["Button", "SplitButton", "MenuItem", "Hyperlink", "TabItem", "CheckBox", "RadioButton",
                 "ListItem", "TreeItem", "ComboBox", "Edit"]
NUMBERS = {str(i): w for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}


@dataclass
class Control:
    name: str
    kind: str  # one of TYPE_PRIORITY
    rect: tuple[int, int, int, int]  # left, top, right, bottom in physical screen pixels
    element: object = field(default=None, repr=False, compare=False)

    @property
    def centre(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2


@dataclass
class Pick:
    control: Control | None
    clear: bool  # safe to act without asking
    score: float = 0.0


# ---- matching (pure, no Windows calls) ------------------------------------------------------
def split_role(spoken: str) -> tuple[str, str | None]:
    """"the send button" -> ("send", "button")."""
    text = normalise(spoken)
    m = ROLE_SUFFIX.search(text)
    if m and m.start() > 0:
        return text[: m.start()], m.group(0).strip()
    return text, None


def normalise(text: str) -> str:
    text = re.sub(r"^(?:the|a|an)\s+", "", text.lower().strip())
    text = re.sub(r"[^\w\s+#.-]|(?<!\d)\.|\.(?!\d)", " ", text)
    words = [NUMBERS.get(w, w) for w in text.split()]
    return " ".join(words)


def score(spoken: str, name: str) -> float:
    name = normalise(name)
    if not name or not spoken:
        return 0.0
    if name == spoken:
        return 1.0
    said, words = spoken.split(), name.split()
    if words[: len(said)] == said:
        return 0.92 - 0.01 * (len(words) - len(said))
    if set(said) <= set(words):
        return 0.85 - 0.02 * (len(words) - len(said))
    ratio = SequenceMatcher(None, spoken, name).ratio()
    return ratio * 0.85 if ratio >= 0.75 else 0.0


def pick(spoken: str, controls: list[Control]) -> Pick:
    text, role = split_role(spoken)
    wanted = ROLES.get(role or "", set())
    ranked = []
    for c in controls:
        s = score(text, c.name)
        if s <= 0:
            continue
        if wanted:
            s += 0.05 if c.kind in wanted else -0.1
        area = max(1, (c.rect[2] - c.rect[0]) * (c.rect[3] - c.rect[1]))
        priority = TYPE_PRIORITY.index(c.kind) if c.kind in TYPE_PRIORITY else len(TYPE_PRIORITY)
        ranked.append((round(s, 3), -priority, -area, c))
    if not ranked:
        return Pick(None, False)
    ranked.sort(key=lambda r: r[:3], reverse=True)
    best = ranked[0]
    runner_up = next((r for r in ranked[1:] if normalise(r[3].name) != normalise(best[3].name)), None)
    clear = best[0] >= CLEAR_WIN and (runner_up is None or best[0] - runner_up[0] > RUNNER_UP_GAP)
    return Pick(best[3], clear, best[0])


# ---- Windows UI Automation ------------------------------------------------------------------
_local = threading.local()


def _uia():
    """The UI Automation client for this thread (COM is set up per thread, multithreaded)."""
    if getattr(_local, "uia", None) is None:
        import comtypes
        import comtypes.client

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # already initialised on this thread
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U

        _local.U = U
        _local.uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    return _local.uia, _local.U


def window_owner_pid(hwnd: int) -> int:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_window() -> int:
    return ctypes.windll.user32.GetForegroundWindow()


def list_controls(hwnd: int) -> list[Control]:
    """The visible, enabled clickable controls of a window. Raises TimeoutError for very slow windows."""
    result: dict = {}

    def work() -> None:
        try:
            result["controls"] = _list_controls(hwnd)
        except Exception as exc:  # surfaced to the caller below
            result["error"] = exc

    worker = threading.Thread(target=work, name="uia-search", daemon=True)
    worker.start()
    worker.join(SEARCH_TIMEOUT_S)
    if worker.is_alive():
        raise TimeoutError("that window took too long to read")
    if "error" in result:
        raise result["error"]
    return result["controls"]


def _list_controls(hwnd: int) -> list[Control]:
    uia, U = _uia()
    types = {getattr(U, f"UIA_{t}ControlTypeId"): t for t in TYPE_PRIORITY}
    kind = uia.CreateOrConditionFromArray([uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, t) for t in types])
    condition = uia.CreateAndConditionFromArray([
        kind,
        uia.CreatePropertyCondition(U.UIA_IsOffscreenPropertyId, False),
        uia.CreatePropertyCondition(U.UIA_IsEnabledPropertyId, True),
    ])
    cache = uia.CreateCacheRequest()
    for prop in (U.UIA_NamePropertyId, U.UIA_ControlTypePropertyId, U.UIA_BoundingRectanglePropertyId):
        cache.AddProperty(prop)
    found = uia.ElementFromHandle(hwnd).FindAllBuildCache(U.TreeScope_Descendants, condition, cache)
    controls = []
    for i in range(min(found.Length, MAX_CONTROLS)):
        element = found.GetElement(i)
        name = (element.CachedName or "").strip()
        r = element.CachedBoundingRectangle
        if name and r.right > r.left and r.bottom > r.top:
            controls.append(Control(name, types.get(element.CachedControlType, "Button"),
                                    (r.left, r.top, r.right, r.bottom), element))
    return controls


def press(control: Control) -> str:
    """Press a control the way its app expects. Returns how it was done (for the log)."""
    _uia_obj, U = _uia()
    element = control.element
    attempts = [
        (U.UIA_InvokePatternId, U.IUIAutomationInvokePattern, lambda p: p.Invoke(), "invoke"),
        (U.UIA_TogglePatternId, U.IUIAutomationTogglePattern, lambda p: p.Toggle(), "toggle"),
        (U.UIA_SelectionItemPatternId, U.IUIAutomationSelectionItemPattern, lambda p: p.Select(), "select"),
        (U.UIA_ExpandCollapsePatternId, U.IUIAutomationExpandCollapsePattern, lambda p: p.Expand(), "expand"),
    ]
    if control.kind in ("Edit", "ComboBox"):
        element.SetFocus()
        return "focus"
    for pattern_id, interface, run, how in attempts:
        try:
            pattern = element.GetCurrentPattern(pattern_id)
            if pattern:
                run(pattern.QueryInterface(interface))
                return how
        except Exception:
            continue
    _mouse_click(*control.centre)
    return "mouse"


def _mouse_click(x: int, y: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    for flag in (0x0002, 0x0004):  # MOUSEEVENTF_LEFTDOWN, LEFTUP
        user32.mouse_event(flag, 0, 0, 0, 0)


def is_own_window(hwnd: int) -> bool:
    return window_owner_pid(hwnd) == os.getpid()
