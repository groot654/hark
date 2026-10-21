"""The desktop client: hotkeys and microphone in, notch and inserted text out."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QColor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from hark import DISPLAY_NAME
from hark.app import clipboard_paste, win_foreground
from hark.app.audio_device import Recorder, to_wav_bytes
from hark.app.engine_client import EngineClient
from hark.app.hotkeys import HotkeyConfig, Hotkeys
from hark.app.hud import Card, Hud, HudState
from hark.app.look import get_look
from hark.app.settings_store import Settings
from hark.app.vad import SileroVad

log = logging.getLogger("hark.client")

MIN_HOLD_SECONDS = 0.25


class _Bridge(QObject):
    """Signals used to hop from hook/worker threads onto the GUI thread."""

    command_key = Signal(bool)
    dictation_key = Signal(bool)
    panel_key = Signal()
    level = Signal(float)
    result = Signal(dict)
    failure = Signal(str)
    engine_event = Signal(dict)


class HarkApp:
    def __init__(self, qt_app: QApplication, engine: EngineClient) -> None:
        self.qt = qt_app
        self.engine = engine
        self.settings = Settings()
        self.bridge = _Bridge()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hark-work")
        self.vad = SileroVad()
        threading.Thread(target=self.vad.load, daemon=True).start()

        self.hud = Hud(get_look(self.settings.look))
        self.hud.clicked.connect(self._on_hud_clicked)

        self.recorder = Recorder(device=self.settings.microphone or None, on_level=self.bridge.level.emit)
        self._mode: str | None = None
        self._pressed_at = 0.0
        self._target: win_foreground.Target | None = None
        self._pending_confirm: str | None = None

        b = self.bridge
        b.command_key.connect(lambda down: self._on_key("command", down))
        b.dictation_key.connect(lambda down: self._on_key("dictation", down))
        b.panel_key.connect(self._show_panel)
        b.level.connect(self.hud.set_level)
        b.result.connect(self._on_result)
        b.failure.connect(self._on_failure)
        b.engine_event.connect(self._on_engine_event)

        self.hotkeys = Hotkeys(
            HotkeyConfig(
                ptt=self.settings.ptt_key, dictation=self.settings.dictation_key,
                panel=self.settings.panel_key, mode=self.settings.trigger_mode,
            ),
            on_command=b.command_key.emit,
            on_dictation=b.dictation_key.emit,
            on_panel=b.panel_key.emit,
        )
        self.hotkeys.start()
        self.engine.subscribe(b.engine_event.emit)
        self._build_tray()
        try:
            self.recorder.open()
        except Exception as exc:
            log.exception("microphone unavailable")
            self.hud.show_card(Card(title="Microphone unavailable", body=str(exc), kind="error"))

    # ---- tray ----------------------------------------------------------------
    def _build_tray(self) -> None:
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#0a0d12"))
        p.setPen(QColor("#5fd7ff"))
        p.drawRoundedRect(1, 6, 30, 20, 10, 10)
        p.setBrush(QColor("#5fd7ff"))
        p.drawRoundedRect(9, 11, 5, 10, 2.5, 2.5)
        p.drawRoundedRect(18, 11, 5, 10, 2.5, 2.5)
        p.end()
        self.tray = QSystemTrayIcon(QIcon(pix), self.qt)
        self.tray.setToolTip(f"{DISPLAY_NAME} — hold {self.settings.ptt_key} to talk")
        menu = QMenu()
        settings_action = QAction("Settings…", menu, triggered=self._open_settings)
        quit_action = QAction(f"Quit {DISPLAY_NAME}", menu, triggered=self.quit)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()
        self._tray_menu = menu

    def _open_settings(self) -> None:
        from hark.app.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings)
        if dialog.exec():
            self.hud.apply_look(get_look(self.settings.look))

    def quit(self) -> None:
        self.hotkeys.stop()
        self.recorder.close()
        self.qt.quit()

    # ---- push-to-talk --------------------------------------------------------
    def _on_key(self, mode: str, down: bool) -> None:
        if down:
            if self._mode is not None:
                return
            self._mode = mode
            self._pressed_at = time.monotonic()
            self._target = win_foreground.capture()
            if mode == "dictation":
                win_foreground.suppress_menu_activation()
            self.recorder.start()
            self.hud.set_state(HudState.DICTATING if mode == "dictation" else HudState.LISTENING)
            log.info("recording started (%s) target=%s", mode, self._target.process if self._target else None)
            return
        if self._mode != mode:
            return
        self._mode = None
        samples = self.recorder.stop()
        if mode == "dictation":
            win_foreground.suppress_menu_activation()
        if time.monotonic() - self._pressed_at < MIN_HOLD_SECONDS:
            self.hud.rest()
            return
        heard, peak = self.vad.gate(samples)
        log.info("speech gate: heard=%s peak=%.3f samples=%d", heard, peak, samples.size)
        if not heard:
            self.hud.rest()
            return
        self.hud.set_state(HudState.THINKING)
        target = self._target
        self.pool.submit(self._send, to_wav_bytes(samples), mode, target)

    def _send(self, wav: bytes, mode: str, target: win_foreground.Target | None) -> None:
        try:
            info = {"process": target.process, "title": target.title, "app": target.app} if target else {}
            info["dictation_style"] = self.settings.dictation_style
            result = self.engine.listen(wav, mode, info)
            result["_mode"] = mode
            result["_target"] = target
            self.bridge.result.emit(result)
        except Exception as exc:
            log.exception("engine request failed")
            self.bridge.failure.emit(str(exc))

    # ---- results -------------------------------------------------------------
    def _on_result(self, result: dict) -> None:
        target = result.get("_target")
        log.info("final transcript: chars=%d mode=%s", len(result.get("transcript", "")), result.get("_mode"))
        for action in result.get("client_actions", []):
            self._run_client_action(action, target)
        card = result.get("card")
        if card:
            self.hud.show_card(Card(**card))
        elif result.get("say"):
            self.hud.show_card(Card(body=result["say"]))
        else:
            self.hud.rest()
        self._pending_confirm = result.get("confirm_id")

    def _run_client_action(self, action: dict, target) -> None:
        kind = action.get("type")
        if kind == "insert_text":
            text = action.get("text", "")
            self.pool.submit(clipboard_paste.insert_text, text, target)
        elif kind == "look":
            self.settings.look = action["look"]
            self.hud.apply_look(get_look(self.settings.look))

    def _on_failure(self, message: str) -> None:
        self.hud.show_card(Card(title="Something went wrong", body=message[:200], kind="error"), dismiss_ms=6000)

    def _on_engine_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "reminder.due":
            self.hud.show_card(Card(title="Reminder", body=event.get("text", "")), dismiss_ms=12_000)
        elif kind == "notify":
            self.hud.show_card(Card(title=event.get("title", DISPLAY_NAME), body=event.get("text", "")))
        elif kind == "agent.step":
            self.hud.show_card(Card(title="Working on it", items=event.get("items", []), kind="agent"), dismiss_ms=20_000)

    def _on_hud_clicked(self) -> None:
        if self.hud.state in (HudState.REPLY, HudState.ERROR):
            self.hud.rest()

    def _show_panel(self) -> None:
        def fetch() -> None:
            try:
                data = self.engine.get("/v1/productivity/summary")
                self.bridge.result.emit({"card": data["card"]})
            except Exception as exc:
                self.bridge.failure.emit(str(exc))

        self.pool.submit(fetch)
