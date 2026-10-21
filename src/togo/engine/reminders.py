"""Fires timed reminders and focus-session endings as events for the notch."""

from __future__ import annotations

import logging
import threading
import time

from togo.engine.eventbus import EventBus
from togo.engine.store.sqlite_store import Store

log = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, store: Store, bus: EventBus, interval: float = 5.0) -> None:
        self.store = store
        self.bus = bus
        self.interval = interval
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="reminders", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick(time.time())
            except Exception:
                log.exception("reminder tick failed")

    def tick(self, now: float) -> None:
        for reminder in self.store.due_reminders(now):
            self.store.mark_fired(reminder["id"])
            log.info("reminder due: %s", reminder["id"])
            self.bus.publish("reminder.due", id=reminder["id"], text=reminder["text"])
        focus = self.store.active_focus()
        if focus and now >= focus["started_at"] + focus["planned_minutes"] * 60:
            self.store.end_focus()
            self.bus.publish("focus.ended", id=focus["id"])
            label = f" on {focus['label']}" if focus["label"] else ""
            self.bus.publish("notify", title="Focus session done",
                             text=f"{focus['planned_minutes']} minutes{label}. Take a short break.")
