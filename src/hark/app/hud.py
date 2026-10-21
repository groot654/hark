"""The notch: a small always-on-top pill at the top of the screen.

It rests as a tiny bar with Hark's eyes, widens while listening (live mic
meter), shows a thinking shimmer, and expands into a card for replies.
"""

from __future__ import annotations

import ctypes
import logging
import math
import random
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from hark.app.look import Look

log = logging.getLogger("hark.hud")

WDA_EXCLUDEFROMCAPTURE = 0x11


class HudState(Enum):
    REST = "rest"
    LISTENING = "listening"
    DICTATING = "dictating"
    THINKING = "thinking"
    REPLY = "reply"
    ERROR = "error"


@dataclass
class Card:
    title: str = ""
    body: str = ""
    items: list[str] = field(default_factory=list)
    kind: str = "reply"  # reply | list | music | error | agent


SIZES = {
    HudState.REST: QSize(104, 30),
    HudState.LISTENING: QSize(340, 40),
    HudState.DICTATING: QSize(340, 40),
    HudState.THINKING: QSize(220, 40),
    HudState.ERROR: QSize(380, 64),
}
CARD_WIDTH = 460
CARD_MAX_HEIGHT = 400
PADDING = 16


class Hud(QWidget):
    clicked = Signal()

    def __init__(self, look: Look) -> None:
        super().__init__(None)
        self.look = look
        self.state = HudState.REST
        self.card = Card()
        self.level = 0.0
        self._levels = [0.0] * 24
        self._phase = 0.0
        self._blink = 0.0
        self._size = QSizeF_from(SIZES[HudState.REST])
        self._target = QSizeF_from(SIZES[HudState.REST])
        self._hidden_for_fullscreen = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

        self._tick = QTimer(self, interval=33, timeout=self._on_tick)
        self._tick.start()
        self._blink_timer = QTimer(self, singleShot=True, timeout=self._start_blink)
        self._blink_timer.start(3000)
        self._dismiss = QTimer(self, singleShot=True, timeout=self.rest)

        self._place(self._size)
        self.show()

    # ---- public API -------------------------------------------------------
    def set_state(self, state: HudState) -> None:
        if state != self.state:
            log.info("hud: %s -> %s", self.state.value, state.value)
        self.state = state
        self._dismiss.stop()
        if state in SIZES:
            self._animate_to(SIZES[state])
        if self._hidden_for_fullscreen and state != HudState.REST:
            self.show()

    def set_level(self, level: float) -> None:
        self.level = level
        self._levels = self._levels[1:] + [level]

    def show_card(self, card: Card, dismiss_ms: int | None = None) -> None:
        self.card = card
        self.state = HudState.REPLY if card.kind != "error" else HudState.ERROR
        self._animate_to(self._card_size(card))
        if self._hidden_for_fullscreen:
            self.show()
        if dismiss_ms is None:
            words = len((card.body + " ".join(card.items)).split())
            dismiss_ms = max(4200, min(15_000, 2000 + words * 300))
        self._dismiss.start(dismiss_ms)

    def rest(self) -> None:
        self.set_state(HudState.REST)
        if self._hidden_for_fullscreen:
            self.hide()

    def set_fullscreen_hidden(self, hidden: bool) -> None:
        self._hidden_for_fullscreen = hidden
        if hidden and self.state == HudState.REST:
            self.hide()
        elif not hidden:
            self.show()

    def apply_look(self, look: Look) -> None:
        self.look = look
        self.update()

    def exclude_from_capture(self, exclude: bool) -> None:
        ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE if exclude else 0)

    # ---- geometry ---------------------------------------------------------
    def _card_size(self, card: Card) -> QSize:
        fm = QFontMetrics(self._body_font())
        inner = CARD_WIDTH - 2 * PADDING - 34
        text = card.body
        lines = 0
        if text:
            lines += fm.boundingRect(0, 0, inner, 10_000, Qt.TextWordWrap, text).height() / fm.lineSpacing()
        lines += len(card.items[:8])
        height = 44 + (22 if card.title else 0) + int(lines * fm.lineSpacing()) + PADDING
        return QSize(CARD_WIDTH, max(64, min(CARD_MAX_HEIGHT, height)))

    def _animate_to(self, size: QSize) -> None:
        self._anim.stop()
        self._anim.setStartValue(QRectF(0, 0, self._size.width(), self._size.height()))
        self._anim.setEndValue(QRectF(0, 0, size.width(), size.height()))
        self._target = QSizeF_from(size)
        self._anim.start()

    def _on_anim(self, rect: QRectF) -> None:
        self._size = rect.size()
        self._place(self._size)

    def _place(self, size) -> None:
        screen = QGuiApplication.primaryScreen().geometry()
        w, h = int(size.width()), int(size.height())
        self.setGeometry(screen.x() + (screen.width() - w) // 2, screen.y() + 6, w, h)
        self.update()

    # ---- animation --------------------------------------------------------
    def _start_blink(self) -> None:
        self._blink = 1.0
        self._blink_timer.start(random.randint(2500, 6000))

    def _on_tick(self) -> None:
        self._phase += 0.033
        if self._blink > 0:
            self._blink = max(0.0, self._blink - 0.18)
        self.update()

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit()

    # ---- painting ---------------------------------------------------------
    def _body_font(self) -> QFont:
        f = QFont("Segoe UI Variable Text", 10)
        f.setStyleStrategy(QFont.PreferAntialias)
        return f

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(rect.height() / 2, 18)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QColor(self.look.notch))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(path)

        eye_box = QRectF(rect.left() + 12, rect.top() + 6, 26, min(rect.height(), 44) - 12)
        if self.state == HudState.REST:
            eye_box = QRectF(rect.center().x() - 13, rect.top() + 6, 26, rect.height() - 12)
        self._paint_eyes(p, eye_box)

        if self.state in (HudState.LISTENING, HudState.DICTATING):
            self._paint_meter(p, QRectF(eye_box.right() + 12, rect.top() + 8, rect.right() - eye_box.right() - 26, 28))
        elif self.state == HudState.THINKING:
            self._paint_thinking(p, QRectF(eye_box.right() + 12, rect.top() + 8, rect.right() - eye_box.right() - 26, 28))
        elif self.state in (HudState.REPLY, HudState.ERROR):
            self._paint_card(p, rect, eye_box)
        p.end()

    def _paint_eyes(self, p: QPainter, box: QRectF) -> None:
        color = QColor(self.look.eyes if self.state != HudState.ERROR else "#ff6b6b")
        eye_w = box.width() * 0.32
        open_h = box.height() * 0.78
        # Squint while thinking, wide while listening.
        if self.state == HudState.THINKING:
            open_h *= 0.55
        elif self.state in (HudState.LISTENING, HudState.DICTATING):
            open_h *= 1.0 + self.level * 0.25
        h = max(2.0, open_h * (1.0 - math.sin(self._blink * math.pi) * 0.9))
        look_x = math.sin(self._phase * 0.7) * 1.5 if self.state == HudState.THINKING else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for cx in (box.left() + box.width() * 0.25, box.left() + box.width() * 0.75):
            p.drawRoundedRect(QRectF(cx - eye_w / 2 + look_x, box.center().y() - h / 2, eye_w, h), eye_w / 2, eye_w / 2)

    def _paint_meter(self, p: QPainter, box: QRectF) -> None:
        color = QColor(self.look.accent if self.state == HudState.LISTENING else self.look.dictation)
        n = len(self._levels)
        gap = box.width() / n
        p.setPen(Qt.NoPen)
        for i, lv in enumerate(self._levels):
            h = max(3.0, (0.15 + lv * 0.85) * box.height() * (0.6 + 0.4 * math.sin(i * 0.9 + self._phase * 6) ** 2))
            c = QColor(color)
            c.setAlphaF(0.45 + 0.55 * (i / n))
            p.setBrush(c)
            p.drawRoundedRect(QRectF(box.left() + i * gap, box.center().y() - h / 2, gap * 0.55, h), 1.5, 1.5)

    def _paint_thinking(self, p: QPainter, box: QRectF) -> None:
        p.setPen(Qt.NoPen)
        for i in range(3):
            a = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self._phase * 7 - i * 0.9))
            c = QColor(self.look.accent)
            c.setAlphaF(a)
            p.setBrush(c)
            p.drawEllipse(QPointF(box.left() + 10 + i * 16, box.center().y()), 4, 4)

    def _paint_card(self, p: QPainter, rect: QRectF, eye_box: QRectF) -> None:
        left = eye_box.right() + 12
        width = rect.right() - left - PADDING
        y = rect.top() + 12
        p.setPen(QColor(self.look.text))
        if self.card.title:
            f = self._body_font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(left, y, width, 20), Qt.AlignLeft | Qt.AlignVCenter, self.card.title)
            y += 22
        p.setFont(self._body_font())
        fm = QFontMetrics(self._body_font())
        if self.card.body:
            r = fm.boundingRect(0, 0, int(width), 10_000, Qt.TextWordWrap, self.card.body)
            p.drawText(QRectF(left, y, width, rect.bottom() - y - 8), Qt.TextWordWrap, self.card.body)
            y += r.height() + 4
        sub = QColor(self.look.text)
        sub.setAlphaF(0.85)
        p.setPen(sub)
        for item in self.card.items[:8]:
            if y > rect.bottom() - fm.lineSpacing():
                break
            p.drawText(QRectF(left, y, width, fm.lineSpacing()), Qt.AlignLeft, fm.elidedText("•  " + item, Qt.ElideRight, int(width)))
            y += fm.lineSpacing()


def QSizeF_from(size: QSize):
    return QRectF(0, 0, size.width(), size.height()).size()
