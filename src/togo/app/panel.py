"""The panel: a drawer under the notch with a Chat tab (type to Togo, see the conversation) and a
History tab (past conversations; pick one to continue it). F9 or a click on the resting notch opens it;
Esc or clicking elsewhere closes it.
"""

from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from togo.app.look import Look

WIDTH, HEIGHT = 520, 420
TOP_OFFSET = 44  # just below the resting notch
BUBBLE_PADDING = 26  # horizontal padding plus a little slack
FONT_PX = 13
EMPTY_CHAT = "Ask anything, or try “What’s on my list?”"
EMPTY_HISTORY = "Nothing here yet."


def message_font() -> QFont:
    font = QFont(["Segoe UI Variable Text", "Segoe UI"])
    font.setPixelSize(FONT_PX)
    return font


def relative_time(ts: float, now: float | None = None) -> str:
    """'now', '5m', '3h', 'yesterday', '4d', or '21 Oct'."""
    now = now or time.time()
    seconds = max(0.0, now - ts)
    if seconds < 90:
        return "now"
    if seconds < 3600:
        return f"{round(seconds / 60)}m"
    if seconds < 86400:
        return f"{round(seconds / 3600)}h"
    if seconds < 2 * 86400:
        return "yesterday"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d"
    return dt.datetime.fromtimestamp(ts).strftime("%d %b").lstrip("0")


