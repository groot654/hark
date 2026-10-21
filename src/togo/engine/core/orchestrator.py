"""Turns one utterance into actions and a reply.

Order of precedence:
  1. answer to a pending confirmation ("yes" / "no")
  2. built-in flows that call other commands (routines, agent mode, briefing)
  3. writing requests ("write an email to..."), or rewriting the selected text
  4. deterministic intents, possibly a compound chain ("open X and then Y")
  5. the local language model: pick a tool, or just answer
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from togo.engine.core import prompts
from togo.engine.core.dictation import CHAT_APPS
from togo.engine.core.intents import Intent, match, normalise
from togo.engine.core.llm import LLMClient, LLMUnavailable
from togo.engine.core.recall import recall
from togo.engine.core.transcript_filter import is_noise
from togo.engine.eventbus import EventBus
from togo.engine.store.sqlite_store import Store
from togo.engine.tools.app_index import AppIndex
from togo.engine.tools.registry import NORMAL, ToolRegistry, ToolResult

log = logging.getLogger(__name__)

YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok(?:ay)?|do it|go ahead|confirm|please do|affirmative|correct)\b", re.I)
NO = re.compile(r"^(?:no|nope|nah|cancel|stop|don't|do not|never ?mind|forget it|abort)\b", re.I)
WRITE = re.compile(
    r"^(?:write|draft|compose|type up)\s+(?:me\s+)?(?:an?|the|some)?\s*(.+)$|^(?:reply|respond)\s+(?:saying|with|that)\s+(.+)$",
    re.I,
)
REWRITE = re.compile(
    r"\b(?:make (?:this|it)|rewrite|reword|rephrase|shorten|tighten|fix (?:the )?grammar|translate|summari[sz]e|"
    r"more (?:formal|casual|friendly|polite|concise)|less (?:formal|wordy))\b",
    re.I,
)
AGENT_MAX_STEPS = 5
CONVERSATION_IDLE_S = 600
PENDING_TTL = 120
# Typing and key presses act on whatever window is in front, so when the model (not the user's own
# words) chose them, ask first.
MODEL_CONFIRM = frozenset({"input.type", "input.keys"})
# Commands that change something earn a happy squint in the notch.
CELEBRATE = frozenset({"task.add", "task.complete", "note.add", "reminder.add", "habit.log", "memory.remember",
                       "routine.save", "focus.start"})
# A tool the model picks only runs if the request mentions what that tool is about.
TOOL_CUES = {name: re.compile(rf"\b(?:{words})", re.I) for name, words in {
    "web.search": r"search|look(?:ing)? (?:up|for)|find|google|browse|online|the web|youtube",
    "system.time": r"time|o'?clock|clock|hour",
    "system.date": r"date|day|today|month|year",
    "system.stats": r"battery|charg|cpu|processor|memory|ram|system|computer|pc",
    "system.lock": r"lock",
    "volume.get": r"volume|loud",
    "media.now_playing": r"playing|song|music|track|listening",
    "memory.list": r"remember|memor|know about",
    "routine.list": r"routine",
}.items()}
PLACEHOLDER = re.compile(r"\s*\[[^\]\n]{2,40}\]")
SUBJECT_LINE = re.compile(r"^\s*subject:.*\n+", re.I)


@dataclass
class Pending:
    steps: list[Intent]
    created: float = field(default_factory=time.time)


class Orchestrator:
    def __init__(self, store: Store, llm: LLMClient, apps: AppIndex, bus: EventBus) -> None:
        self.store = store
        self.llm = llm
        self.bus = bus
        self.tools = ToolRegistry(store, apps)
        self._pending: dict[str, Pending] = {}
        self._target: dict = {}
        self._conversation: int | None = None
        self._last_turn = 0.0

    # ---- entry points ------------------------------------------------------------------
    def handle(self, text: str, target: dict | None = None, selection: str | None = None) -> dict:
        run_id = uuid.uuid4().hex
        self.bus.publish("run.started", run_id=run_id, text=text)
        self.bus.publish("state.changed", run_id=run_id, state="thinking")
        try:
            if is_noise(text):
                return self._finish(run_id, ToolResult(), text)
            conversation = self.conversation_id()  # before the reply, so the chat model sees earlier turns only
            result = self._dispatch(text, target or {}, selection)
            self._record(conversation, text, result)
            return self._finish(run_id, result, text)
        except Exception as exc:
            log.exception("run failed")
            self.bus.publish("error.raised", run_id=run_id, code=type(exc).__name__, message=str(exc))
            return self._finish(run_id, ToolResult(status="error", say="Sorry, something went wrong."), text)

    def confirm(self, confirm_id: str, approved: bool) -> dict:
        pending = self._pending.pop(confirm_id, None)
        if pending is None or time.time() - pending.created > PENDING_TTL:
            return self._response(ToolResult(say="That request expired."))
        if not approved:
            return self._response(ToolResult(say="Cancelled."))
        return self._response(self._run_steps(pending.steps, confirmed=True))

    def summary_card(self) -> dict:
        tasks = [t["title"] for t in self.store.open_tasks()][:5]
        reminders = [r["text"] for r in self.store.upcoming_reminders(3)]
        items = [f"☐ {t}" for t in tasks] + [f"⏰ {r}" for r in reminders]
        focus = self.store.active_focus()
        if focus:
            left = max(0, round((focus["started_at"] + focus["planned_minutes"] * 60 - time.time()) / 60))
            items.insert(0, f"Focus: {left} min left")
        return {"title": "Today", "items": items or ["Nothing on your list."], "kind": "list"}

    # ---- pipeline ------------------------------------------------------------------------
    def _dispatch(self, text: str, target: dict, selection: str | None) -> ToolResult:
        phrase = normalise(text)
        self._target = target

        if self._pending and (YES.match(phrase) or NO.match(phrase)):
            confirm_id = max(self._pending, key=lambda k: self._pending[k].created)
            return ToolResult(**_strip(self.confirm(confirm_id, bool(YES.match(phrase)))))

        if selection and REWRITE.search(phrase):
            return self._rewrite(selection, phrase)

        if m := WRITE.match(phrase):
            return self._write(m.group(1) or f"reply saying {m.group(2)}", target)

        steps = match(text)
        if steps:
            return self._run_steps(steps)
        if answer := recall(phrase, self.store.list_memories()):
            return ToolResult(say=answer)
        return self._ask_llm(text, target)

    def _run_steps(self, steps: list[Intent], confirmed: bool = False, ask: frozenset = frozenset()) -> ToolResult:
        if not confirmed:
            risky = [s for s in steps if self.tools.permission(s) != NORMAL or s.tool in ask]
            if risky:
                confirm_id = uuid.uuid4().hex
                self._pending[confirm_id] = Pending(steps)
                if self.tools.permission(risky[0]) != NORMAL:
                    question = self.tools.confirm_text(risky[0])
                else:
                    question = "I'll " + ", then ".join(s.phrase for s in steps) + ". Go ahead?"
                self.bus.publish("state.changed", state="confirming")
                return ToolResult(say=question, data={"confirm_id": confirm_id},
                                  card={"title": "Confirm", "body": question + " Say yes or no.", "kind": "reply"})

        combined = ToolResult()
        says: list[str] = []
        for i, step in enumerate(steps):
            self.bus.publish("plan.step.started", index=i, tool=step.tool, args=step.args)
            result = self._run_one(step)
            self.bus.publish("tool.result", tool=step.tool, status=result.status, message=result.say)
            follow_up = result.data.pop("ask", None)
            if follow_up is not None:
                # The tool wants a yes before acting (e.g. an unclear click): park it and the steps after it.
                confirm_id = uuid.uuid4().hex
                self._pending[confirm_id] = Pending([follow_up, *steps[i + 1:]])
                self.bus.publish("state.changed", state="confirming")
                combined.say = " ".join([*says, result.say])
                combined.data["confirm_id"] = confirm_id
                combined.card = {"title": "Confirm", "body": result.say + " Say yes or no.", "kind": "reply"}
                return combined
            if result.say:
                says.append(result.say)
            combined.client_actions += result.client_actions
            combined.card = result.card or combined.card
            combined.data.update(result.data)
            if result.status != "ok":
                combined.status = result.status
                break
            if len(steps) > 1:
                time.sleep(0.6)  # let an app open before the next step acts on it
        combined.say = " ".join(says)
        if combined.status == "ok" and not _has_mood(combined) and any(s.tool in CELEBRATE for s in steps):
            combined.client_actions.append(mood("happy"))
        return combined

    def _run_one(self, step: Intent) -> ToolResult:
        if step.tool.startswith("ui.") and "hwnd" not in step.args and self._target.get("hwnd"):
            step.args["hwnd"] = self._target["hwnd"]  # the window that was in front when the user spoke
        if step.tool == "routine.save":
            return self._save_routine(step.args["name"], step.args["steps"])
        if step.tool == "routine.run":
            return self._run_routine(step.args["name"])
        if step.tool == "routine.list":
            names = self.store.routines()
            return ToolResult(say="Your routines: " + ", ".join(names) + "." if names else "You have no routines yet.")
        if step.tool == "agent.run":
            return self._agent(step.args["goal"])
        if step.tool == "briefing.daily":
            return self._briefing()
        return self.tools.run(step)

    # ---- routines, agent, briefing -------------------------------------------------------
    def _save_routine(self, name: str, spoken_steps: str) -> ToolResult:
        steps = match(spoken_steps)
        if not steps:
            return ToolResult(status="error", say="I couldn't turn those steps into commands.")
        self.store.save_routine(name.lower().strip(), [s.phrase for s in steps])
        return ToolResult(say=f"Saved routine “{name}” with {len(steps)} step{'s' * (len(steps) > 1)}.")

    def _run_routine(self, name: str) -> ToolResult:
        phrases = self.store.get_routine(name.lower().strip())
        if phrases is None:
            return ToolResult(status="error", say=f"I don't have a routine called {name}.")
        steps = [s for p in phrases for s in match(p)]
        return self._run_steps(steps)

    def _agent(self, goal: str) -> ToolResult:
        try:
            raw = self.llm.chat(
                [{"role": "system", "content": prompts.PLANNER.format(max_steps=AGENT_MAX_STEPS)},
                 {"role": "user", "content": goal}],
                temperature=0.1, max_tokens=300, json_mode=True,
            )
            commands = [str(c) for c in json.loads(raw).get("steps", [])][:AGENT_MAX_STEPS]
        except (LLMUnavailable, ValueError, AttributeError):
            return ToolResult(status="error", say="I need the AI model for that, and it isn't ready yet.")
        steps, unknown = [], []
        for command in commands:
            found = match(command)
            (steps.extend(found) if found else unknown.append(command))
        self.bus.publish("agent.step", items=[s.phrase for s in steps])
        if not steps:
            return ToolResult(status="error", say="I couldn't work out how to do that safely.")
        result = self._run_steps(steps, ask=MODEL_CONFIRM)
        if unknown:
            result.say += f" I skipped {len(unknown)} step{'s' * (len(unknown) > 1)} I couldn't do."
        return result

    def _briefing(self) -> ToolResult:
        now = dt.datetime.now()
        hour = now.hour
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        tasks = self.store.open_tasks()
        reminders = [r for r in self.store.upcoming_reminders(10)
                     if dt.datetime.fromtimestamp(r["due_at"]).date() == now.date()]
        parts = [f"{greeting}. It's {now.strftime('%A, %B %d').replace(' 0', ' ')}."]
        parts.append(f"You have {len(tasks)} thing{'s' * (len(tasks) != 1)} on your list." if tasks else "Your list is clear.")
        if reminders:
            parts.append(f"{len(reminders)} reminder{'s' * (len(reminders) != 1)} today.")
        items = [t["title"] for t in tasks[:5]] + [f"⏰ {r['text']}" for r in reminders[:3]]
        return ToolResult(say=" ".join(parts), card={"title": greeting, "body": " ".join(parts[1:]), "items": items})

    # ---- writing --------------------------------------------------------------------------
    def _write(self, request: str, target: dict) -> ToolResult:
        app = (target.get("app") or "").lower()
        style = "Use a casual, friendly tone." if app in CHAT_APPS else \
            "Use a clear, professional tone." if app in ("outlook", "olk", "thunderbird") else ""
        try:
            text = self.llm.chat(
                [{"role": "system", "content": prompts.WRITER.format(style=style)},
                 {"role": "user", "content": f"Write {request}"}],
                temperature=0.4, max_tokens=500,
            )
        except LLMUnavailable:
            return ToolResult(status="error", say="Writing needs the AI model, which isn't ready yet.")
        text = tidy_written(text, request, casual=app in CHAT_APPS)
        return ToolResult(say="", client_actions=[{"type": "insert_text", "text": text}])

    def _rewrite(self, selection: str, instruction: str) -> ToolResult:
        try:
            text = self.llm.chat(
                [{"role": "system", "content": prompts.REWRITER},
                 {"role": "user", "content": f"Instruction: {instruction}\n\nText:\n{selection}"}],
                temperature=0.3, max_tokens=max(200, len(selection) // 2),
            )
        except LLMUnavailable:
            return ToolResult(status="error", say="Rewriting needs the AI model, which isn't ready yet.")
        return ToolResult(client_actions=[{"type": "insert_text", "text": text}])

    # ---- LLM fallback ---------------------------------------------------------------------
    def _ask_llm(self, text: str, target: dict) -> ToolResult:
        try:
            raw = self.llm.chat(
                [{"role": "system", "content": prompts.ROUTER.format(tools=self.tools.describe_for_llm())},
                 {"role": "user", "content": text}],
                temperature=0.1, max_tokens=250, json_mode=True, timeout=20,
            )
            decision = json.loads(raw)
        except LLMUnavailable:
            return ToolResult(say="I didn't catch a command there, and my AI model isn't running yet.",
                              client_actions=[mood("puzzled")])
        except ValueError:
            decision = {}
        tool = decision.get("tool")
        if tool in TOOL_CUES and not TOOL_CUES[tool].search(text):
            tool = None  # the small model sometimes picks an unrelated tool; answer in conversation instead
        if tool and self.tools.get(tool) and not tool.startswith(("persona.", "system.shutdown", "system.restart")):
            return self._run_steps([Intent(tool, decision.get("args") or {}, normalise(text))], ask=MODEL_CONFIRM)
        return self._chat(text)

    def _chat(self, text: str) -> ToolResult:
        history = self.store.recent_messages(self.conversation_id(), limit=8)
        memories = self.store.list_memories()[:20]
        memory_text = prompts.MEMORIES.format(facts="\n".join(f"- {m['value']}" for m in memories)) if memories else ""
        now = dt.datetime.now()
        system = prompts.PERSONA.format(today=now.strftime("%A %d %B %Y"), time=now.strftime("%H:%M"), memories=memory_text)
        try:
            answer = self.llm.chat([{"role": "system", "content": system}, *history, {"role": "user", "content": text}],
                                   temperature=0.5, max_tokens=220)
        except LLMUnavailable:
            return ToolResult(say="My AI model isn't running yet, so I can only do commands for now.",
                              client_actions=[mood("puzzled")])
        return ToolResult(say=answer, card={"body": answer})

    # ---- history --------------------------------------------------------------------------
    def conversation_id(self) -> int:
        """The conversation in progress; a new one starts after 10 minutes of quiet."""
        if self._conversation is None or time.time() - self._last_turn > CONVERSATION_IDLE_S:
            self._conversation = self.store.new_conversation()
        self._last_turn = time.time()
        return self._conversation

    def new_conversation(self) -> int:
        self._conversation = self.store.new_conversation()
        self._last_turn = time.time()
        return self._conversation

    def continue_conversation(self, conversation_id: int) -> None:
        self._conversation = conversation_id
        self._last_turn = time.time()

    def _record(self, conversation: int, text: str, result: ToolResult) -> None:
        """Keep the exchange for the History tab. Confirmation answers ("yes") are kept too, so the
        conversation reads naturally; what was typed into other apps isn't."""
        self.store.add_message(conversation, "user", text.strip())
        reply = result.say.strip()
        if not reply and any(a.get("type") == "insert_text" for a in result.client_actions):
            reply = "(Wrote it into the app.)"
        if reply:
            self.store.add_message(conversation, "assistant", reply)

    # ---- output ---------------------------------------------------------------------------
    def _finish(self, run_id: str, result: ToolResult, text: str) -> dict:
        if result.status != "ok" and not _has_mood(result):
            result.client_actions.append(mood("puzzled"))
        if result.say:
            self.bus.publish("assistant.message", run_id=run_id, text=result.say)
        self.bus.publish("state.changed", run_id=run_id, state="idle")
        self.bus.publish("run.ended", run_id=run_id, status="ok" if result.status == "ok" else "error")
        return self._response(result)

    @staticmethod
    def _response(result: ToolResult) -> dict:
        out = {"status": result.status, "say": result.say, "card": result.card, "client_actions": result.client_actions}
        if "confirm_id" in result.data:
            out["confirm_id"] = result.data["confirm_id"]
        return out


def mood(name: str) -> dict:
    """A client action that makes the notch's eyes react: love | happy | puzzled."""
    return {"type": "mood", "mood": name}


def _has_mood(result: ToolResult) -> bool:
    return any(a.get("type") == "mood" for a in result.client_actions)


def tidy_written(text: str, request: str, casual: bool = False) -> str:
    """Small models add template scaffolding despite instructions: drop [placeholders] and an
    unrequested subject line, and fix the greeting and sign-off a removed name leaves behind.
    Chat messages lose a nameless greeting altogether."""
    if "subject" not in request.lower():
        text = SUBJECT_LINE.sub("", text)
    text = PLACEHOLDER.sub("", text)
    text = re.sub(r"^(Dear|Hi|Hello|Hey)\s*,", "Hi,", text, flags=re.M)
    if casual:
        text = re.sub(r"\AHi,\s*", "", text.strip())
    lines = [line.rstrip() for line in text.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text.removesuffix(",") if "\n" in text else text


def _strip(response: dict) -> dict:
    return {k: response[k] for k in ("status", "say", "card", "client_actions") if k in response}
