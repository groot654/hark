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

from hark.engine.core import prompts
from hark.engine.core.intents import Intent, match, normalise
from hark.engine.core.llm import LLMClient, LLMUnavailable
from hark.engine.core.transcript_filter import is_noise
from hark.engine.eventbus import EventBus
from hark.engine.store.sqlite_store import Store
from hark.engine.tools.app_index import AppIndex
from hark.engine.tools.registry import NORMAL, ToolRegistry, ToolResult

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
PENDING_TTL = 120


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
            result = self._dispatch(text, target or {}, selection)
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
        return self._ask_llm(text, target)

    def _run_steps(self, steps: list[Intent], confirmed: bool = False) -> ToolResult:
        if not confirmed:
            risky = [s for s in steps if self.tools.permission(s) != NORMAL]
            if risky:
                confirm_id = uuid.uuid4().hex
                self._pending[confirm_id] = Pending(steps)
                question = self.tools.confirm_text(risky[0])
                self.bus.publish("state.changed", state="confirming")
                return ToolResult(say=question, data={"confirm_id": confirm_id},
                                  card={"title": "Confirm", "body": question + " Say yes or no.", "kind": "reply"})

        combined = ToolResult()
        says: list[str] = []
        for i, step in enumerate(steps):
            self.bus.publish("plan.step.started", index=i, tool=step.tool, args=step.args)
            result = self._run_one(step)
            self.bus.publish("tool.result", tool=step.tool, status=result.status, message=result.say)
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
        return combined

    def _run_one(self, step: Intent) -> ToolResult:
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
        result = self._run_steps(steps)
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
        style = "Use a casual, friendly tone." if app in ("whatsapp", "telegram", "discord", "slack") else \
            "Use a clear, professional tone." if app in ("outlook", "olk", "thunderbird") else ""
        try:
            text = self.llm.chat(
                [{"role": "system", "content": prompts.WRITER.format(style=style)},
                 {"role": "user", "content": f"Write {request}"}],
                temperature=0.6, max_tokens=500,
            )
        except LLMUnavailable:
            return ToolResult(status="error", say="Writing needs the AI model, which isn't ready yet.")
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
            return ToolResult(say="I didn't catch a command there, and my AI model isn't running yet.")
        except ValueError:
            decision = {}
        tool = decision.get("tool")
        if tool and self.tools.get(tool) and not tool.startswith(("persona.", "system.shutdown", "system.restart")):
            return self._run_steps([Intent(tool, decision.get("args") or {}, normalise(text))])
        return self._chat(text)

    def _chat(self, text: str) -> ToolResult:
        if self._conversation is None or time.time() - self._last_turn > 600:
            self._conversation = self.store.new_conversation()
        self._last_turn = time.time()
        history = self.store.recent_messages(self._conversation, limit=8)
        memories = self.store.list_memories()[:20]
        memory_text = ("Things the user has told you to remember:\n" + "\n".join(f"- {m['value']}" for m in memories)) if memories else ""
        now = dt.datetime.now()
        system = prompts.PERSONA.format(today=now.strftime("%A %d %B %Y"), time=now.strftime("%H:%M"), memories=memory_text)
        try:
            answer = self.llm.chat([{"role": "system", "content": system}, *history, {"role": "user", "content": text}],
                                   temperature=0.5, max_tokens=220)
        except LLMUnavailable:
            return ToolResult(say="My AI model isn't running yet, so I can only do commands for now.")
        self.store.add_message(self._conversation, "user", text)
        self.store.add_message(self._conversation, "assistant", answer)
        return ToolResult(say=answer, card={"body": answer})

    # ---- output ---------------------------------------------------------------------------
    def _finish(self, run_id: str, result: ToolResult, text: str) -> dict:
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


def _strip(response: dict) -> dict:
    return {k: response[k] for k in ("status", "say", "card", "client_actions") if k in response}
