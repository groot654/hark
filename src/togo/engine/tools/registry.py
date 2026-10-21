"""Executes tool calls. Every tool has a permission tier:

- normal: runs immediately (opening apps, volume, notes...)
- sensitive: asks first (closing apps, typing into another window from the LLM)
- destructive: asks first and warns it can't be undone (shutdown, clearing data)
"""

from __future__ import annotations

import ctypes
import datetime as dt
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Callable

import psutil

from togo.engine.core.intents import Intent
from togo.engine.store.sqlite_store import Store
from togo.engine.tools import system, ui_automation
from togo.engine.tools.app_index import AppIndex
from togo.engine.tools.timeparse import describe, parse_when

log = logging.getLogger(__name__)

NORMAL, SENSITIVE, DESTRUCTIVE = "normal", "sensitive", "destructive"


@dataclass
class ToolResult:
    status: str = "ok"  # ok | error | needs_input
    say: str = ""
    card: dict | None = None
    client_actions: list[dict] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    permission: str
    run: Callable[[dict], ToolResult]
    confirm: Callable[[dict], str] | None = None


KEY_NAMES = {
    "control": "ctrl", "ctrl": "ctrl", "alt": "alt", "shift": "shift", "windows": "windows", "win": "windows",
    "enter": "enter", "return": "enter", "escape": "esc", "esc": "esc", "space": "space", "spacebar": "space",
    "tab": "tab", "backspace": "backspace", "delete": "delete", "up": "up", "down": "down", "left": "left",
    "right": "right", "home": "home", "end": "end", "page up": "page up", "page down": "page down",
    "f5": "f5", "f11": "f11", "plus": "+", "minus": "-",
}


def spoken_keys_to_combo(spoken: str) -> str:
    spoken = spoken.lower().replace("+", " ").replace("-", " ").replace(" and ", " ")
    for phrase in ("page up", "page down"):
        spoken = spoken.replace(phrase, phrase.replace(" ", "_"))
    keys = [KEY_NAMES.get(k.replace("_", " "), k.replace("_", " ")) for k in spoken.split()]
    return "+".join(keys)


def _list_card(title: str, items: list[str], empty: str) -> ToolResult:
    if not items:
        return ToolResult(say=empty)
    return ToolResult(say=f"{title}: " + "; ".join(items[:5]), card={"title": title, "items": items, "kind": "list"})


