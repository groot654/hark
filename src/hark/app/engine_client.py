"""HTTP + SSE client for the local engine."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

import httpx

from hark.engine.security import HEADER
from hark.paths import port_file, token_file

log = logging.getLogger(__name__)


class EngineClient:
    def __init__(self, port: int | None = None, token: str | None = None) -> None:
        self.port = port or int(port_file().read_text().strip())
        self.token = token or token_file().read_text(encoding="utf-8").strip()
        self.base = f"http://127.0.0.1:{self.port}"
        self._http = httpx.Client(base_url=self.base, headers={HEADER: self.token}, timeout=60)

    def health(self) -> dict:
        return self._http.get("/v1/system/health", timeout=3).json()

    def listen(self, wav: bytes, mode: str, target: dict | None) -> dict:
        resp = self._http.post(
            "/v1/listen",
            files={"audio": ("speech.wav", wav, "audio/wav")},
            data={"mode": mode, "target": json.dumps(target or {})},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def chat(self, text: str, target: dict | None = None, selection: str | None = None,
             conversation_id: int | None = None) -> dict:
        resp = self._http.post("/v1/chat", json={"text": text, "target": target or {}, "selection": selection,
                                                 "conversation_id": conversation_id})
        resp.raise_for_status()
        return resp.json()

    def confirm(self, confirm_id: str, approved: bool) -> dict:
        return self._http.post("/v1/confirm", json={"id": confirm_id, "approved": approved}).json()

    def get(self, path: str, **params) -> dict:
        resp = self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict) -> dict:
        resp = self._http.post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    def subscribe(self, on_event: Callable[[dict], None]) -> threading.Thread:
        """Follow /v1/events on a daemon thread, reconnecting on failure."""

        def run() -> None:
            import time

            while True:
                try:
                    with httpx.stream(
                        "GET", f"{self.base}/v1/events", headers={HEADER: self.token}, timeout=None
                    ) as resp:
                        for line in resp.iter_lines():
                            if line.startswith("data:"):
                                on_event(json.loads(line[5:]))
                except Exception as exc:
                    log.debug("event stream dropped: %s", exc)
                    time.sleep(1.0)

        thread = threading.Thread(target=run, name="engine-events", daemon=True)
        thread.start()
        return thread
