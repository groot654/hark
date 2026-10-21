"""The notch: a small always-on-top pill at the top of the screen.

It rests as a tiny bar with Hark's eyes, widens while listening (live mic
meter), shows a thinking shimmer, and expands into a card for replies.
"""

from __future__ import annotations

import ctypes
import logging
import math
import random
import time
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
REST_FOCUS_SIZE = QSize(150, 30)  # resting pill while a focus countdown runs
CARD_WIDTH = 460
CARD_MAX_HEIGHT = 400
PADDING = 16
TICK_S = 0.033

# Reactions the engine can ask for, and how long each lasts (seconds).
MOODS = {"love": 2.4, "happy": 1.5, "puzzled": 2.2}
LOVE_COLOUR = "#ff6fa8"
HOP_S = 0.35
HEART_COUNT = 5
SPI_GETCLIENTAREAANIMATION = 0x1042


def format_remaining(seconds: float) -> str:
    """Countdown text: 24:59, or 1:05:00 for an hour or more."""
    total = max(0, math.ceil(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def animations_enabled() -> bool:
    """Respect Windows' "Animation effects" setting: when off, reactions skip the hop and float."""
    try:
        value = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0)
        return bool(value.value)
    except (AttributeError, OSError):
        return True


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
        self.mood: str | None = None
        self._mood_age = 0.0
        self._hearts: list[tuple[float, float]] = []  # (side -1..1, start delay)
        self._animate = animations_enabled()
        self._focus_ends: float | None = None  # epoch seconds
        self._focus_total = 0.0

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
        if state == HudState.REST:
            self._animate_to(self._rest_size())
        elif state in SIZES:
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

    def set_focus(self, ends_at: float | None, total_seconds: float | None = None) -> None:
        """Show a focus countdown in the resting pill until `ends_at` (epoch seconds); None clears it."""
        if ends_at is not None and ends_at <= time.time():
            ends_at = None
        self._focus_ends = ends_at
        if ends_at is not None:
            self._focus_total = total_seconds or (ends_at - time.time())
        if self.state == HudState.REST:
            self._animate_to(self._rest_size())

    @property
    def focus_remaining(self) -> float | None:
        return None if self._focus_ends is None else max(0.0, self._focus_ends - time.time())

    def _rest_size(self) -> QSize:
        return REST_FOCUS_SIZE if self._focus_ends is not None else SIZES[HudState.REST]

    def react(self, mood: str) -> None:
        """Play a short expression (see MOODS); unknown moods are ignored."""
        if mood not in MOODS:
            return
        self.mood = mood
        self._mood_age = 0.0
        self._blink = 1.0
        self._hearts = [(random.uniform(-1, 1), i * 0.22) for i in range(HEART_COUNT)] if mood == "love" else []
        if self._hidden_for_fullscreen:
            self.show()

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
        self._phase += TICK_S
        if self._blink > 0:
            self._blink = max(0.0, self._blink - 0.18)
        if self.mood:
            self._mood_age += TICK_S
            if self._mood_age >= MOODS[self.mood]:
                self.mood = None
                self._hearts = []
        if self._focus_ends is not None and time.time() >= self._focus_ends:
            self.set_focus(None)
        self.update()

    def _hop(self) -> float:
        """Vertical eye offset in px: a small jump at the start of a reaction."""
        if not self.mood or not self._animate or self._mood_age >= HOP_S:
            return 0.0
        return -3.0 * math.sin(self._mood_age / HOP_S * math.pi)

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
        focusing = self.state == HudState.REST and self._focus_ends is not None
        if self.state == HudState.REST and not focusing:
            eye_box = QRectF(rect.center().x() - 13, rect.top() + 6, 26, rect.height() - 12)
        elif focusing:
            eye_box = QRectF(rect.left() + 16, rect.top() + 6, 26, rect.height() - 12)
            self._paint_focus(p, rect, eye_box)
        self._paint_eyes(p, eye_box.translated(0, self._hop()))
        if self._hearts and self._animate:
            p.save()
            p.setClipPath(path)
            self._paint_hearts(p, rect, eye_box)
            p.restore()

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
        centres = (box.left() + box.width() * 0.25, box.left() + box.width() * 0.75)
        blink = 1.0 - math.sin(self._blink * math.pi) * 0.9
        cy = box.center().y()

        if self.mood == "love":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(LOVE_COLOUR))
            size = eye_w * 1.45 * (1.0 + 0.08 * math.sin(self._mood_age * 9))  # gentle pulse
            for cx in centres:
                p.drawPath(heart_path(QPointF(cx, cy), size))
            return
        if self.mood == "happy":
            # Squashed upward arcs: ^ ^
            p.setPen(QPen(color, eye_w * 0.42, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            arc_w, arc_h = eye_w * 1.05, open_h * 0.55
            for cx in centres:
                p.drawArc(QRectF(cx - arc_w / 2, cy - arc_h * 0.4, arc_w, arc_h * 1.2), 15 * 16, 150 * 16)
            return

        # Squint while thinking, wide while listening.
        if self.state == HudState.THINKING:
            open_h *= 0.55
        elif self.state in (HudState.LISTENING, HudState.DICTATING):
            open_h *= 1.0 + self.level * 0.25
        look_x = math.sin(self._phase * 0.7) * 1.5 if self.state == HudState.THINKING else 0.0
        heights = (open_h, open_h)
        lift = (0.0, 0.0)
        if self.mood == "puzzled":
            # One eye narrowed and raised, both glancing to the side.
            heights = (open_h, open_h * 0.5)
            lift = (0.0, -open_h * 0.18)
            look_x = 1.8
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for cx, eye_h, dy in zip(centres, heights, lift):
            h = max(2.0, eye_h * blink)
            p.drawRoundedRect(QRectF(cx - eye_w / 2 + look_x, cy - h / 2 + dy, eye_w, h), eye_w / 2, eye_w / 2)

    def _paint_focus(self, p: QPainter, rect: QRectF, eye_box: QRectF) -> None:
        """Countdown text to the right of the eyes, and a thin progress line along the bottom."""
        remaining = self.focus_remaining or 0.0
        f = QFont("Segoe UI Variable Text", 10)
        f.setBold(True)
        f.setStyleStrategy(QFont.PreferAntialias)
        p.setFont(f)
        p.setPen(QColor(self.look.text))
        text_box = QRectF(eye_box.right() + 8, rect.top(), rect.right() - eye_box.right() - 22, rect.height())
        p.drawText(text_box, Qt.AlignRight | Qt.AlignVCenter, format_remaining(remaining))

        done = 1.0 - remaining / self._focus_total if self._focus_total > 0 else 0.0
        inset = rect.height() / 2
        track = QRectF(rect.left() + inset, rect.bottom() - 3, rect.width() - 2 * inset, 1.6)
        c = QColor(self.look.accent)
        c.setAlphaF(0.22)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(track, 0.8, 0.8)
        c.setAlphaF(0.9)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * min(1.0, max(0.0, done)), track.height()), 0.8, 0.8)

    def _paint_hearts(self, p: QPainter, rect: QRectF, eye_box: QRectF) -> None:
        """Small hearts float away from the eyes and fade: out towards the ends of the resting pill,
        or up beside the eyes when a card is open (so they stay clear of the text)."""
        p.setPen(Qt.NoPen)
        travel = max(24.0, rect.width() / 2 - eye_box.width() / 2 - 10)
        for side, delay in self._hearts:
            t = (self._mood_age - delay) / (MOODS["love"] - delay)
            if not 0.0 < t < 1.0:
                continue
            wobble = math.sin(t * 9 + side * 3) * 1.5
            if self.state == HudState.REST:
                direction = -1.0 if side < 0 else 1.0
                x = eye_box.center().x() + direction * (eye_box.width() / 2 + 4 + t * travel * (0.6 + 0.4 * abs(side)))
                y = rect.bottom() - 6 - t * (rect.height() - 12) + wobble
            else:
                x = eye_box.center().x() + side * eye_box.width() * 0.45 + wobble
                y = eye_box.bottom() + 22 - t * 30
            c = QColor(LOVE_COLOUR)
            c.setAlphaF(max(0.0, 1.0 - t) * 0.9)
            p.setBrush(c)
            p.drawPath(heart_path(QPointF(x, y), 7.0 * (0.8 + 0.3 * abs(side))))

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


def heart_path(centre: QPointF, size: float) -> QPainterPath:
    """A heart about `size` px wide, centred on `centre`."""
    s = size / 2
    x, y = centre.x(), centre.y() + s * 0.1
    path = QPainterPath(QPointF(x, y + s * 0.9))
    path.cubicTo(x - s * 1.3, y + s * 0.1, x - s * 0.9, y - s * 1.05, x, y - s * 0.4)
    path.cubicTo(x + s * 0.9, y - s * 1.05, x + s * 1.3, y + s * 0.1, x, y + s * 0.9)
    return path


def QSizeF_from(size: QSize):
    return QRectF(0, 0, size.width(), size.height()).size()
