"""Insert text into the captured window by pasting, then put the user's clipboard back."""

from __future__ import annotations

import logging
import time

import keyboard
import win32clipboard
import win32con

from hark.app import win_foreground
from hark.app.win_foreground import Target

log = logging.getLogger(__name__)


def _read_clipboard_text() -> str | None:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:  # clipboard held by another process
            time.sleep(0.03)
    return None


def _write_clipboard_text(text: str) -> bool:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.03)
    return False


def copy_selection(timeout: float = 0.4) -> str | None:
    """Copy whatever is selected in the foreground window (for rewrites)."""
    previous = _read_clipboard_text()
    sentinel = "⁣hark-selection-probe⁣"
    _write_clipboard_text(sentinel)
    keyboard.send("ctrl+c")
    deadline = time.monotonic() + timeout
    selected = None
    while time.monotonic() < deadline:
        current = _read_clipboard_text()
        if current is not None and current != sentinel:
            selected = current
            break
        time.sleep(0.03)
    _write_clipboard_text(previous or "")
    return selected


def insert_text(text: str, target: Target | None, restore_clipboard: bool = True) -> bool:
    if not text:
        return False
    if target is not None and not win_foreground.restore(target):
        return False
    previous = _read_clipboard_text() if restore_clipboard else None
    if not _write_clipboard_text(text):
        log.warning("clipboard unavailable; typing instead")
        keyboard.write(text, delay=0.002)
        return True
    keyboard.send("ctrl+v")
    if restore_clipboard:
        # Give the target time to read the clipboard before we restore it.
        time.sleep(0.4)
        if previous is not None:
            _write_clipboard_text(previous)
    log.info("inserted %d chars into %s", len(text), target.process if target else "foreground")
    return True
