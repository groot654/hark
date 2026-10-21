"""Teleprompter: the copied script scrolls in a strip just below the notch, moving while you speak.

Pacing is voice-driven but not word-matched: while the speech detector hears you, the script
advances at a natural reading pace, and it holds whenever you pause. Click the strip to pause,
scroll to nudge, Esc or the ✕ to close. The strip is hidden from screen capture and sharing.
"""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from hark.app.look import Look

WORDS_PER_SECOND = 2.6  # about 155 words a minute, a comfortable reading pace
SPEECH_HANGOVER_S = 0.45  # keep moving this long after the last speech frame (gaps between words)
DONE_HOLD_MS = 2500  # how long "Done" shows before the strip closes
VISIBLE_LINES = 3  # previous, current (middle row, fixed), next
SCROLL_EASE = 0.72  # per 33 ms frame: a new line glides into place in about 0.2 s
LINE_ALPHA = {-1: 0.35, 0: 1.0, 1: 0.6}
LINE_HEIGHT = 34
PAD_X, PAD_TOP, FOOTER_H = 28, 12, 22
TOP_OFFSET = 44  # below the resting notch
WDA_EXCLUDEFROMCAPTURE = 0x11


class ScriptPacer:
    """Where the reader is in the script, measured in words."""

    def __init__(self, script: str, words_per_second: float = WORDS_PER_SECOND) -> None:
        self.words = script.split()
        self.words_per_second = words_per_second
        self.position = 0.0
        self.paused = False

    @property
    def total(self) -> int:
        return len(self.words)

    @property
    def progress(self) -> float:
        return self.position / self.total if self.total else 1.0

    @property
    def finished(self) -> bool:
        return self.position >= self.total

    def advance(self, dt: float, speaking: bool) -> None:
        if speaking and not self.paused and not self.finished:
            self.position = min(float(self.total), self.position + self.words_per_second * dt)

    def nudge(self, words: float) -> None:
        self.position = min(float(self.total), max(0.0, self.position + words))


@dataclass
class Line:
    start: int  # index of the first word
    end: int  # index after the last word
    words: list[str]


def wrap_lines(script: str, width: float, measure) -> list[Line]:
    """Greedy word wrap that keeps paragraph breaks and each line's word range in the whole script.
    `measure(text)` returns the drawn width of `text`."""
    lines: list[Line] = []
    index = 0
    space = measure(" ")
    for paragraph in script.splitlines():
        words = paragraph.split()
        if not words:
            if lines and lines[-1].words:
                lines.append(Line(index, index, []))  # blank line between paragraphs
            continue
        current: list[str] = []
        used = 0.0
        start = index
        for word in words:
            w = measure(word)
            if current and used + space + w > width:
                lines.append(Line(start, start + len(current), current))
                start += len(current)
                current, used = [], 0.0
            used += (space if current else 0.0) + w
            current.append(word)
        lines.append(Line(start, start + len(current), current))
        index = start + len(current)
    while lines and not lines[-1].words:
        lines.pop()
    return lines


