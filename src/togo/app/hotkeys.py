"""Global hotkeys: hold-to-talk for commands, hold-to-dictate, and a panel toggle.

Callbacks run on the `keyboard` hook thread; the Qt side must marshal them
onto the GUI thread (see TogoApp, which wraps them in signals).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import keyboard

log = logging.getLogger(__name__)


@dataclass
class HotkeyConfig:
    ptt: str = "right ctrl"
    dictation: str = "right alt"
    panel: str = "f9"
    mode: str = "hold"  # "hold" or "toggle"


class Hotkeys:
    def __init__(
        self,
        config: HotkeyConfig,
        on_command: Callable[[bool], None],
        on_dictation: Callable[[bool], None],
        on_panel: Callable[[], None],
    ) -> None:
        self.config = config
        self._on_command = on_command
        self._on_dictation = on_dictation
        self._on_panel = on_panel
        self._down: set[str] = set()
        self._toggled: dict[str, bool] = {}
        self._hooks: list = []

    def start(self) -> None:
        for key, handler in ((self.config.ptt, self._on_command), (self.config.dictation, self._on_dictation)):
            self._hooks.append(keyboard.on_press_key(key, self._make_press(key, handler), suppress=False))
            self._hooks.append(keyboard.on_release_key(key, self._make_release(key, handler), suppress=False))
        self._hooks.append(keyboard.add_hotkey(self.config.panel, self._on_panel, suppress=False))
        log.info(
            "global hotkeys active: push-to-talk=%s dictation=%s panel=%s mode=%s",
            self.config.ptt, self.config.dictation, self.config.panel, self.config.mode,
        )

    def stop(self) -> None:
        keyboard.unhook_all()
        self._hooks.clear()

    def _make_press(self, key: str, handler: Callable[[bool], None]):
        def press(_event) -> None:
            if key in self._down:  # key repeat while held
                return
            self._down.add(key)
            if self.config.mode == "toggle":
                active = not self._toggled.get(key, False)
                self._toggled[key] = active
                handler(active)
            else:
                handler(True)

        return press

    def _make_release(self, key: str, handler: Callable[[bool], None]):
        def release(_event) -> None:
            self._down.discard(key)
            if self.config.mode == "hold":
                handler(False)

        return release
