"""Foreground-window capture and restore, so text lands where the user was typing."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass

import psutil

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

KEYEVENTF_KEYUP = 0x0002
VK_UNASSIGNED = 0xE8  # injected to stop a lone Alt press from opening the menu bar


@dataclass(frozen=True)
class Target:
    hwnd: int
    pid: int
    process: str
    title: str

    @property
    def app(self) -> str:
        return self.process.lower().removesuffix(".exe")


def capture() -> Target | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    try:
        name = psutil.Process(pid.value).name()
    except psutil.Error:
        name = ""
    return Target(hwnd=int(hwnd), pid=pid.value, process=name, title=buf.value)


def is_foreground(target: Target) -> bool:
    return int(user32.GetForegroundWindow() or 0) == target.hwnd


def restore(target: Target, timeout: float = 0.6) -> bool:
    """Bring `target` back to the front; returns True once it is verified."""
    if not user32.IsWindow(target.hwnd):
        return False
    if is_foreground(target):
        return True
    # Windows only lets the foreground process hand focus over; a synthetic
    # key event makes this process the last input source so the call succeeds.
    suppress_menu_activation()
    user32.SetForegroundWindow(target.hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_foreground(target):
            return True
        time.sleep(0.02)
    log.warning("could not restore focus to %s (%r)", target.process, target.title)
    return False


def suppress_menu_activation() -> None:
    user32.keybd_event(VK_UNASSIGNED, 0, 0, 0)
    user32.keybd_event(VK_UNASSIGNED, 0, KEYEVENTF_KEYUP, 0)
