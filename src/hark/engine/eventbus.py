"""In-process pub/sub that fans engine events out to SSE subscribers (the HUD)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, kind: str, **data: Any) -> None:
        """Thread-safe: callable from worker threads and the event loop."""
        event = {"type": kind, "ts": time.time(), **data}
        if self._loop is None:
            return
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            self._loop.call_soon_threadsafe(_offer, q, event)


def _offer(q: asyncio.Queue, event: dict) -> None:
    if q.full():
        q.get_nowait()
    q.put_nowait(event)


def sse_format(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
