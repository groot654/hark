"""System Check: is everything Togo needs working on this PC, and what to do if not."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from togo.app.look import Look

COLOURS = {"ok": "#1E9E62", "warn": "#B7791F", "error": "#D64545"}
SUMMARY = {"ok": "Everything's working.", "warn": "Working, with something to look at.",
           "error": "Something needs attention."}


def summary(items: list[dict]) -> str:
    statuses = {i["status"] for i in items}
    return SUMMARY["error" if "error" in statuses else "warn" if "warn" in statuses else "ok"]


class SystemCheck(QDialog):
    def __init__(self, look: Look, refresh: Callable[[], list[dict]]) -> None:
        super().__init__(None)
        self.refresh = refresh
        self.setWindowTitle("Togo · System Check")
        self.setMinimumWidth(500)
        self.setStyleSheet(f"""
            QDialog {{ background: {look.notch}; }}
            QLabel, QPushButton {{ color: {look.text}; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }}
            QLabel#title {{ font-size: 17px; font-weight: 600; }}
            QLabel#detail {{ color: rgba(238,242,247,0.75); }}
            QLabel#fix {{ color: rgba(238,242,247,0.55); font-style: italic; }}
            QPushButton {{ background: rgba(255,255,255,0.08); color: {look.text}; border: none; border-radius: 14px;
                           padding: 6px 16px; font-size: 13px; }}
            QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
        """)
        self.title = QLabel("", objectName="title")
        self.rows = QVBoxLayout()
        self.rows.setSpacing(12)
        again = QPushButton("Check again", cursor=Qt.PointingHandCursor)
        again.clicked.connect(self.run)
        close = QPushButton("Close", cursor=Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(again)
        buttons.addWidget(close)
        note = QLabel("Togo never records audio during this check.", objectName="fix")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(self.title)
        layout.addLayout(self.rows)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.run()

    def run(self) -> None:
        self.show_items(self.refresh())

    def show_items(self, items: list[dict]) -> None:
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.title.setText(summary(items))
        for item in items:
            self.rows.addWidget(_row(item))
        self.adjustSize()  # wrapped fix lines need the extra height


def _row(item: dict) -> QWidget:
    dot = QLabel("●")
    dot.setStyleSheet(f"color: {COLOURS.get(item['status'], COLOURS['warn'])}; font-size: 15px;")
    dot.setAlignment(Qt.AlignTop)
    name = QLabel(f"<b>{item['name']}</b>")
    detail = QLabel(item["detail"], objectName="detail", wordWrap=True)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(name)
    text.addWidget(detail)
    if item.get("fix"):
        text.addWidget(QLabel(item["fix"], objectName="fix", wordWrap=True))
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(dot)
    row.addLayout(text, 1)
    widget = QWidget()
    widget.setLayout(row)
    return widget