class ToolRegistry:
    def __init__(self, store: Store, apps: AppIndex) -> None:
        self.store = store
        self.apps = apps
        self.tools: dict[str, Tool] = {}
        self._register_all()

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def permission(self, intent: Intent) -> str:
        tool = self.tools.get(intent.tool)
        return tool.permission if tool else NORMAL

    def confirm_text(self, intent: Intent) -> str:
        tool = self.tools[intent.tool]
        text = tool.confirm(intent.args) if tool.confirm else f"{tool.description}?"
        if tool.permission == DESTRUCTIVE:
            text = "This can't be undone. " + text
        return text

    def run(self, intent: Intent) -> ToolResult:
        tool = self.tools.get(intent.tool)
        if tool is None:
            return ToolResult(status="error", say=f"I don't know how to do {intent.tool} yet.")
        try:
            result = tool.run(intent.args)
            log.info("tool %s -> %s", intent.tool, result.status)
            return result
        except Exception as exc:
            log.exception("tool %s failed", intent.tool)
            return ToolResult(status="error", say=f"That didn't work: {exc}")

    def describe_for_llm(self) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in self.tools.values() if not t.name.startswith("persona."))

    # ---- registration -----------------------------------------------------------
    def _add(self, name: str, description: str, run, permission: str = NORMAL, confirm=None) -> None:
        self.tools[name] = Tool(name, description, permission, run, confirm)

    def _register_all(self) -> None:
        s = self.store
        add = self._add

        # apps & web
        add("app.open", "Open or switch to an installed app or a known website. args: {name}", self._open_app)
        add("app.close", "Close an app. args: {name}", self._close_app, SENSITIVE,
            confirm=lambda a: f"Close {a['name']}?")
        add("web.open", "Open a URL in the browser. args: {url}", lambda a: self._ok(system.open_url(a["url"]), f"Opening {a['url']}."))
        add("web.search", "Search the web. args: {query, engine: google|youtube|amazon|wikipedia|github|maps}",
            lambda a: self._ok(system.search(a["query"], a.get("engine", "google")),
                               f"Searching {a.get('engine', 'google').title()} for {a['query']}."))

        # input
        add("input.keys", "Press a key or shortcut in the window in front. args: {keys, times}", self._keys)
        add("input.type", "Type text into the window in front. args: {text}",
            lambda a: ToolResult(say="", client_actions=[{"type": "insert_text", "text": a["text"]}]))
        add("ui.click", "Click a button, link, tab, menu or field in the window in front. args: {name}", self._ui_click)
        add("ui.point", "Show where a button or field is in the window in front. args: {name}", self._ui_point)
        add("window.minimise", "Minimise the window in front", lambda a: self._ok(system.press_keys("windows+down"), ""))
        add("window.maximise", "Maximise the window in front", lambda a: self._ok(system.press_keys("windows+up"), ""))

        # volume & media
        add("volume.set", "Set the volume to an exact level. args: {percent}",
            lambda a: ToolResult(say=f"Volume {system.set_volume(int(a['percent']))}%."))
        add("volume.change", "Make it louder or quieter (too loud, can't hear). args: {delta}: 10 louder, -10 quieter",
            lambda a: ToolResult(say=f"Volume {system.change_volume(int(a['delta']))}%."))
        add("volume.mute", "Mute or unmute. args: {muted}",
            lambda a: self._ok(system.set_mute(bool(a["muted"])), "Muted." if a["muted"] else "Unmuted."))
        add("volume.get", "Say the current volume", lambda a: ToolResult(say=f"Volume is {system.get_volume()}%."))
        add("media.key", "Media control. args: {action: play_pause|next|previous}",
            lambda a: self._ok(system.media(a["action"]), ""))
        add("media.now_playing", "Say what's playing", self._now_playing)

        # time & system
        add("system.time", "Say the time", lambda a: ToolResult(say=f"It's {dt.datetime.now().strftime('%I:%M %p').lstrip('0')}."))
        add("system.date", "Say the date", lambda a: ToolResult(say=dt.datetime.now().strftime("It's %A, %B %d.").replace(" 0", " ")))
        add("system.stats", "Battery, CPU and memory", self._stats)
        add("system.lock", "Lock the PC", lambda a: self._ok(system.lock_screen(), ""))
        add("system.shutdown", "Shut down the PC", lambda a: self._ok(subprocess.Popen(["shutdown", "/s", "/t", "5"]), "Shutting down."),
            DESTRUCTIVE, confirm=lambda a: "Shut down the PC now?")
        add("system.restart", "Restart the PC", lambda a: self._ok(subprocess.Popen(["shutdown", "/r", "/t", "5"]), "Restarting."),
            DESTRUCTIVE, confirm=lambda a: "Restart the PC now?")

        # memory
        add("memory.remember", "Remember a fact about the user. args: {fact}", self._remember)
        add("memory.list", "List what you remember", lambda a: _list_card(
            "What I remember", [m["value"] for m in s.list_memories()], "I haven't remembered anything yet."))
        add("memory.forget", "Forget memories matching some words. args: {needle}",
            lambda a: ToolResult(say="Forgotten." if s.forget(a["needle"]) else "I didn't have anything about that."),
            SENSITIVE, confirm=lambda a: f"Forget what I know about {a['needle']}?")

        # tasks & notes
        add("task.add", "Add something the user has to do to their to-do list. args: {title}", lambda a: self._ok(s.add_task(a["title"]), f"Added “{a['title']}” to your list."))
        add("task.list", "Show the to-do list", lambda a: _list_card(
            "To-do", [t["title"] for t in s.open_tasks()], "Your to-do list is empty."))
        add("task.complete", "Mark a to-do done. args: {needle}", self._complete_task)
        add("task.clear_completed", "Remove completed to-dos",
            lambda a: ToolResult(say=f"Cleared {s.clear_completed_tasks()} finished tasks."),
            DESTRUCTIVE, confirm=lambda a: "Delete all completed tasks?")
        add("note.add", "Save a note: information to keep, not a task. args: {body}", lambda a: self._ok(s.add_note(a["body"]), "Noted."))
        add("note.list", "Show recent notes", lambda a: _list_card("Notes", [n["body"] for n in s.recent_notes()], "No notes yet."))
        add("note.search", "Search notes. args: {query}", lambda a: _list_card(
            f"Notes about {a['query']}", [n["body"] for n in s.search_notes(a["query"])], f"No notes about {a['query']}."))

        # reminders, habits, focus
        add("reminder.add", "Set a reminder. args: {text} including the time words, e.g. 'in 2 hours to call mum'", self._reminder)
        add("reminder.list", "List upcoming reminders", lambda a: _list_card(
            "Reminders", [f"{describe(dt.datetime.fromtimestamp(r['due_at']))}: {r['text']}" for r in s.upcoming_reminders()],
            "No reminders set."))
        add("habit.log", "Log a habit for today. args: {name}", self._habit_log)
        add("habit.streak", "Say a habit streak. args: {name}", self._habit_streak)
        add("focus.start", "Start a focus timer. args: {minutes, label}", self._focus_start)
        add("focus.stop", "Stop the focus timer", self._focus_stop)

        # look & persona & teleprompter
        add("look.set", "Change Togo's colours. args: {look: arc|ember|mint|violet|mono}",
            lambda a: ToolResult(say="New look.", client_actions=[{"type": "look", "look": a["look"]}]))
        add("persona.thanks", "", lambda a: ToolResult(say="Any time.", client_actions=[{"type": "mood", "mood": "love"}]))
        add("teleprompter.start", "Start the teleprompter with the copied script",
            lambda a: ToolResult(client_actions=[{"type": "teleprompter", "action": "start"}]))
        add("teleprompter.stop", "Stop the teleprompter",
            lambda a: ToolResult(client_actions=[{"type": "teleprompter", "action": "stop"}]))

    @staticmethod
    def _ok(_value, say: str) -> ToolResult:
        return ToolResult(say=say)

    # ---- tool bodies --------------------------------------------------------------------
    def _open_app(self, args: dict) -> ToolResult:
        name = args["name"].strip()
        site = system.SITES.get(name.lower())
        app = self.apps.find(name)
        if app is not None and (site is None or name.lower() in ("spotify", "outlook", "whatsapp")):
            app.launch()
            return ToolResult(say=f"Opening {app.name}.")
        if site:
            system.open_url(site)
            return ToolResult(say=f"Opening {name.title()}.")
        return ToolResult(status="error", say=f"I couldn't find an app called {name}.")

    def _close_app(self, args: dict) -> ToolResult:
        app = self.apps.find(args["name"])
        # Close its windows the way the ✕ button does: works for Store apps (whose process names differ, e.g.
        # CalculatorApp.exe) and lets apps offer to save. Ending the process is the fallback.
        if system.close_windows([args["name"], app.name if app else ""]):
            return ToolResult(say=f"Closed {args['name']}.")
        wanted = args["name"].lower().replace(" ", "")
        closed = 0
        for proc in psutil.process_iter(["name", "exe"]):
            pname = (proc.info["name"] or "").lower().removesuffix(".exe")
            if pname == wanted or (app and pname and pname in app.name.lower().replace(" ", "")):
                try:
                    proc.terminate()
                    closed += 1
                except psutil.Error:
                    pass
        return ToolResult(say=f"Closed {args['name']}." if closed else f"{args['name']} isn't running.")

    def _keys(self, args: dict) -> ToolResult:
        combo = spoken_keys_to_combo(args["keys"])
        for _ in range(max(1, min(20, int(args.get("times", 1))))):
            system.press_keys(combo)
        return ToolResult(say="")

    def _find_control(self, args: dict) -> ui_automation.Pick | ToolResult:
        hwnd = int(args.get("hwnd") or ui_automation.foreground_window())
        if not hwnd or ui_automation.is_own_window(hwnd):
            return ToolResult(status="error", say="Click into the app you want first, then ask again.")
        try:
            controls = ui_automation.list_controls(hwnd)
        except TimeoutError:
            return ToolResult(status="error", say="That window took too long to read.")
        except Exception:
            log.exception("reading window controls failed")
            return ToolResult(status="error", say="I couldn't read the controls in that window.")
        choice = ui_automation.pick(args["name"], controls)
        if choice.control is None:
            return ToolResult(status="error", say=f"I can't see “{args['name']}” in this window.")
        return choice

    def _ui_click(self, args: dict) -> ToolResult:
        choice = self._find_control(args)
        if isinstance(choice, ToolResult):
            return choice
        control = choice.control
        if not choice.clear and not args.get("confirmed"):
            again = Intent("ui.click", {**args, "confirmed": True}, f"click {control.name}")
            return ToolResult(say=f"Click “{control.name}”?", data={"ask": again})
        how = ui_automation.press(control)
        log.info("clicked a %s via %s (match %.2f)", control.kind, how, choice.score)
        return ToolResult(client_actions=[point_action(control, 900)])

    def _ui_point(self, args: dict) -> ToolResult:
        choice = self._find_control(args)
        if isinstance(choice, ToolResult):
            return choice
        return ToolResult(say=f"There's “{choice.control.name}”.", client_actions=[point_action(choice.control, 2500)])

    def _now_playing(self, _args: dict) -> ToolResult:
        from togo.engine.tools.now_playing import current

        info = current()
        if not info:
            return ToolResult(say="Nothing's playing.")
        return ToolResult(say=f"{info['title']} by {info['artist']}." if info.get("artist") else f"{info['title']}.",
                          card={"title": "Now playing", "body": f"{info['title']}\n{info.get('artist', '')}", "kind": "music"})

    def _stats(self, _args: dict) -> ToolResult:
        st = system.stats()
        parts = [f"CPU {st['cpu_percent']:.0f}%", f"memory {st['memory_percent']:.0f}%"]
        if st["battery_percent"] is not None:
            parts.insert(0, f"battery {st['battery_percent']}%" + (" and charging" if st["plugged_in"] else ""))
        say = ", ".join(parts)
        return ToolResult(say=say[0].upper() + say[1:] + ".", data=st)

    def _remember(self, args: dict) -> ToolResult:
        fact = args["fact"].strip().rstrip(".")
        fact = fact[0].upper() + fact[1:] if fact else fact
        key = " ".join(fact.lower().split()[:6])
        self.store.remember(key, fact)
        return ToolResult(say="Got it, I'll remember that.")

    def _complete_task(self, args: dict) -> ToolResult:
        title = self.store.complete_task(args["needle"])
        return ToolResult(say=f"Done: {title}." if title else "I couldn't find that task.")

    def _reminder(self, args: dict) -> ToolResult:
        text = args["text"]
        when = parse_when(text)
        if when is None:
            return ToolResult(status="needs_input", say="When should I remind you?")
        due, phrase = when
        what = text.replace(phrase, " ")
        what = " ".join(what.split()).strip(" ,.")
        what = re_strip_lead(what) or "your reminder"
        self.store.add_reminder(what, due.timestamp())
        return ToolResult(say=f"I'll remind you {describe(due)} to {what}.")

    def _habit_log(self, args: dict) -> ToolResult:
        name = args["name"].lower().strip()
        self.store.log_habit(name, dt.date.today().isoformat())
        return self._habit_streak({"name": name}, prefix="Logged. ")

    def _habit_streak(self, args: dict, prefix: str = "") -> ToolResult:
        days = set(self.store.habit_days(args["name"].lower().strip()))
        streak, day = 0, dt.date.today()
        if day.isoformat() not in days:
            day -= dt.timedelta(days=1)
        while day.isoformat() in days:
            streak += 1
            day -= dt.timedelta(days=1)
        return ToolResult(say=f"{prefix}{args['name'].title()}: {streak}-day streak.")

    def _focus_start(self, args: dict) -> ToolResult:
        minutes = int(args.get("minutes") or 25)
        self.store.start_focus(minutes, args.get("label"))
        return ToolResult(say=f"Focus for {minutes} minutes. I'll tell you when it's done.",
                          client_actions=[focus_action(self.store.active_focus())])

    def _focus_stop(self, _args: dict) -> ToolResult:
        ended = self.store.end_focus()
        if not ended:
            return ToolResult(say="There's no focus session running.")
        return ToolResult(say="Focus session stopped.", client_actions=[focus_action(None)])


def point_action(control: ui_automation.Control, duration_ms: int) -> dict:
    """Client action: draw a ring around a control (rect in physical screen pixels)."""
    return {"type": "point", "rect": list(control.rect), "duration_ms": duration_ms}


def focus_action(session: dict | None) -> dict:
    """Client action that shows the notch's focus countdown, or clears it when `session` is None."""
    if not session:
        return {"type": "focus", "ends_at": None}
    return {"type": "focus", "ends_at": session["started_at"] + session["planned_minutes"] * 60,
            "minutes": session["planned_minutes"], "label": session["label"]}


def re_strip_lead(text: str) -> str:
    import re

    return re.sub(r"^(?:me\s+)?(?:to|that|about)\s+", "", text, flags=re.I).strip()


def user_is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False
