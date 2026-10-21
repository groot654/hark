"""The engine: a local FastAPI daemon that turns speech into text, actions and replies."""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import logging
import socket
import shutil
import threading
import time
from contextlib import asynccontextmanager

import psutil
import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hark import __version__
from hark.app.audio_device import from_wav_bytes
from hark.engine.core import prompts, wake
from hark.engine.core.dictation import format_dictation
from hark.engine.core.intents import Intent
from hark.engine.core.llm import LLMClient, LLMUnavailable
from hark.engine.core.local_model import LocalModel
from hark.engine.core.orchestrator import Orchestrator
from hark.engine.core.stt import SpeechRecognizer
from hark.engine.eventbus import EventBus, sse_format
from hark.engine.reminders import ReminderScheduler
from hark.engine.security import TokenGuard, issue_token
from hark.engine.store.sqlite_store import Store
from hark.engine.tools.app_index import AppIndex
from hark.engine.tools.registry import focus_action
from hark.paths import data_dir, db_path, port_file

log = logging.getLogger("hark.engine")

DEFAULT_PORT = 7861
# HARK_WAKE_DEBUG=1 logs the text of speech that didn't start with the wake phrase (normally never kept).
WAKE_DEBUG = os.environ.get("HARK_WAKE_DEBUG") == "1"


class ChatRequest(BaseModel):
    text: str
    target: dict = {}
    selection: str | None = None
    conversation_id: int | None = None  # continue this conversation (from the History tab)


class ConfirmRequest(BaseModel):
    id: str
    approved: bool


class NotifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    title: str = Field(default="Hark", max_length=80)


class IntegrationRequest(BaseModel):
    name: str
    args: dict = {}


# What other apps (MCP clients) may do: personal lists and timers only. Nothing that types, clicks,
# opens apps, deletes, or reads what Hark remembers about the user.
INTEGRATION_TOOLS = {"task.add", "task.list", "task.complete", "note.add", "note.list", "note.search", "habit.log",
                     "habit.streak", "reminder.add", "reminder.list", "focus.start", "focus.stop", "focus.status"}
# Client actions an integration's result may pass on to the notch.
INTEGRATION_CLIENT_ACTIONS = {"focus", "mood"}


class PolishRequest(BaseModel):
    text: str
    style: str = "clean"
    app: str = ""


