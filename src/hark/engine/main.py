"""The engine: a local FastAPI daemon that turns speech into text, actions and replies."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import socket
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hark import __version__
from hark.app.audio_device import from_wav_bytes
from hark.engine.core import prompts
from hark.engine.core.dictation import format_dictation
from hark.engine.core.llm import LLMClient, LLMUnavailable
from hark.engine.core.local_model import MODEL_NAME, LocalModel
from hark.engine.core.orchestrator import Orchestrator
from hark.engine.core.stt import SpeechRecognizer
from hark.engine.eventbus import EventBus, sse_format
from hark.engine.reminders import ReminderScheduler
from hark.engine.security import TokenGuard, issue_token
from hark.engine.store.sqlite_store import Store
from hark.engine.tools.app_index import AppIndex
from hark.paths import db_path, port_file

log = logging.getLogger("hark.engine")

DEFAULT_PORT = 7861


class ChatRequest(BaseModel):
    text: str
    target: dict = {}
    selection: str | None = None


class ConfirmRequest(BaseModel):
    id: str
    approved: bool


class PolishRequest(BaseModel):
    text: str
    style: str = "clean"
    app: str = ""


class Engine:
    def __init__(self, stt_backend: str = "parakeet", llm_mode: str = "builtin", llm_url: str = "",
                 llm_model: str = "") -> None:
        self.bus = EventBus()
        self.store = Store(db_path())
        self.llm = LLMClient()
        if llm_url:
            self.llm.set_endpoint(llm_url, llm_model)
        self.llm_mode = llm_mode
        # An explicit server (settings or HARK_LLM_URL) wins over the built-in model.
        self.local_model = LocalModel() if llm_mode == "builtin" and not self.llm.config.base_url else None
        self.stt = SpeechRecognizer(stt_backend)
        self.apps = AppIndex()
        self.orchestrator = Orchestrator(self.store, self.llm, self.apps, self.bus)
        self.reminders = ReminderScheduler(self.store, self.bus)
        self.token = issue_token()
        self.started = time.time()

    def warm_up(self) -> None:
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
            if not self.local_model.installed:
                self.bus.publish("notify", title="Setting up the AI model",
                                 text="Downloading about 570 MB once. Commands work meanwhile.")
            try:
                self.llm.set_endpoint(self.local_model.start(), MODEL_NAME)
                self._warm_llm()
                self.bus.publish("llm.ready", model=MODEL_NAME)
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

        @app.post("/v1/listen", dependencies=[guard])
        def listen(audio: UploadFile = File(...), mode: str = Form("command"), target: str = Form("{}")) -> dict:
            samples = from_wav_bytes(audio.file.read())
            started = time.monotonic()
            transcript = self.stt.transcribe(samples)
            log.info("transcribed %.1fs of audio in %.2fs", samples.size / 16000, time.monotonic() - started)
            target_info = json.loads(target or "{}")
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
            return {"transcript": req.text, **self.orchestrator.handle(req.text, req.target, req.selection)}

        @app.post("/v1/confirm", dependencies=[guard])
        def confirm(req: ConfirmRequest) -> dict:
            return self.orchestrator.confirm(req.id, req.approved)

        @app.post("/v1/dictation/polish", dependencies=[guard])
        def polish(req: PolishRequest) -> dict:
            return {"text": format_dictation(req.text, req.style, req.app, self.store, self.llm)}

        @app.get("/v1/productivity/summary", dependencies=[guard])
        def summary() -> dict:
            return {"card": self.orchestrator.summary_card()}

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


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def start_in_thread(stt_backend: str = "parakeet", port: int = DEFAULT_PORT, llm_mode: str = "builtin",
                    llm_url: str = "", llm_model: str = "") -> tuple[Engine, int]:
    """Run the engine on a daemon thread; returns once it accepts connections."""
    engine = Engine(stt_backend, llm_mode, llm_url, llm_model)
    atexit.register(engine.shutdown)
    port = _free_port(port)
    server = uvicorn.Server(uvicorn.Config(engine.build_app(), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="engine", daemon=True).start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    port_file().write_text(str(port))
    engine.warm_up()
    log.info("engine listening on 127.0.0.1:%d", port)
    return engine, port
