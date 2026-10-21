from __future__ import annotations

import json

import pytest

from hark.engine.core.llm import LLMUnavailable
from hark.engine.store.sqlite_store import Store


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HARK_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


class FakeLLM:
    """Returns queued replies in order; raises LLMUnavailable when the queue is empty."""

    def __init__(self, *replies) -> None:
        self.replies = [json.dumps(r) if isinstance(r, dict) else r for r in replies]
        self.calls: list[list[dict]] = []

    def chat(self, messages, **_kwargs) -> str:
        self.calls.append(messages)
        if not self.replies:
            raise LLMUnavailable("no model")
        return self.replies.pop(0)


class NoApps:
    def find(self, _spoken):
        return None
