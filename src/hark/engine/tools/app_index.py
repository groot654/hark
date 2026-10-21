"""Index of installed apps from the Start menu (classic and Store apps alike)."""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Spoken names that don't match the Start-menu entry.
ALIASES = {
    "chrome": "google chrome",
    "edge": "microsoft edge",
    "word": "word",
    "excel": "excel",
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "code": "visual studio code",
    "file explorer": "file explorer",
    "explorer": "file explorer",
    "files": "file explorer",
    "settings": "settings",
    "calculator": "calculator",
    "terminal": "terminal",
    "command prompt": "command prompt",
    "notepad": "notepad",
    "paint": "paint",
    "spotify": "spotify",
    "teams": "microsoft teams",
    "outlook": "outlook",
    "whatsapp": "whatsapp",
}

# Always available even if the Start menu scan fails.
BUILTINS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
}


@dataclass(frozen=True)
class AppEntry:
    name: str
    app_id: str

    def launch(self) -> None:
        if self.app_id.endswith(".exe") or self.app_id.endswith(":"):
            os.startfile(self.app_id)
        else:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{self.app_id}"])


def _normalise(name: str) -> str:
    name = name.lower().replace("&", "and")
    name = re.sub(r"\(.*?\)|[^a-z0-9+# ]", " ", name)
    return " ".join(name.split())


class AppIndex:
    def __init__(self) -> None:
        self._apps: dict[str, AppEntry] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def refresh(self) -> None:
        apps = {name: AppEntry(name, target) for name, target in BUILTINS.items()}
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            for row in json.loads(out or "[]"):
                key = _normalise(row["Name"])
                if key and "uninstall" not in key:
                    apps.setdefault(key, AppEntry(row["Name"], row["AppID"]))
        except (OSError, ValueError, subprocess.SubprocessError):
            log.exception("start-menu scan failed")
        with self._lock:
            self._apps = apps
            self._loaded_at = time.monotonic()
        log.info("app index: %d installed apps", len(apps))

    def refresh_async(self) -> None:
        threading.Thread(target=self.refresh, name="app-index", daemon=True).start()

    def find(self, spoken: str) -> AppEntry | None:
        if time.monotonic() - self._loaded_at > 600:
            self.refresh()
        query = _normalise(spoken)
        query = ALIASES.get(query, query)
        with self._lock:
            apps = dict(self._apps)
        if query in apps:
            return apps[query]
        starts = [k for k in apps if k.startswith(query + " ") or k.endswith(" " + query)]
        if starts:
            return apps[min(starts, key=len)]
        contains = [k for k in apps if query in k.split()]
        if contains:
            return apps[min(contains, key=len)]
        close = difflib.get_close_matches(query, list(apps), n=1, cutoff=0.82)
        return apps[close[0]] if close else None
