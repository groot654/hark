"""Draws Togo's icon (the notch pill with its two eyes) into packaging/togo.ico at several sizes."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

SIZES = (16, 24, 32, 48, 64, 128, 256)
NOTCH, EYES = QColor("#0a0d12"), QColor("#5fd7ff")


def draw(size: int) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 32
    p.setPen(Qt.NoPen)
    p.setBrush(NOTCH)
    p.drawRoundedRect(QRectF(1 * s, 7 * s, 30 * s, 18 * s), 9 * s, 9 * s)
    p.setBrush(EYES)
    for x in (10, 18):
        p.drawRoundedRect(QRectF(x * s, 11 * s, 4.5 * s, 10 * s), 2.25 * s, 2.25 * s)
    p.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    img.save(buffer, "PNG")
    return bytes(data)


def write_ico(path: Path) -> None:
    """An .ico whose entries are PNGs (supported since Windows Vista)."""
    images = [draw(size) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, png in zip(SIZES, images):
        dim = 0 if size == 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    path.write_bytes(header + entries + b"".join(images))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = Path(__file__).with_name("togo.ico")
    write_ico(out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
