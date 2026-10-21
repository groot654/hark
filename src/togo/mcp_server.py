"""`togo --mcp`: an MCP server (stdio) so Claude Code, Claude Desktop and other MCP clients can use
Togo's to-do list, notes, habits, reminders and focus timer, and put a short message in the notch.

Calls are forwarded to the running Togo through its allow-listed integrations endpoint, so nothing
here can type, click, open apps or delete, and Togo has to be running.

Set up in Claude Code with:  claude mcp add togo -- "<path to>\\togo.exe" --mcp
"""

from __future__ import annotations

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from togo import __version__
from togo.paths import port_file, token_file
from togo.single_instance import TOKEN_HEADER

NOT_RUNNING = "Togo isn't running. Start it and try again."

server = MCPServer(
    "togo",
    version=__version__,
    instructions=(
        "Togo is the user's voice assistant on this PC. Use these tools to keep their to-do list, notes, "
        "habits, reminders and focus timer, or to tell them something in Togo's notch at the top of the screen "
        "(for example when a long task finishes)."
    ),
)


class TogoError(ToolError):
    """An expected failure: the client gets this message, and no traceback is logged."""


def _post(path: str, payload: dict) -> dict:
    try:
        port = int(port_file().read_text().strip())
        token = token_file().read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        raise TogoError(NOT_RUNNING) from None
    try:
        resp = httpx.post(f"http://127.0.0.1:{port}{path}", json=payload, headers={TOKEN_HEADER: token}, timeout=15)
    except httpx.HTTPError:
        raise TogoError(NOT_RUNNING) from None
    if resp.status_code == 401:
        raise TogoError(NOT_RUNNING)  # a stale token from an earlier run
    if resp.status_code >= 400:
        raise TogoError(f"Togo couldn't do that ({resp.status_code}).")
    return resp.json()


def call(tool: str, **args) -> str:
    """Run one Togo tool and return its answer as text (lists numbered)."""
    result = _post("/v1/integrations/tool", {"name": tool, "args": {k: v for k, v in args.items() if v is not None}})
    text = result.get("text") or ("Done." if result.get("ok") else "That didn't work.")
    items = result.get("items")
    if items:
        text = text.split(":")[0] + ":\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    if not result.get("ok"):
        raise TogoError(text)
    return text


@server.tool(description="Add something the user has to do to their to-do list.")
def add_task(text: str) -> str:
    return call("task.add", title=text)


@server.tool(description="The user's open to-dos, numbered.")
def list_tasks() -> str:
    return call("task.list")


@server.tool(description="Tick off a to-do, found by a few words from it.")
def complete_task(text: str) -> str:
    return call("task.complete", needle=text)


@server.tool(description="Save a note for the user (information to keep, not a task).")
def add_note(text: str) -> str:
    return call("note.add", body=text)


@server.tool(description="The user's notes: the most recent ones, or those containing `query`.")
def search_notes(query: str = "") -> str:
    return call("note.search", query=query) if query.strip() else call("note.list")


@server.tool(description="Mark a habit as done today, e.g. 'reading' or 'workout'. Replies with the streak.")
def log_habit(habit: str) -> str:
    return call("habit.log", name=habit)


@server.tool(description="How many days in a row the user has kept a habit.")
def habit_streak(habit: str) -> str:
    return call("habit.streak", name=habit)


@server.tool(description=(
    "Set a reminder that pops up in Togo's notch. Put the time in the text, e.g. "
    "'in 20 minutes to stretch' or 'at 6pm to call Sam'."))
def add_reminder(text: str) -> str:
    return call("reminder.add", text=text)


@server.tool(description="The user's upcoming reminders.")
def list_reminders() -> str:
    return call("reminder.list")


@server.tool(description="Start a focus timer; the notch shows the countdown.")
def start_focus(minutes: int = 25, label: str | None = None) -> str:
    return call("focus.start", minutes=minutes, label=label)


@server.tool(description="Stop the focus timer early.")
def stop_focus() -> str:
    return call("focus.stop")


@server.tool(description="Time left in the current focus session, if any.")
def focus_status() -> str:
    return call("focus.status")


@server.tool(description="Show a short message in Togo's notch, e.g. 'Build finished' or 'Tests failed'.")
def notify(text: str, title: str = "Togo") -> str:
    _post("/v1/system/notify", {"text": text[:500], "title": title[:80]})
    return "Shown."


def main() -> int:
    server.run("stdio")
    return 0
