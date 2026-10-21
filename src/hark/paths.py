r"""Filesystem layout. Everything the app writes lives under %LOCALAPPDATA%\hark."""

from __future__ import annotations

import os
from pathlib import Path

from hark import PRODUCT


def data_dir() -> Path:
    override = os.environ.get("HARK_DATA_DIR")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / PRODUCT
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path


def models_dir() -> Path:
    override = os.environ.get("HARK_MODELS_DIR")
    path = Path(override) if override else data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "hark.db"


def port_file() -> Path:
    return data_dir() / "engine.port"


def token_file() -> Path:
    return data_dir() / "engine.token"
