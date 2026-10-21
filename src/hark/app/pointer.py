"""A brief ring drawn around a control on screen: what Hark just clicked, or where something is."""

from __future__ import annotations

import time

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

MARGIN = 8  # px of room around the control for the ring


class Pointer(QWidget):
    def __init__(self, rect_px: list[int], colour: str, duration_ms: int = 1200) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.colour = QColor(colour)
        self.duration = duration_ms / 1000
        self.started = time.monotonic()
        self.setGeometry(to_logical(rect_px).adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN))
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._timer.start()
        self.show()

    def _tick(self) -> None:
        if time.monotonic() - self.started >= self.duration:
            self.close()
        else:
            self.update()

    def paintEvent(self, _event) -> None:
        t = min(1.0, (time.monotonic() - self.started) / self.duration)
        fade = 1.0 if t < 0.7 else (1.0 - t) / 0.3
        grow = 1.0 - min(1.0, t / 0.18)  # the ring settles in from slightly larger
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ring = QRectF(self.rect()).adjusted(3 - 6 * grow, 3 - 6 * grow, -3 + 6 * grow, -3 + 6 * grow)
        glow = QColor(self.colour)
        glow.setAlphaF(0.25 * fade)
        p.setPen(QPen(glow, 7))
        p.drawRoundedRect(ring, 9, 9)
        line = QColor(self.colour)
        line.setAlphaF(0.95 * fade)
        p.setPen(QPen(line, 2.5))
        p.drawRoundedRect(ring, 9, 9)
        p.end()


def to_logical(rect_px: list[int]) -> QRect:
    """UI Automation reports physical pixels; Qt positions windows in logical ones."""
    left, top, right, bottom = rect_px
    screen = QGuiApplication.screenAt(QRect(left, top, 1, 1).center()) or QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio()
    return QRect(round(left / ratio), round(top / ratio), round((right - left) / ratio), round((bottom - top) / ratio))
