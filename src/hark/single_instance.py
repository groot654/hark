"""One Hark per data folder: a Windows named mutex, and a nudge to the copy that's already running.

Windows releases the mutex when its process exits, even after a crash, so a stale lock can't
keep Hark from starting.
"""

from __future__ import annotations

import hashlib
import logging
import sys

import httpx

from hark.paths import data_dir, port_file, token_file

log = logging.getLogger(__name__)

TOKEN_HEADER = "X-Hark-Token"  # same as hark.engine.security.HEADER, without importing the engine


def mutex_name() -> str:
    # Keyed on the data folder, so a test copy with its own HARK_DATA_DIR doesn't collide with the real one.
    key = hashlib.sha1(str(data_dir()).lower().encode()).hexdigest()[:12]
    return f"Local\\Hark.{key}"


def acquire():
    """Take the lock. Returns a handle to keep for the life of the process, or None if another Hark has it."""
    if sys.platform != "win32":
        return True
    import win32api
    import win32event
    import winerror

    handle = win32event.CreateMutex(None, False, mutex_name())
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        handle.Close()
        return None
    return handle


def notify_running(text: str = "Hark is already running.") -> bool:
    """Ask the running Hark to show `text` in its notch. False if it can't be reached."""
    try:
        port = int(port_file().read_text().strip())
        token = token_file().read_text(encoding="utf-8").strip()
        resp = httpx.post(f"http://127.0.0.1:{port}/v1/system/notify", json={"title": "Hark", "text": text},
                          headers={TOKEN_HEADER: token}, timeout=3)
        return resp.status_code == 200
    except (OSError, ValueError, httpx.HTTPError):
        log.warning("couldn't reach the running Hark")
        return False
