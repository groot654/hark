"""Shared logging: one rotating file for the engine and client, plus stderr."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from hark.paths import logs_dir

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir() / "hark.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(file_handler)
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
        root.addHandler(stream)
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
