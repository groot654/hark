"""The desktop client: hotkeys and microphone in, notch and inserted text out."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import keyboard
import numpy as np

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
from hark.app.teleprompter import Teleprompter
from hark.app.vad import SileroVad
from hark.app.wake_listener import BurstCollector, Endpointer, battery_saver_on, session_locked

log = logging.getLogger("hark.client")

MIN_HOLD_SECONDS = 0.25
PROMPTER_SPEECH_THRESHOLD = 0.5
MAX_QUEUED_BURSTS = 2


class _Bridge(QObject):
    """Signals used to hop from hook/worker threads onto the GUI thread."""

    command_key = Signal(bool)
    dictation_key = Signal(bool)
    panel_key = Signal()
    level = Signal(float)
    result = Signal(dict)
    failure = Signal(str)
    engine_event = Signal(dict)
    focus = Signal(dict)
    prompter_close = Signal()
    wake_burst = Signal(object)
    wake_result = Signal(dict)
    session_done = Signal(str)


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

        self.prompter: Teleprompter | None = None
        self._prompter_vad = SileroVad()  # its own instance: the push-to-talk gate resets shared state
        self._prompter_vad_loading = False
        self._esc_hook = None
        # Hands-free: its own VAD instance, shared by the burst collector and the end-of-request detector.
        self._wake_vad = SileroVad()
        self._wake_vad_loading = False
        self.wake = BurstCollector(self._wake_vad.frame_prob, self.bridge.wake_burst.emit)
        self.endpointer = Endpointer()
        self._wake_enabled = False
        self._wake_busy = False
        self._wake_session = False
        self._session_closing = False
        self._handoff_pending = False
        self._queued_bursts: list[np.ndarray] = []
        self._told_battery_saver = False
        self.recorder = Recorder(device=self.settings.microphone or None, on_level=self.bridge.level.emit,
                                 on_frame=self._on_audio_frame)
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
        b.focus.connect(self._apply_focus)
        b.prompter_close.connect(self._stop_prompter)
        b.wake_burst.connect(self._on_wake_burst)
        b.wake_result.connect(self._on_wake_result)
        b.session_done.connect(self._end_wake_session)

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
        self.pool.submit(self._restore_focus)
        self._build_tray()
        try:
            self.recorder.open()
        except Exception as exc:
            log.exception("microphone unavailable")
            self.hud.show_card(Card(title="Microphone unavailable", body=str(exc), kind="error"))
        self._apply_wake_setting()

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
        prompter_action = QAction("Teleprompter (copied script)", menu, triggered=self._start_prompter)
        self._wake_action = QAction("Listen for “Hey Hark”", menu, checkable=True)
        self._wake_action.setChecked(bool(self.settings.get("wake/enabled")))
        self._wake_action.toggled.connect(self._toggle_wake)
        settings_action = QAction("Settings…", menu, triggered=self._open_settings)
        quit_action = QAction(f"Quit {DISPLAY_NAME}", menu, triggered=self.quit)
        menu.addAction(self._wake_action)
        menu.addAction(prompter_action)
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
            if self.prompter:
                self.prompter.apply_look(get_look(self.settings.look))
            self._wake_action.blockSignals(True)
            self._wake_action.setChecked(bool(self.settings.get("wake/enabled")))
            self._wake_action.blockSignals(False)
            self._apply_wake_setting()

    def quit(self) -> None:
        self._stop_prompter()
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
        self._finish_recording(mode)

    def _finish_recording(self, mode: str) -> None:
        """Key released or a hands-free request ended: gate the audio and send it to the engine."""
        self._mode = None
        self._wake_session = False
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
        elif kind == "mood":
            self.hud.react(action.get("mood", ""))
        elif kind == "focus":
            self._apply_focus(action)
        elif kind == "teleprompter":
            self._start_prompter() if action.get("action") == "start" else self._stop_prompter()

    def _apply_focus(self, focus: dict) -> None:
        minutes = focus.get("minutes")
        self.hud.set_focus(focus.get("ends_at"), minutes * 60 if minutes else None)

    def _restore_focus(self) -> None:
        """Pick up a focus session that was already running when Hark (re)started."""
        try:
            focus = self.engine.get("/v1/productivity/summary").get("focus")
        except Exception:
            log.exception("could not restore focus session")
            return
        if focus and focus.get("ends_at"):
            self.bridge.focus.emit(focus)

    def _on_failure(self, message: str) -> None:
        self.hud.show_card(Card(title="Something went wrong", body=message[:200], kind="error"), dismiss_ms=6000)

    def _on_engine_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "reminder.due":
            self.hud.show_card(Card(title="Reminder", body=event.get("text", "")), dismiss_ms=12_000)
        elif kind == "notify":
            self.hud.show_card(Card(title=event.get("title", DISPLAY_NAME), body=event.get("text", "")))
        elif kind == "focus.ended":
            self.hud.set_focus(None)
        elif kind == "agent.step":
            self.hud.show_card(Card(title="Working on it", items=event.get("items", []), kind="agent"), dismiss_ms=20_000)

    def _on_hud_clicked(self) -> None:
        if self.hud.state in (HudState.REPLY, HudState.ERROR):
            self.hud.rest()
        elif self.prompter:
            self.prompter.toggle_pause()

    # ---- teleprompter ------------------------------------------------------------
    def _start_prompter(self) -> None:
        script = self.qt.clipboard().text().strip()
        if not script:
            self.hud.show_card(Card(title="Teleprompter", body="Copy your script, then say “start teleprompter” again."),
                               dismiss_ms=4200)
            return
        self._stop_prompter()
        if not self._prompter_vad_loading:
            self._prompter_vad_loading = True
            threading.Thread(target=self._prompter_vad.load, name="prompter-vad", daemon=True).start()
        self._prompter_vad.reset()
        self.prompter = Teleprompter(script, get_look(self.settings.look))
        self.prompter.closed.connect(self._on_prompter_closed)
        self.prompter.start()
        self._esc_hook = keyboard.add_hotkey("esc", self.bridge.prompter_close.emit, suppress=False)
        log.info("teleprompter started: %d words", self.prompter.pacer.total)

    def _stop_prompter(self) -> None:
        if self.prompter is not None:
            self.prompter.close()  # emits closed -> _on_prompter_closed

    def _on_prompter_closed(self) -> None:
        if self._esc_hook is not None:
            keyboard.remove_hotkey(self._esc_hook)
            self._esc_hook = None
        if self.prompter is not None:
            log.info("teleprompter closed at %d%%", round(self.prompter.pacer.progress * 100))
            self.prompter.deleteLater()
        self.prompter = None

    def _on_audio_frame(self, block: np.ndarray) -> None:
        """Audio thread: tell the teleprompter when it hears speech (not while push-to-talk records)."""
        if self._handoff_pending:
            # A bare wake phrase was just confirmed: start the request with any speech already under way.
            self._handoff_pending = False
            seed, flags = self.wake.take()
            for speaking in flags:
                self.endpointer.feed(1.0 if speaking else 0.0)
            self.recorder.start(seed)
            self._wake_session = True
        if self._wake_session:
            if self.recorder.recording and not self._session_closing:
                verdict = self.endpointer.feed(self._wake_vad.frame_prob(block))
                if verdict != "continue":
                    self._session_closing = True
                    self.bridge.session_done.emit(verdict)
            return
        prompter = self.prompter
        if prompter is not None:
            if not self.recorder.recording and self._prompter_vad.frame_prob(block) >= PROMPTER_SPEECH_THRESHOLD:
                prompter.mark_speech()
            return
        if self._wake_enabled and self._mode is None and not self.recorder.recording:
            self.wake.feed(block)  # keeps listening while a burst is being checked, so nothing is missed

    # ---- hands-free ("Hey Hark") ----------------------------------------------------
    def _toggle_wake(self, enabled: bool) -> None:
        self.settings.set("wake/enabled", enabled)
        self._apply_wake_setting()
        phrase = self.settings.get("wake/phrase") or "hey hark"
        self.hud.show_card(Card(body=f"“{phrase.title()}” is {'on' if enabled else 'off'}."), dismiss_ms=2600)

    def _apply_wake_setting(self) -> None:
        enabled = bool(self.settings.get("wake/enabled"))
        if enabled and not self._wake_vad_loading:
            self._wake_vad_loading = True
            threading.Thread(target=self._wake_vad.load, name="wake-vad", daemon=True).start()
        self.wake.reset()
        self._wake_enabled = enabled
        log.info("hands-free listening %s", "on" if enabled else "off")

    def _on_wake_burst(self, samples: np.ndarray) -> None:
        if self._mode is not None or not self._wake_enabled:
            return
        if self._wake_busy:
            # Heard while the previous burst is being checked: it may be the request after "Hey Hark".
            self._queued_bursts = (self._queued_bursts + [samples])[-MAX_QUEUED_BURSTS:]
            return
        self._check_wake(samples)

    def _check_wake(self, samples: np.ndarray) -> None:
        if session_locked():
            log.info("session is locked; ignoring speech")
            return
        if battery_saver_on():
            if not self._told_battery_saver:  # say it once, so a silent Hark isn't a mystery
                self._told_battery_saver = True
                self.hud.show_card(Card(body="“Hey Hark” rests while battery saver is on."), dismiss_ms=3200)
            log.info("battery saver is on; ignoring speech")
            return
        self._told_battery_saver = False
        self._wake_busy = True
        self.pool.submit(self._send_wake, to_wav_bytes(samples), win_foreground.capture())

    def _send_wake(self, wav: bytes, target: win_foreground.Target | None) -> None:
        result: dict = {"wake": False}
        try:
            info = {"process": target.process, "title": target.title, "app": target.app} if target else {}
            info["wake_phrase"] = self.settings.get("wake/phrase") or "hey hark"
            result = self.engine.listen(wav, "wake", info)
        except Exception:
            log.exception("wake check failed")
        result["_mode"] = "command"
        result["_target"] = target
        self.bridge.wake_result.emit(result)

    def _on_wake_result(self, result: dict) -> None:
        self._wake_busy = False
        queued, self._queued_bursts = self._queued_bursts, []
        if not result.get("wake"):
            if queued:  # check what was said meanwhile
                self._queued_bursts = queued[1:]
                self._check_wake(queued[0])
            return
        if not result.get("follow_up"):
            self._on_result(result)
        elif queued:
            # "Hey Hark … open Spotify": the request already arrived as its own burst.
            log.info("hands-free request taken from the next burst")
            self.hud.set_state(HudState.THINKING)
            self.pool.submit(self._send, to_wav_bytes(queued[0]), "command", result["_target"])
        else:
            self._start_wake_session(result["_target"])

    def _start_wake_session(self, target) -> None:
        """The wake phrase on its own: listen for the request as if the key were held, until a pause.
        The audio thread starts the recording so it can keep speech that's already under way."""
        if self._mode is not None:
            return
        self._mode = "command"
        self._target = target
        self._pressed_at = time.monotonic()
        self.endpointer.reset()
        self._session_closing = False
        self._handoff_pending = True
        self.hud.set_state(HudState.LISTENING)
        log.info("hands-free request started")

    def _end_wake_session(self, verdict: str) -> None:
        if not self._wake_session:
            return
        if verdict == "cancel":
            self._wake_session = False
            self._mode = None
            self.recorder.stop()
            self.hud.rest()
            log.info("hands-free request cancelled: nothing said")
            return
        self._finish_recording("command")

    def _show_panel(self) -> None:
        def fetch() -> None:
            try:
                data = self.engine.get("/v1/productivity/summary")
                self.bridge.result.emit({"card": data["card"]})
            except Exception as exc:
                self.bridge.failure.emit(str(exc))

        self.pool.submit(fetch)