class Teleprompter(QWidget):
    closed = Signal()

    def __init__(self, script: str, look: Look) -> None:
        super().__init__(None)
        self.look = look
        self.pacer = ScriptPacer(script)
        self._last_speech = 0.0
        self._last_tick = time.monotonic()
        self._done = False
        self._shown_line = 0
        self._scroll = 0.0  # px still to glide after moving to a new line

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)

        screen = QGuiApplication.primaryScreen().geometry()
        width = min(760, int(screen.width() * 0.6))
        height = PAD_TOP + VISIBLE_LINES * LINE_HEIGHT + FOOTER_H + 8
        self.setGeometry(screen.x() + (screen.width() - width) // 2, screen.y() + TOP_OFFSET, width, height)
        metrics = QFontMetricsF(self._font())
        self.lines = wrap_lines(script, width - 2 * PAD_X, metrics.horizontalAdvance)

        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._close_timer = QTimer(self, singleShot=True, timeout=self.close)

    # ---- control ------------------------------------------------------------------------
    def start(self) -> None:
        self.show()
        self._hide_from_capture()
        self._last_tick = time.monotonic()
        self._timer.start()

    def mark_speech(self) -> None:
        """Called from the audio thread whenever a frame contains speech."""
        self._last_speech = time.monotonic()

    def toggle_pause(self) -> None:
        self.pacer.paused = not self.pacer.paused
        self.update()

    def apply_look(self, look: Look) -> None:
        self.look = look
        self.update()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self.closed.emit()
        super().closeEvent(event)

    @property
    def speaking(self) -> bool:
        return time.monotonic() - self._last_speech < SPEECH_HANGOVER_S

    def _tick(self) -> None:
        now = time.monotonic()
        self.pacer.advance(min(0.1, now - self._last_tick), self.speaking)
        self._last_tick = now
        line = self._current_line_index()
        if line != self._shown_line:
            self._scroll += (line - self._shown_line) * LINE_HEIGHT
            self._shown_line = line
        self._scroll = self._scroll * SCROLL_EASE if abs(self._scroll) > 0.5 else 0.0
        if self.pacer.finished and not self._done:
            self._done = True
            self._close_timer.start(DONE_HOLD_MS)
        self.update()

    def _hide_from_capture(self) -> None:
        if os.environ.get("HARK_PROMPTER_IN_CAPTURE") == "1":
            return
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except (AttributeError, OSError):
            pass

    # ---- mouse --------------------------------------------------------------------------
    def _close_rect(self) -> QRectF:
        return QRectF(self.width() - 30, self.height() - FOOTER_H - 4, 22, FOOTER_H)

    def mousePressEvent(self, event) -> None:
        if self._close_rect().contains(event.position()):
            self.close()
        else:
            self.toggle_pause()

    def wheelEvent(self, event) -> None:
        line = self._current_line_index()
        words = len(self.lines[line].words) if self.lines else 6
        self.pacer.nudge(-words if event.angleDelta().y() > 0 else words)
        self._done = False
        self._close_timer.stop()
        self.update()

    # ---- painting -----------------------------------------------------------------------
    @staticmethod
    def _font() -> QFont:
        f = QFont("Segoe UI Variable Display", 15)
        f.setWeight(QFont.DemiBold)
        f.setStyleStrategy(QFont.PreferAntialias)
        return f

    def _current_line_index(self) -> int:
        pos = int(self.pacer.position)
        for i, line in enumerate(self.lines):
            if line.words and line.start <= pos < line.end:
                return i
        return max(0, len(self.lines) - 1)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QPainterPath()
        bg.addRoundedRect(rect, 18, 18)
        fill = QColor(self.look.notch)
        fill.setAlphaF(0.93)
        p.fillPath(bg, fill)

        text_area = QRectF(rect.left(), rect.top() + PAD_TOP, rect.width(), VISIBLE_LINES * LINE_HEIGHT)
        p.save()
        p.setClipRect(text_area)
        self._paint_lines(p, text_area)
        p.restore()
        self._paint_footer(p, rect)
        p.end()

    def _paint_lines(self, p: QPainter, area: QRectF) -> None:
        if not self.lines:
            return
        current = self._shown_line
        # The current line holds the middle row; after a line change everything glides up into place.
        y_current = area.top() + LINE_HEIGHT + self._scroll
        p.setFont(self._font())
        metrics = QFontMetricsF(self._font())
        read = QColor(self.look.accent)
        ahead = QColor(self.look.text)
        for offset in range(-2, 3):
            i = current + offset
            if not 0 <= i < len(self.lines) or not self.lines[i].words:
                continue
            y = y_current + offset * LINE_HEIGHT
            alpha = LINE_ALPHA.get(offset, 0.2)
            x = area.left() + PAD_X
            for k, word in enumerate(self.lines[i].words):
                spoken = self.lines[i].start + k < self.pacer.position
                c = QColor(read if spoken else ahead)
                c.setAlphaF(alpha * (0.85 if spoken else 1.0))
                p.setPen(c)
                p.drawText(QRectF(x, y, area.width(), LINE_HEIGHT), Qt.AlignLeft | Qt.AlignVCenter, word)
                x += metrics.horizontalAdvance(word + " ")

    def _paint_footer(self, p: QPainter, rect: QRectF) -> None:
        f = QFont("Segoe UI Variable Text", 9)
        p.setFont(f)
        dim = QColor(self.look.text)
        dim.setAlphaF(0.6)
        p.setPen(dim)
        footer = QRectF(rect.left() + PAD_X, rect.bottom() - FOOTER_H - 4, rect.width() - 2 * PAD_X, FOOTER_H)
        if self._done:
            status = "Done"
        elif self.pacer.paused:
            status = "Paused · click to resume"
        else:
            status = "Listening" if self.speaking else "Waiting for you to speak"
        p.drawText(footer, Qt.AlignLeft | Qt.AlignVCenter, f"Teleprompter · {round(self.pacer.progress * 100)}%  ·  {status}")
        p.drawText(self._close_rect(), Qt.AlignCenter, "✕")
        bar = QRectF(rect.left() + 18, rect.bottom() - 3, (rect.width() - 36), 1.6)
        track = QColor(self.look.accent)
        track.setAlphaF(0.2)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(bar, 0.8, 0.8)
        track.setAlphaF(0.9)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * self.pacer.progress, bar.height()), 0.8, 0.8)