class Panel(QWidget):
    submitted = Signal(str)
    new_conversation = Signal()
    conversation_chosen = Signal(int)
    history_requested = Signal()

    def __init__(self, look: Look) -> None:
        super().__init__(None)
        self.look = look
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIDTH, HEIGHT)
        self._opened_at = 0.0

        self.chat_tab = QPushButton("Chat", checkable=True, checked=True)
        self.history_tab = QPushButton("History", checkable=True)
        for tab in (self.chat_tab, self.history_tab):
            tab.setObjectName("tab")
            tab.setCursor(Qt.PointingHandCursor)
        self.chat_tab.clicked.connect(lambda: self.show_tab("chat"))
        self.history_tab.clicked.connect(lambda: self.show_tab("history"))
        new_button = QPushButton("＋ New", objectName="ghost", cursor=Qt.PointingHandCursor,
                                 toolTip="Start a new conversation")
        new_button.clicked.connect(self._start_new)
        close_button = QPushButton("✕", objectName="ghost", cursor=Qt.PointingHandCursor, toolTip="Close (Esc)")
        close_button.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.chat_tab)
        header.addWidget(self.history_tab)
        header.addStretch(1)
        header.addWidget(new_button)
        header.addWidget(close_button)

        # Chat: messages above an input row.
        self._messages = QVBoxLayout()
        self._messages.setSpacing(8)
        self._messages.addStretch(1)
        holder = QWidget(objectName="transparent")
        holder.setLayout(self._messages)
        self._scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        self._scroll.setWidget(holder)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._empty_chat = QLabel(EMPTY_CHAT, objectName="dim", alignment=Qt.AlignCenter, wordWrap=True)
        self.input = QLineEdit(placeholderText="Ask Togo…")
        self.input.returnPressed.connect(self._submit)
        send = QPushButton("↑", objectName="send", cursor=Qt.PointingHandCursor, toolTip="Send (Enter)")
        send.clicked.connect(self._submit)
        input_row = QHBoxLayout()
        input_row.addWidget(self.input, 1)
        input_row.addWidget(send)
        chat = QWidget(objectName="transparent")
        chat_layout = QVBoxLayout(chat)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.addWidget(self._empty_chat)
        chat_layout.addWidget(self._scroll, 1)
        chat_layout.addLayout(input_row)

        # History: a list of past conversations.
        self.history = QListWidget()
        self.history.setCursor(Qt.PointingHandCursor)
        self.history.itemClicked.connect(self._choose)
        self._empty_history = QLabel(EMPTY_HISTORY, objectName="dim", alignment=Qt.AlignCenter)
        history = QWidget(objectName="transparent")
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(self._empty_history)
        history_layout.addWidget(self.history, 1)

        self.pages = QStackedWidget()
        self.pages.addWidget(chat)
        self.pages.addWidget(history)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)
        root.addLayout(header)
        root.addWidget(self.pages, 1)
        self._busy: QLabel | None = None
        self.apply_look(look)
        self._refresh_empty()

    # ---- public ---------------------------------------------------------------------------
    def open(self) -> None:
        screen = QGuiApplication.primaryScreen().geometry()
        self.move(screen.x() + (screen.width() - WIDTH) // 2, screen.y() + TOP_OFFSET)
        self._opened_at = time.monotonic()
        self.show()
        self.raise_()
        self.activateWindow()
        self.show_tab("chat")
        self.input.setFocus()

    def show_tab(self, name: str) -> None:
        history = name == "history"
        self.chat_tab.setChecked(not history)
        self.history_tab.setChecked(history)
        self.pages.setCurrentIndex(1 if history else 0)
        if history:
            self.history_requested.emit()
        else:
            self.input.setFocus()

    def set_messages(self, messages: list[dict]) -> None:
        self.clear_messages()
        for m in messages:
            self.add_message(m["role"], m["content"])

    def clear_messages(self) -> None:
        self.set_busy(False)
        while self._messages.count() > 1:
            item = self._messages.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self._refresh_empty()

    def add_message(self, role: str, text: str) -> None:
        bubble = QLabel(text, wordWrap=True, objectName="user" if role == "user" else "togo")
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Word-wrapped labels shrink to a narrow column; size the bubble to its text, up to ~72% wide.
        metrics = QFontMetricsF(message_font())  # the stylesheet's font, not the label's default
        longest = max((metrics.horizontalAdvance(line) for line in text.splitlines() or [""]), default=0)
        longest = int(longest + 1)
        bubble.setFixedWidth(min(int(WIDTH * 0.72), longest + BUBBLE_PADDING))
        row = QHBoxLayout()
        if role == "user":
            row.addStretch(1)
        row.addWidget(bubble)
        if role != "user":
            row.addStretch(1)
        wrapper = QWidget(objectName="transparent")
        wrapper.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self._messages.addWidget(wrapper)
        self._refresh_empty()
        QTimer.singleShot(40, self._scroll_to_end)

    def set_busy(self, busy: bool) -> None:
        if busy and self._busy is None:
            self._busy = QLabel("…", objectName="togo")
            self._messages.addWidget(self._busy, 0, Qt.AlignLeft)
            QTimer.singleShot(40, self._scroll_to_end)
        elif not busy and self._busy is not None:
            self._messages.removeWidget(self._busy)  # now, so a reply added next lands in its place
            self._busy.deleteLater()
            self._busy = None

    def set_conversations(self, conversations: list[dict], now: float | None = None) -> None:
        self.history.clear()
        for c in conversations:
            title = (c.get("title") or "Untitled").strip().replace("\n", " ")
            if len(title) > 52:
                title = title[:51] + "…"
            item = QListWidgetItem(f"{title}\n{relative_time(c['updated_at'], now)} · {c['messages']} messages")
            item.setData(Qt.UserRole, c["id"])
            self.history.addItem(item)
        self._refresh_empty()

    def apply_look(self, look: Look) -> None:
        self.look = look
        text, accent, notch = look.text, look.accent, look.notch
        self.setStyleSheet(f"""
            QWidget {{ color: {text}; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: {FONT_PX}px; }}
            #transparent, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QPushButton#tab {{ background: rgba(255,255,255,0.06); border: none; border-radius: 13px;
                               padding: 5px 14px; color: {text}; }}
            QPushButton#tab:checked {{ background: rgba(255,255,255,0.16); font-weight: 600; }}
            QPushButton#ghost {{ background: transparent; border: none; padding: 5px 8px; color: {text}; }}
            QPushButton#ghost:hover {{ color: {accent}; }}
            QPushButton#send {{ background: {accent}; color: {notch}; border: none; border-radius: 17px;
                                min-width: 34px; min-height: 34px; font-size: 16px; font-weight: 700; }}
            QLineEdit {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10);
                         border-radius: 17px; padding: 7px 14px; selection-background-color: {accent}; }}
            QLineEdit:focus {{ border: 1px solid {accent}; }}
            QLabel#user {{ background: {accent}; color: {notch}; border-radius: 12px; padding: 7px 11px; }}
            QLabel#togo {{ background: rgba(255,255,255,0.08); border-radius: 12px; padding: 7px 11px; }}
            QLabel#dim {{ color: rgba(238,242,247,0.55); }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ padding: 9px 10px; border-radius: 10px; margin-bottom: 2px; }}
            QListWidget::item:hover {{ background: rgba(255,255,255,0.06); }}
            QListWidget::item:selected {{ background: rgba(255,255,255,0.12); color: {text}; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; }}
            QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 3px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)
        self.update()

    # ---- internals ------------------------------------------------------------------------
    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.add_message("user", text)
        self.set_busy(True)
        self.submitted.emit(text)

    def _start_new(self) -> None:
        self.clear_messages()
        self.show_tab("chat")
        self.new_conversation.emit()

    def _choose(self, item: QListWidgetItem) -> None:
        self.show_tab("chat")
        self.conversation_chosen.emit(int(item.data(Qt.UserRole)))

    def _refresh_empty(self) -> None:
        has_messages = self._messages.count() > 1
        self._empty_chat.setVisible(not has_messages)
        self._scroll.setVisible(has_messages)
        self._empty_history.setVisible(self.history.count() == 0)
        self.history.setVisible(self.history.count() > 0)

    def _scroll_to_end(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event) -> None:
        # Clicking anywhere else closes the panel (but not in the instant it is being opened).
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            if time.monotonic() - self._opened_at > 0.4:
                self.hide()
        super().changeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        fill = QColor(self.look.notch)
        p.fillPath(path, fill)
        edge = QColor(255, 255, 255, 26)
        p.setPen(edge)
        p.drawPath(path)
        p.end()
