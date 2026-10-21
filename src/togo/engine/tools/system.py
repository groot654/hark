"""Windows actions that need no AI: volume, media keys, key presses, URLs, system stats."""

from __future__ import annotations

import ctypes
import datetime as dt
import logging
import urllib.parse
import webbrowser

import keyboard
import psutil

log = logging.getLogger(__name__)

VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD, "volume_up": 0xAF, "volume_down": 0xAE}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "bing": "https://www.bing.com/search?q={}",
    "amazon": "https://www.amazon.com/s?k={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "github": "https://github.com/search?q={}",
    "maps": "https://www.google.com/maps/search/{}",
    "images": "https://www.google.com/search?tbm=isch&q={}",
    "reddit": "https://www.reddit.com/search/?q={}",
    "spotify": "https://open.spotify.com/search/{}",
}

SITES = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "maps": "https://maps.google.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "whatsapp web": "https://web.whatsapp.com",
    "outlook": "https://outlook.live.com",
    "wikipedia": "https://www.wikipedia.org",
    "stack overflow": "https://stackoverflow.com",
}


def press_vk(code: int) -> None:
    ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(code, 0, 2, 0)


def media(action: str) -> None:
    press_vk(VK[action])


def _endpoint_volume():
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> int:
    return round(_endpoint_volume().GetMasterVolumeLevelScalar() * 100)


def set_volume(percent: int) -> int:
    percent = max(0, min(100, percent))
    vol = _endpoint_volume()
    vol.SetMute(0, None)
    vol.SetMasterVolumeLevelScalar(percent / 100, None)
    return percent


def change_volume(delta: int) -> int:
    return set_volume(get_volume() + delta)


def set_mute(muted: bool) -> None:
    _endpoint_volume().SetMute(1 if muted else 0, None)


def press_keys(combo: str) -> None:
    keyboard.send(combo)


def type_text(text: str) -> None:
    keyboard.write(text, delay=0.004)


def open_url(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)


def search(query: str, engine: str = "google") -> str:
    url = SEARCH_URLS.get(engine, SEARCH_URLS["google"]).format(urllib.parse.quote_plus(query))
    webbrowser.open(url)
    return url


def stats() -> dict:
    battery = psutil.sensors_battery()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("C:\\").percent,
        "battery_percent": round(battery.percent) if battery else None,
        "plugged_in": battery.power_plugged if battery else None,
        "uptime_hours": round((dt.datetime.now().timestamp() - psutil.boot_time()) / 3600, 1),
    }


def lock_screen() -> None:
    ctypes.windll.user32.LockWorkStation()


WM_CLOSE = 0x0010


def windows_matching(windows: list[tuple[int, str, str]], names: list[str]) -> list[int]:
    """Handles of top-level windows that belong to an app: its process name, or a whole-word match in the
    title ("Calculator", "Untitled - Notepad", "New Tab - Google Chrome"). `windows` is (hwnd, process, title)."""
    import re

    wanted = [n.lower().strip() for n in names if n and n.strip()]
    found = []
    for hwnd, process, title in windows:
        process = process.lower().removesuffix(".exe")
        if any(process == w.replace(" ", "") for w in wanted) or any(
                re.search(rf"(?<!\w){re.escape(w)}(?!\w)", title.lower()) for w in wanted):
            found.append(hwnd)
    return found


def top_level_windows() -> list[tuple[int, str, str]]:
    """Visible, titled top-level windows of other processes: (hwnd, process name, title)."""
    import os

    user32 = ctypes.windll.user32
    result: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindow(hwnd, 4) == 0:  # GW_OWNER: skip owned popups
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if title.value and pid.value != os.getpid():
                try:
                    name = psutil.Process(pid.value).name()
                except psutil.Error:
                    name = ""
                result.append((int(hwnd), name, title.value))
        return True

    user32.EnumWindows(visit, 0)
    return result


def close_windows(names: list[str]) -> int:
    """Ask an app's windows to close, as clicking ✕ would (so it can offer to save). Returns how many."""
    handles = windows_matching(top_level_windows(), names)
    for hwnd in handles:
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return len(handles)
