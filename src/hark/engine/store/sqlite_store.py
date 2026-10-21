"""SQLite persistence for conversations, memory and the productivity features."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY, started_at REAL NOT NULL, summary TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL, done_at REAL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, body TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_logs (
    habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE, day TEXT NOT NULL,
    PRIMARY KEY (habit_id, day)
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY, label TEXT, started_at REAL NOT NULL, planned_minutes INTEGER NOT NULL, ended_at REAL
);
CREATE TABLE IF NOT EXISTS timed_reminders (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, due_at REAL NOT NULL, fired INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS routines (
    name TEXT PRIMARY KEY, steps TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON timed_reminders(fired, due_at);
"""

USER_TABLES = ("conversations", "messages", "memories", "tasks", "notes", "habits", "habit_logs",
               "focus_sessions", "timed_reminders", "routines")


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        """Run a write. Returns the new row id for an INSERT, else the number of rows changed."""
        with self._lock:
            cur = self._db.execute(sql, args)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

    # ---- settings ------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        self._x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    # ---- conversations -------------------------------------------------------
    def new_conversation(self) -> int:
        return self._x("INSERT INTO conversations(started_at) VALUES(?)", (time.time(),))

    def add_message(self, conversation_id: int, role: str, content: str) -> None:
        self._x("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)",
                (conversation_id, role, content, time.time()))

    def recent_messages(self, conversation_id: int, limit: int = 8) -> list[dict]:
        rows = self._q("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                       (conversation_id, limit))
        return [dict(r) for r in reversed(rows)]

    def prune_history(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        self._x("DELETE FROM conversations WHERE started_at < ?", (cutoff,))

    # ---- memory --------------------------------------------------------------
    def remember(self, key: str, value: str) -> None:
        now = time.time()
        self._x("INSERT INTO memories(key,value,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now, now))

    def forget(self, needle: str) -> int:
        like = f"%{needle}%"
        return self._x("DELETE FROM memories WHERE key LIKE ? OR value LIKE ?", (like, like))

    def list_memories(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT key, value FROM memories ORDER BY updated_at DESC")]

    # ---- tasks ---------------------------------------------------------------
    def add_task(self, title: str) -> int:
        return self._x("INSERT INTO tasks(title,created_at) VALUES(?,?)", (title, time.time()))

    def open_tasks(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, title FROM tasks WHERE done=0 ORDER BY id")]

    def complete_task(self, needle: str) -> str | None:
        rows = self._q("SELECT id, title FROM tasks WHERE done=0 AND title LIKE ? ORDER BY length(title) LIMIT 1",
                       (f"%{needle}%",))
        if not rows:
            return None
        self._x("UPDATE tasks SET done=1, done_at=? WHERE id=?", (time.time(), rows[0]["id"]))
        return rows[0]["title"]

    def clear_completed_tasks(self) -> int:
        return self._x("DELETE FROM tasks WHERE done=1")

    # ---- notes ---------------------------------------------------------------
    def add_note(self, body: str) -> int:
        return self._x("INSERT INTO notes(body,created_at) VALUES(?,?)", (body, time.time()))

    def recent_notes(self, limit: int = 8) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, body, created_at FROM notes ORDER BY id DESC LIMIT ?", (limit,))]

    def search_notes(self, query: str) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, body FROM notes WHERE body LIKE ? ORDER BY id DESC LIMIT 8",
                                         (f"%{query}%",))]

    # ---- habits --------------------------------------------------------------
    def log_habit(self, name: str, day: str) -> int:
        self._x("INSERT OR IGNORE INTO habits(name,created_at) VALUES(?,?)", (name, time.time()))
        habit_id = self._q("SELECT id FROM habits WHERE name=?", (name,))[0]["id"]
        self._x("INSERT OR IGNORE INTO habit_logs(habit_id,day) VALUES(?,?)", (habit_id, day))
        return habit_id

    def habit_days(self, name: str) -> list[str]:
        rows = self._q("SELECT day FROM habit_logs JOIN habits ON habits.id=habit_logs.habit_id "
                       "WHERE habits.name=? ORDER BY day DESC", (name,))
        return [r["day"] for r in rows]

    def habits(self) -> list[str]:
        return [r["name"] for r in self._q("SELECT name FROM habits ORDER BY name")]

    # ---- focus ---------------------------------------------------------------
    def start_focus(self, minutes: int, label: str | None) -> int:
        self._x("UPDATE focus_sessions SET ended_at=? WHERE ended_at IS NULL", (time.time(),))
        return self._x("INSERT INTO focus_sessions(label,started_at,planned_minutes) VALUES(?,?,?)",
                       (label, time.time(), minutes))

    def active_focus(self) -> dict | None:
        rows = self._q("SELECT * FROM focus_sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def end_focus(self) -> dict | None:
        active = self.active_focus()
        if active:
            self._x("UPDATE focus_sessions SET ended_at=? WHERE id=?", (time.time(), active["id"]))
        return active

    # ---- reminders -----------------------------------------------------------
    def add_reminder(self, text: str, due_at: float) -> int:
        return self._x("INSERT INTO timed_reminders(text,due_at,created_at) VALUES(?,?,?)",
                       (text, due_at, time.time()))

    def due_reminders(self, now: float) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, text, due_at FROM timed_reminders WHERE fired=0 AND due_at<=?",
                                         (now,))]

    def upcoming_reminders(self, limit: int = 8) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, text, due_at FROM timed_reminders WHERE fired=0 "
                                         "ORDER BY due_at LIMIT ?", (limit,))]

    def mark_fired(self, reminder_id: int) -> None:
        self._x("UPDATE timed_reminders SET fired=1 WHERE id=?", (reminder_id,))

    # ---- routines ------------------------------------------------------------
    def save_routine(self, name: str, steps: list[str]) -> None:
        self._x("INSERT INTO routines(name,steps,created_at) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET steps=excluded.steps", (name, json.dumps(steps), time.time()))

    def get_routine(self, name: str) -> list[str] | None:
        rows = self._q("SELECT steps FROM routines WHERE name=?", (name,))
        return json.loads(rows[0]["steps"]) if rows else None

    def routines(self) -> list[str]:
        return [r["name"] for r in self._q("SELECT name FROM routines ORDER BY name")]

    # ---- privacy -------------------------------------------------------------
    def export_all(self) -> dict:
        return {t: [dict(r) for r in self._q(f"SELECT * FROM {t}")] for t in USER_TABLES}

    def clear_all(self) -> None:
        with self._lock:
            for table in reversed(USER_TABLES):
                self._db.execute(f"DELETE FROM {table}")
            self._db.execute("VACUUM")
