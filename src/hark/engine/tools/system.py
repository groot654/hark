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
