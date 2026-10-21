"""User settings, persisted with QSettings (HKCU\\Software\\Togo\\togo)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

DEFAULTS: dict[str, Any] = {
    "audio/microphone": "",
    "hotkeys/ptt": "right ctrl",
    "hotkeys/dictation": "right alt",
    "hotkeys/panel": "f9",
    "hotkeys/mode": "hold",
    "dictation/style": "clean",  # exact | clean | polished
    "wake/enabled": False,
    "wake/phrase": "hey togo",
    "look/scheme": "arc",
    "look/hide_in_fullscreen": True,
    "stt/backend": "parakeet",  # parakeet | whisper
    "tts/enabled": False,
    "history/retention_days": 30,
    "llm/mode": "builtin",  # builtin | external | off
    "llm/size": "small",  # small (0.8B) | medium (2B) | large (4B), for the built-in model
    "llm/url": "",
    "llm/model": "",
}


class Settings:
    def __init__(self) -> None:
        self._q = QSettings("Togo", "togo")

    def get(self, key: str) -> Any:
        default = DEFAULTS.get(key)
        value = self._q.value(key, default)
        if isinstance(default, bool) and isinstance(value, str):
            return value.lower() in ("1", "true", "yes")
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        self._q.setValue(key, value)
        self._q.sync()

    # Convenience accessors used across the client.
    microphone = property(lambda s: s.get("audio/microphone"))
    ptt_key = property(lambda s: s.get("hotkeys/ptt"))
    dictation_key = property(lambda s: s.get("hotkeys/dictation"))
    panel_key = property(lambda s: s.get("hotkeys/panel"))
    trigger_mode = property(lambda s: s.get("hotkeys/mode"))
    dictation_style = property(lambda s: s.get("dictation/style"))

    @property
    def look(self) -> str:
        return self.get("look/scheme")

    @look.setter
    def look(self, value: str) -> None:
        self.set("look/scheme", value)