class Engine:
    def __init__(self, stt_backend: str = "parakeet", llm_mode: str = "builtin", llm_url: str = "",
                 llm_model: str = "", history_days: int = 30, llm_size: str = "small") -> None:
        self.history_days = history_days
        self.bus = EventBus()
        self.store = Store(db_path())
        self.llm = LLMClient()
        if llm_url:
            self.llm.set_endpoint(llm_url, llm_model)
        self.llm_mode = llm_mode
        # An explicit server (settings or HARK_LLM_URL) wins over the built-in model.
        self.local_model = (LocalModel(size=llm_size)
                            if llm_mode == "builtin" and not self.llm.config.base_url else None)
        self.stt = SpeechRecognizer(stt_backend)
        self.apps = AppIndex()
        self.orchestrator = Orchestrator(self.store, self.llm, self.apps, self.bus)
        self.reminders = ReminderScheduler(self.store, self.bus)
        self.token = issue_token()
        self.started = time.time()

    def warm_up(self) -> None:
        if self.history_days > 0:  # 0 keeps history forever
            self.store.prune_history(self.history_days)
        self.stt.load_async()
        self.apps.refresh_async()
        threading.Thread(target=self._connect_llm, name="llm-start", daemon=True).start()
        self.reminders.start()

    def _connect_llm(self) -> None:
        """built-in: download/start llama-server, falling back to Ollama; external: the configured
        server or Ollama; off: no model."""
        if self.llm_mode == "off":
            return
        if self.local_model is not None:
            choice = self.local_model.choice
            if not self.local_model.installed:
                self.bus.publish("notify", title="Setting up the AI model",
                                 text=f"Downloading about {choice.asset.size / 1e6:.0f} MB once. Commands work meanwhile.")
            if (free := self.local_model.memory_short()) is not None:
                self.bus.publish("notify", title="Low on memory",
                                 text=f"Only {free:.1f} GB is free and this AI model needs about {choice.ram_gb:.1f} GB, "
                                      "so replies may be slow. A smaller size in Settings helps.")
            try:
                self.llm.set_endpoint(self.local_model.start(), choice.name)
                self._warm_llm()
                self.bus.publish("llm.ready", model=choice.name)
                return
            except Exception:
                log.exception("built-in model unavailable; looking for Ollama")
        if self.llm.discover():
            self._warm_llm()

    def _warm_llm(self) -> None:
        """Process the router prompt once so the server caches it and the first command is fast."""
        try:
            system = prompts.ROUTER.format(tools=self.orchestrator.tools.describe_for_llm())
            self.llm.chat([{"role": "system", "content": system}, {"role": "user", "content": "hi"}],
                          max_tokens=1, timeout=60)
        except LLMUnavailable:
            log.warning("model warm-up failed")

    def system_check(self) -> list[dict]:
        """The engine's half of System Check: speech model, AI model, disk space, memory."""
        items = []
        if self.stt.error:
            items.append(check("Speech recognition", "error", self.stt.error,
                               "Restart Hark. If it keeps failing, try the other speech model in Settings."))
        elif self.stt.ready.is_set():
            items.append(check("Speech recognition", "ok", f"Ready ({self.stt.backend})."))
        else:
            items.append(check("Speech recognition", "warn", "Still loading (the first start downloads ~640 MB)."))

        builtin = self.local_model.status() if self.local_model else None
        if self.llm_mode == "off":
            items.append(check("AI model", "ok", "Off: commands work, chat and writing don't."))
        elif self.llm.available():
            items.append(check("AI model", "ok", f"Ready ({self.llm.config.model or 'local model'})."))
        elif builtin and builtin["state"] == "downloading":
            items.append(check("AI model", "warn", f"Downloading: {round(builtin['progress'] * 100)}%."))
        elif builtin and builtin["state"] == "error":
            items.append(check("AI model", "error", builtin["error"] or "Couldn't start.",
                               "Restart Hark, or pick Ollama or Off under Settings → Privacy & AI."))
        else:
            items.append(check("AI model", "warn", "Not running yet.",
                               "It starts by itself; with the external option, check Ollama is running."))

        free_gb = shutil.disk_usage(data_dir()).free / 1e9
        items.append(check("Disk space", "ok" if free_gb >= 2 else "warn", f"{free_gb:.1f} GB free.",
                           None if free_gb >= 2 else "Models and history need a little room; free some space."))
        mem_gb = psutil.virtual_memory().available / 1e9
        items.append(check("Memory", "ok" if mem_gb >= 1.5 else "warn", f"{mem_gb:.1f} GB free.",
                           None if mem_gb >= 1.5 else "The AI model may be slow. Closing a few apps helps."))
        return items

    def _focus_status(self) -> str:
        focus = self.store.active_focus()
        if not focus:
            return "No focus session is running."
        left = max(0, round((focus["started_at"] + focus["planned_minutes"] * 60 - time.time()) / 60))
        label = f" on {focus['label']}" if focus["label"] else ""
        return f"Focus session{label}: {left} of {focus['planned_minutes']} minutes left."

    def _wake(self, transcript: str, target: dict) -> dict:
        """A burst heard while idle: act only if it opens with the wake phrase. Anything else is
        background speech, so neither the transcript nor its text in the log is kept."""
        rest = wake.match(transcript, target.get("wake_phrase") or wake.DEFAULT_PHRASE)
        if rest is None:
            if WAKE_DEBUG:  # opt-in: shows what was heard, to tune the matcher
                log.info("wake phrase not detected in %r", transcript)
            else:
                log.info("wake phrase not detected")
            return {"transcript": "", "wake": False, "client_actions": []}
        log.info("wake phrase heard")
        if not rest.strip(" .!?"):
            return {"transcript": transcript, "wake": True, "follow_up": True, "client_actions": []}
        return {"transcript": rest, "wake": True, **self.orchestrator.handle(rest, target)}

    def shutdown(self) -> None:
        if self.local_model is not None:
            self.local_model.stop()

    def build_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            self.bus.bind(asyncio.get_running_loop())
            yield

        app = FastAPI(title="hark engine", version=__version__, lifespan=lifespan)
        guard = Depends(TokenGuard(self.token))

        @app.get("/v1/system/health", dependencies=[guard])
        def health() -> dict:
            return {
                "version": __version__,
                "uptime": round(time.time() - self.started),
                "stt": {"backend": self.stt.backend, "ready": self.stt.ready.is_set() and not self.stt.error,
                        "error": self.stt.error},
                "llm": {"mode": self.llm_mode, "url": self.llm.config.base_url, "model": self.llm.config.model,
                        "available": self.llm.available(),
                        "builtin": self.local_model.status() if self.local_model else None},
            }

        @app.post("/v1/system/notify", dependencies=[guard])
        def notify(req: NotifyRequest) -> dict:
            """Show a short message in the notch (a second launch, MCP clients)."""
            self.bus.publish("notify", title=req.title, text=req.text)
            return {"ok": True}

        @app.post("/v1/integrations/tool", dependencies=[guard])
        def integration_tool(req: IntegrationRequest) -> dict:
            """One allow-listed tool call from another app (see `hark --mcp`)."""
            if req.name not in INTEGRATION_TOOLS:
                raise HTTPException(status_code=403, detail=f"{req.name} isn't available to other apps")
            if req.name == "focus.status":
                return {"ok": True, "text": self._focus_status(), "items": None}
            result = self.orchestrator.tools.run(Intent(req.name, dict(req.args), f"integration {req.name}"))
            actions = [a for a in result.client_actions if a.get("type") in INTEGRATION_CLIENT_ACTIONS]
            if actions:
                self.bus.publish("client.actions", actions=actions)  # e.g. show the focus countdown
            log.info("integration tool %s -> %s", req.name, result.status)
            return {"ok": result.status == "ok", "text": result.say, "items": (result.card or {}).get("items")}

        @app.post("/v1/listen", dependencies=[guard])
        def listen(audio: UploadFile = File(...), mode: str = Form("command"), target: str = Form("{}")) -> dict:
            samples = from_wav_bytes(audio.file.read())
            started = time.monotonic()
            transcript = self.stt.transcribe(samples)
            log.info("transcribed %.1fs of audio in %.2fs", samples.size / 16000, time.monotonic() - started)
            target_info = json.loads(target or "{}")
            if mode == "wake":
                return self._wake(transcript, target_info)
            if not transcript:
                return {"transcript": "", "client_actions": []}
            if mode == "dictation":
                style = target_info.get("dictation_style") or self.store.get_setting("dictation.style", "clean")
                text = format_dictation(transcript, style, target_info.get("app", ""), self.store, self.llm)
                self.bus.publish("dictation.done", chars=len(text))
                return {"transcript": transcript, "text": text,
                        "client_actions": [{"type": "insert_text", "text": text}] if text else []}
            return {"transcript": transcript, **self.orchestrator.handle(transcript, target_info)}

        @app.post("/v1/chat", dependencies=[guard])
        def chat(req: ChatRequest) -> dict:
            if req.conversation_id:
                self.orchestrator.continue_conversation(req.conversation_id)
            out = self.orchestrator.handle(req.text, req.target, req.selection)
            return {"transcript": req.text, "conversation_id": self.orchestrator.conversation_id(), **out}

        @app.get("/v1/history", dependencies=[guard])
        def history() -> dict:
            return {"conversations": self.store.conversations()}

        @app.get("/v1/history/{conversation_id}", dependencies=[guard])
        def history_conversation(conversation_id: int) -> dict:
            return {"id": conversation_id, "messages": self.store.conversation_messages(conversation_id)}

        @app.post("/v1/history/new", dependencies=[guard])
        def history_new() -> dict:
            return {"id": self.orchestrator.new_conversation()}

        @app.get("/v1/system/check", dependencies=[guard])
        def system_check() -> dict:
            return {"items": self.system_check()}

        @app.post("/v1/confirm", dependencies=[guard])
        def confirm(req: ConfirmRequest) -> dict:
            return self.orchestrator.confirm(req.id, req.approved)

        @app.post("/v1/dictation/polish", dependencies=[guard])
        def polish(req: PolishRequest) -> dict:
            return {"text": format_dictation(req.text, req.style, req.app, self.store, self.llm)}

        @app.get("/v1/productivity/summary", dependencies=[guard])
        def summary() -> dict:
            return {"card": self.orchestrator.summary_card(), "focus": focus_action(self.store.active_focus())}

        @app.get("/v1/memory", dependencies=[guard])
        def memory() -> dict:
            return {"memories": self.store.list_memories()}

        @app.get("/v1/data/export", dependencies=[guard])
        def export() -> dict:
            return self.store.export_all()

        @app.post("/v1/data/clear", dependencies=[guard])
        def clear() -> dict:
            self.store.clear_all()
            return {"ok": True}

        @app.get("/v1/events", dependencies=[guard])
        async def events(request: Request) -> StreamingResponse:
            queue = self.bus.subscribe()

            async def stream():
                try:
                    yield ": connected\n\n"
                    while not await request.is_disconnected():
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=15)
                            yield sse_format(event)
                        except TimeoutError:
                            yield ": ping\n\n"
                finally:
                    self.bus.unsubscribe(queue)

            return StreamingResponse(stream(), media_type="text/event-stream")

        return app


def check(name: str, status: str, detail: str, fix: str | None = None) -> dict:
    """One System Check line: status is ok | warn | error."""
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def start_in_thread(stt_backend: str = "parakeet", port: int = DEFAULT_PORT, llm_mode: str = "builtin",
                    llm_url: str = "", llm_model: str = "", history_days: int = 30,
                    llm_size: str = "small") -> tuple[Engine, int]:
    """Run the engine on a daemon thread; returns once it accepts connections."""
    engine = Engine(stt_backend, llm_mode, llm_url, llm_model, history_days, llm_size)
    atexit.register(engine.shutdown)
    port = _free_port(port)
    # log_config=None: use the logging Hark already set up. Uvicorn's own setup fails when there is no
    # stderr at all, which is how Windows starts Hark at sign-in (pythonw / the windowed exe).
    server = uvicorn.Server(uvicorn.Config(engine.build_app(), host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None))
    threading.Thread(target=server.run, name="engine", daemon=True).start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    port_file().write_text(str(port))
    engine.warm_up()
    log.info("engine listening on 127.0.0.1:%d", port)
    return engine, port
