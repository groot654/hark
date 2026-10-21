"""Settings window: microphone, hotkeys, dictation style, look, speech model."""

from __future__ import annotations

import sounddevice as sd
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from hark.app import autostart
from hark.app.look import LOOKS
from hark.app.settings_store import Settings

AUTOSTART = "general/autostart"
RESTART_KEYS = {"hotkeys/ptt", "hotkeys/dictation", "hotkeys/panel", "hotkeys/mode", "stt/backend", "audio/microphone",
                "llm/mode", "llm/url", "llm/model", "llm/size"}


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("Hark settings")
        self.setMinimumWidth(460)
        self._fields: dict[str, QWidget] = {}

        tabs = QTabWidget()
        tabs.addTab(self._page([
            (AUTOSTART, "Start Hark when I sign in", QCheckBox()),
        ]), "General")
        tabs.addTab(self._page([
            ("audio/microphone", "Microphone", self._mic_combo()),
            ("hotkeys/ptt", "Command key (hold to talk)", QLineEdit()),
            ("hotkeys/dictation", "Dictation key", QLineEdit()),
            ("hotkeys/panel", "Panel key", QLineEdit()),
            ("hotkeys/mode", "Trigger", self._combo([("hold", "Hold to talk"), ("toggle", "Press to start, press to stop")])),
        ]), "Talking")
        tabs.addTab(self._page([
            ("dictation/style", "Dictation style", self._combo([
                ("exact", "Exact: word for word"), ("clean", "Clean: punctuation, no fillers"),
                ("polished", "Polished: tidied by the AI model")])),
            ("wake/enabled", "Listen for the wake phrase", QCheckBox()),
            ("wake/phrase", "Wake phrase", QLineEdit(placeholderText="hey hark")),
            ("stt/backend", "Speech recognition", self._combo([("parakeet", "Fast (Parakeet)"), ("whisper", "Enhanced (Whisper)")])),
        ]), "Dictation")
        tabs.addTab(self._page([
            ("look/scheme", "Colours", self._combo([(k, v.name) for k, v in LOOKS.items()])),
            ("look/hide_in_fullscreen", "Step aside for full-screen apps", QCheckBox()),
        ]), "Look")
        retention = QSpinBox()
        retention.setRange(0, 3650)
        retention.setSuffix(" days")
        tabs.addTab(self._page([
            ("history/retention_days", "Keep conversation history for", retention),
            ("llm/mode", "AI model", self._combo([
                ("builtin", "Built in: Qwen 3.5, runs on this PC"),
                ("external", "Ollama or another server"), ("off", "Off: commands only")])),
            ("llm/size", "Built-in model size", self._combo([
                ("small", "Small: fastest (0.5 GB download)"), ("medium", "Medium: better writing (1.3 GB)"),
                ("large", "Large: best, needs ~3.5 GB free memory (2.7 GB)")])),
            ("llm/url", "Server address (external)", QLineEdit(placeholderText="Ollama, found automatically")),
            ("llm/model", "Model name (external)", QLineEdit()),
        ]), "Privacy && AI")

        self._note = QLabel("Hands-free listening transcribes speech it hears nearby to look for the wake phrase, "
                            "so it uses more CPU in busy rooms. Nothing that isn't meant for Hark is kept.")
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: #888")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self._note)
        layout.addWidget(buttons)

    def _mic_combo(self) -> QComboBox:
        options = [("", "System default")]
        try:
            for dev in sd.query_devices():
                if dev["max_input_channels"] > 0 and dev["hostapi"] == 0:
                    options.append((dev["name"], dev["name"]))
        except Exception:
            pass
        return self._combo(options)

    @staticmethod
    def _combo(options: list[tuple[str, str]]) -> QComboBox:
        box = QComboBox()
        for value, label in options:
            box.addItem(label, value)
        return box

    def _page(self, rows: list[tuple[str, str, QWidget]]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for key, label, widget in rows:
            value = autostart.is_enabled() if key == AUTOSTART else self.settings.get(key)
            if isinstance(widget, QComboBox):
                index = widget.findData(value)
                widget.setCurrentIndex(max(0, index))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value or ""))
            form.addRow(label, widget)
            self._fields[key] = widget
        return page

    def _save(self) -> None:
        changed_restart = False
        for key, widget in self._fields.items():
            if isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            else:
                value = widget.text().strip()
            if key == AUTOSTART:  # lives in the Windows Run key, not in Hark's settings
                if value != autostart.is_enabled():
                    autostart.set_enabled(value)
                continue
            if value != self.settings.get(key) and key in RESTART_KEYS:
                changed_restart = True
            self.settings.set(key, value)
        if changed_restart:
            self._note.setText("Some changes apply after restarting Hark.")
        self.accept()
