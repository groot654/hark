import asyncio

import pytest

from togo import mcp_server


@pytest.fixture
def engine_calls(monkeypatch):
    calls = []

    def fake_post(path, payload):
        calls.append((path, payload))
        if payload.get("name") == "task.list":
            return {"ok": True, "text": "To-do: a; b", "items": ["a", "b"]}
        if payload.get("name") == "task.complete":
            return {"ok": False, "text": "I couldn't find that task.", "items": None}
        return {"ok": True, "text": "Done.", "items": None}

    monkeypatch.setattr(mcp_server, "_post", fake_post)
    return calls


def test_lists_are_numbered(engine_calls):
    assert mcp_server.list_tasks() == "To-do:\n1. a\n2. b"


def test_arguments_map_to_togo_tools(engine_calls):
    mcp_server.add_task("buy milk")
    mcp_server.search_notes("")
    mcp_server.search_notes("wifi")
    mcp_server.start_focus(15)
    assert [p for _, p in engine_calls] == [
        {"name": "task.add", "args": {"title": "buy milk"}},
        {"name": "note.list", "args": {}},
        {"name": "note.search", "args": {"query": "wifi"}},
        {"name": "focus.start", "args": {"minutes": 15}},
    ]


def test_failures_become_tool_errors(engine_calls):
    with pytest.raises(mcp_server.TogoError, match="couldn't find"):
        mcp_server.complete_task("nothing like this")


def test_notify_uses_the_notch_endpoint(engine_calls):
    assert mcp_server.notify("Build finished") == "Shown."
    assert engine_calls == [("/v1/system/notify", {"text": "Build finished", "title": "Togo"})]


def test_not_running(tmp_path, monkeypatch):
    monkeypatch.setenv("TOGO_DATA_DIR", str(tmp_path / "empty"))
    with pytest.raises(mcp_server.TogoError, match="isn't running"):
        mcp_server.list_tasks()


def test_tool_list():
    tools = asyncio.run(mcp_server.server.list_tools())
    assert {t.name for t in tools} == {
        "add_task", "list_tasks", "complete_task", "add_note", "search_notes", "log_habit", "habit_streak",
        "add_reminder", "list_reminders", "start_focus", "stop_focus", "focus_status", "notify"}
