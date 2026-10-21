# 01 - heynixi engine: API surface, data model, configuration

Source: heynixi 0.2.1 (`BUILD-METADATA.json`: commit `19c58a33...`, built 2026-10-18), Nuitka-compiled `heynixi.exe`.
Evidence:
- **[S]** = observed in `strings-ascii.txt`. The hex value is the string offset, e.g. `@8ce343c`.
- **[DB]** = observed in a *copy* of `nexus.db`+WAL, made to the scratchpad. The live file was not opened.
- **[LOG]** = observed in `%LOCALAPPDATA%\heynixi\logs`.
- **[FS]** = observed on disk (install dir, registry).
- **[INF]** = inferred.

**Extraction limit:** the string dump keeps only strings of 6 characters or more. Nuitka writes attribute names with an `a` prefix, so any identifier of 5 characters or fewer is invisible. That includes field names such as `text`, `mode`, `file`, `kind`, `tool`, `args`, `name`, `key`, `id`, `type` and `runs`, and the HTTP verbs `get`/`post`/`put`. Numeric defaults (ints and floats) are stored as marshalled constants and cannot be recovered. Wherever one of these appears below, it is marked [INF].

---

## 0. Process architecture (corrects the brief)

| Fact | Evidence |
|---|---|
| A single exe runs both the engine and the Qt client in **one process**. `__main__` (`notch_main.py`) starts uvicorn in a daemon thread named `notch-engine`, waits for `/health`, then calls `app.nexus_app` desktop_main. A thread named `notch-supervisor` supervises both. | [S] `unotch-engine @8b60d0c`, `uProduction entry point: supervise the engine and desktop client together. @8b60ead`, `auvicorn/aConfig/aServer @8b60c92`. [LOG] app.* and engine.* loggers write to the same `nexus.log` |
| CLI flags: `--mcp` (stdio MCP server), `--a11y-wake` (runs `engine.nexusd.tools.a11y_wake.serve`), `--self-test` (packaged self-test that writes a JSON report), `--multiprocessing-fork`. | [S] `u--mcp @8b60ac1`, `u--a11y-wake @8b60af2`, `u--self-test @8b60b1e`, `u--multiprocessing-fork @8b613d0` |
| Port choice `_usable_port`: preferred `7860` if free, otherwise any free port. An explicit `NEXUS_PORT` is never moved. The chosen port is written to `<data_dir>/engine.port` ("for a second launch and the MCP bridge"). `NEXUS_API_URL` is also set for the client. | [S] `@8b5fa76`, `@8b5fc78`. [FS] engine.port = `7860` |
| A second launch first probes `engine.port` + `/health`. It checks `service == "notch-engine"` (`_is_notch_engine`), then knocks on a singleton TCP socket (`NEXUS_SINGLETON_PORT`) so the running pill comes to the front. | [S] `@8b5fdaf`, `@8b6013d`, `@8bec13b` |
| uvicorn log level comes from `NEXUS_UVICORN_LOG_LEVEL` (default `warning`), with `access_log` off [INF]. | [S] `@8b60ca5` |
| The client connects over HTTP `http://127.0.0.1:{NEXUS_PORT}` plus WebSocket `ws://127.0.0.1:{port}/v1/events` (WSThread). It uses no SSE. | [S] `=uws://127.0.0.1: @8bed001`, `u/v1/events @8bed013` |
| **There are no QSettings.** The PySide app never uses QSettings. User settings are a **dotenv file** of `NEXUS_*` keys (section 3). The registry key `HKCU\Software\NEXUS\heynixi` holds only `InstallDir`, written by the NSIS installer. Autostart uses `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. | [FS] registry query. [S] `uNative customer settings UI; .env is an implementation detail here. @8bfb0e6`, `@8bb20ec` |

---

## 1. HTTP / WebSocket API (FastAPI app `NEXUS Engine (nexusd)`)

`create_app()` includes the routers in this order: chat, confirm, conversations, events, listen, partial, tts, memory, runs, sessions, system, write, dictation, models, integrations [S `@8d14b85`..`@8d14cb1`]. Middleware: `CORSMiddleware(allow_origins=trusted, allow_methods, allow_headers)` and `BrowserRequestGuard` (section 6).

The verb column is [INF] unless stated otherwise. The inference rule: body model means POST; Query/path-only parameters mean GET; `delete` handler names mean DELETE.

### 1.1 Route table

| Method | Path | Handler / models | Purpose / response | Evidence |
|---|---|---|---|---|
| POST | `/v1/chat` | `ChatRequest` -> `ChatResponse` (`response_model`) | Main turn. The client POSTs `{messages:[{role:"user",content}], conversation_id}`. Delegates to `Orchestrator.handle_chat`, which is documented as a "Legacy endpoint ... WS remains the authoritative stream; this yields only the final text". | `@8ce343c`, `@8cfd765` |
| POST | `/v1/chat/stream` | `ChatRequest` -> `StreamingResponse(media_type="text/event-stream")` | SSE variant built on `handle_chat_stream`. Each chunk is `sse_data({...})`. The event type is `assistant.delta`. | `@8ce3643`, `utext/event-stream @8ce37a8`, `uassistant.delta @8ce37f2` |
| POST | `/v1/confirm` | `ConfirmRequest{conversation_id: str (required), confirmed: bool}` -> `ChatResponse` | Resolves the pending tool/plan proposal for that conversation with no LLM call. Docstring: "conversation_id is required: confirmations are per-conversation". | `@8ce3a04`, `@8ce3c43`, `@8cfd329` |
| GET | `/v1/conversations?limit&offset` | Query params | `{items:[{id, created_at, updated_at, messages_since_summary, pending_type, preview, message_count}], total, limit, offset}` [field set: S, shape: INF] | `@8ce3e46`..`@8ce4157` |
| GET | `/v1/conversations/{conversation_id}?messages_limit&messages_offset` | | `{id, created_at, updated_at, memory_summary, memory_updated_at, messages_since_summary, messages:[{id, role, content, created_at}], total}`. 404 `Conversation not found`. | `@8ce3f70`, `@8ce4183` |
| WS | `/v1/events` | `WebSocket` | Event stream (section 1.3). Rejects untrusted browser `Origin` with close code `WS_1008_POLICY_VIOLATION`. Then `accept()`, `bus.subscribe()`, a loop of `asyncio.wait_for(queue.get, timeout)` -> `send_json(evt)`, and `unsubscribe` on `WebSocketDisconnect`. | `@8ce5028`, `@8ce5103` |
| POST | `/v1/listen/start` | `ListenStartRequest{audio_b64: str (max_length=MAX_AUDIO_B64_CHARS), conversation_id: Optional[str]}` | Transcribes base64 WAV for the chat-routing voice path. Emits `stt.started` -> `stt.ended` -> `transcript.final`. Strips a triggered wake phrase. Uses run id `stt_run_id` = uuid4 and conversation id `stt-no-convo` when none is given. Returns the transcript and ids [INF]. The client then POSTs the text to `/v1/chat`. | `@8ce5aa2`, `@8ce6138`, `@8ce5d48`..`@8ce5e22` |
| POST | `/v1/listen` | multipart `file: UploadFile`, form `mode: Optional[str]` [names INF] | Pure transcription with no routing. The client sends `?mode=dictation` with multipart boundary `----nexusdictation` and `filename="dictation.wav"`. Dictation uses the local backend. Errors: 400 `file is required`, `invalid_wav:`, `stt_failed:`. | `@8ce5ba5`, `@8be0748`, `@8be07a7` |
| POST | `/v1/listen/partial` | `PartialRequest{audio_b64, conversation_id: Optional[str], final: bool}` [final: S near handler] | The partial (mid-sentence) command path. The client re-posts the growing buffer about every 700 ms while PTT is held. Returns `{text, ready, command}` plus opens/implicit_app information. Each conversation key gets a `StabilityTracker`; the key `_default` is used when there is no conversation_id. When ready, it can `remember_app_open` for `plan.app.open_and_focus`. | `@8ce7446`, `@8ce748b`..`@8ce758b`, `@8ce71d7`, `@8d0b1f3` |
| POST | `/v1/tts` | `TTSRequest{text (max_length), conversation_id: Optional[str]}` -> `Response(audio/wav)` | Synthesises speech. Emits `tts.started`/`tts.ended` with `tts_run_id`, or `tts-no-convo`. Errors: `tts_unavailable` ("Local voice output is currently unavailable."), `tts_failed`. | `@8cea67b`, `@8cea8b9` |
| GET | `/v1/memory?limit` | | `{items:[{key, value, updated_at}]}` from `global_memories` | `@8ce6402` |
| GET | `/v1/memory/{key}` | | `{key, value}`. 404 when missing [INF]. | `@8ce64b9` |
| PUT | `/v1/memory/{key}` | `MemorySetRequest{value, extra: Optional[Dict]}` [INF names] | Upsert. Handler `memory_put`. | `@8ce65a6` |
| DELETE | `/v1/memory/{key}` | | Handler `memory_delete`. | `@8ce6628` |
| POST | `/v1/memory/set` | `MemorySetCompatRequest{key, value}` | Compat alias. 400 `key is required`. | `@8ce66ae` |
| POST | `/v1/memory/forget` | `MemoryForgetCompatRequest{key}` | Compat alias. | `@8ce6784` |
| GET | `/v1/models/recommend` | | Model picker: `{system:{cpu, cores, ram_gb, gpus, summary}, models:[rated entry...], recommended, selected, selected_id, backend, vision}` (section 4.4) | `@8ce6c92`, `@8cf44a4`..`@8cf4518` |
| POST | `/v1/models/download` | `ModelRequest{id}` [field ≤5 chars, INF `id`] | Starts a background SHA-256-verified download. 404/400 `unknown model`. | `@8ce6d2d`, `@8ce6f35` |
| GET | `/v1/models/downloads` | | `{<model_id>: {state: "downloading"\|"failed"\|..., error}}` | `@8ce6dce`, `@8cf4765` |
| POST | `/v1/models/select` | `ModelRequest` | Writes `selected.json` and hot-switches llama-server when the bundled backend is active. Returns `{message:"Now using X"}` or "Download that model first." | `@8ce6e41`, `@8cf4a93` |
| GET | `/v1/runs/{run_id}` | | Run row `{id, conversation_id, source, status, started_at, ended_at, error_code, error_message}`. 400 `run_id is required`, 404 `run not found`. | `@8ce7ebc` |
| GET | `/v1/runs/{run_id}/events?limit&offset` | | `{run_id, events:[envelope...]}`, ordered by seq ASC | `@8ce7f6b`, SQL `@8d1d37f` |
| GET | `/v1/sessions?limit&include_open` | | "Recent sessions, newest first". The open session is included and flagged. Items are trimmed to `{id, title, summary, started_at, last_activity_at, ended_at, turn_count}`. The client calls `?limit=40`. Returns `{items,total}`. | `@8ce8390`, `@8ce82ea`, `@8be1b70` |
| GET | `/v1/sessions/search?q&limit` | `q` with `min_length` | Search sessions. | `@8ce85d1` |
| GET | `/v1/sessions/{session_id}` | | Session plus `messages:[{role, content, ts}]`, `conversation_id`, `end_reason`, `pruned`, `message_count`. 404 `Session not found`. | `@8ce86c5`, `@8ce883d` |
| GET | `/v1/data/export` | | `{schema, product:"heynixi", exported_at, tables:{<name>: [rows]}}`. The client saves it as `heynixi-data-YYYY-MM-DD.json`. | `@8ce9c51`, `@8d1e617`, `@8be4bd9` |
| POST | `/v1/data/clear` | `ClearUserDataRequest{confirmation}` | Requires the exact string **`CLEAR ALL NOTCH DATA`**, else `confirmation_mismatch`. Response `{deleted/counts}`. | `@8ce9d05`, `@8cea095` |
| GET | `/v1/config` | | `{config:{NEXUS_PORT, ollama_url, fast_model, smart_model, db_path}, stt:{backend, model, quantization, device, providers, model_id, is_local, compute_type}, tts:{backend, available, timeout_s, voice ("system default"), sample_rate, deprecated}, features:{stream_transport, sse_chat_stream_enabled, run_event_persistence}}` [keys: S, nesting: INF] | `@8ce9ddf`, `@8cea149`..`@8cea1db` |
| GET | `/ready` | | `{ready, issues:[{component, level, message, code}]}`. Checks run in a worker thread so CUDA probing cannot freeze the loop. Issue codes are in the table below. | `@8ce9e7d`, `@8ce9e87` |
| GET | `/health` | | `{status, service:"notch-engine", ...}`. The launcher uses it to identify the engine. | `@8d14e6d`, `@8b6013d` |
| POST | `/v1/write/stream` | `WriteRequest{instruction (min/max_length), source (selected text, default "")}` plus one more field with a default [INF] | Streams plain prose: `text/plain; charset=utf-8`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. Errors: `WRITE_OUT_OF_MEMORY`, `WRITE_MODEL_DOWN`, `WRITE_UNAVAILABLE`, `WRITE_LENGTH_FAILED` with the user strings at `@8cebe82`..`@8cebf84`. | `@8ceb930`, `@8cebadb` |
| POST | `/v1/dictation/polish` | `PolishRequest{text (min/max_length)}` -> `PolishResponse{text}` | Local-LLM rewrite for "Polished" dictation. The system prompt is at `@8ce47ab`..`@8ce4d92`. Errors: "Polished dictation needs the built-in model, which isn't running", "The local rewriter returned no text", "...expanded the transcript unexpectedly". | `@8ce4594`, `@8ce4682` |
| POST | `/v1/integrations/tool` | `ToolCall{name, args: Dict[str,Any]}` [INF names] | Runs an **allow-listed** productivity tool in a thread. Anything else returns `tool not available to integrations`. Allow-list: `note.add, note.list, reminder.add, reminder.list, task.add, task.list, task.done, task.clear_done, focus.start, focus.status, focus.stop, habit.log, habit.status`. | `@8ce53e5`, `@8ce5814`..`@8ce58a6` |
| POST | `/v1/integrations/notify` | `Notify{text, title?}` | Publishes `pill.notify` with `{title, text, source:"integration"}` and run/conversation id `system` [INF]. 400 `text is required`. | `@8ce54a2`, `@8ce5630` |
| GET | `/v1/open_ui` | | Opens the browser UI (dev only). | `@8d14eb9` |
| GET | `/`, `/assets/*`, `/{full_path:path}` | | Serves the React build from `NEXUS_STATIC_DIR`; otherwise returns dev info `{service:"NEXUS Engine", status:"running", dev_ui, stream:"ws_only", events_ws:"/v1/events"}`. | `@8d14f42`, `@8d15050`, `@8d158a2` |

`/ready` issue codes [S `@8ce9000`..`@8ce97be`]:

| Code | Level |
|---|---|
| `ollama_http` | error |
| `ollama_unreachable` | error/info, depending on `NEXUS_LLM`: `small` gives error, `auto` gives info, `off` skips the check |
| `ollama_no_models` | |
| `fast_model_missing` | |
| `smart_model_missing` | warning |
| `parakeet_package_missing` | |
| `stt_backend_unsupported` | |
| `stt_package_missing` | |
| `stt_running_on_cpu` | |
| `psutil_missing` | |
| `windows_voice_missing` | |
| `piper_not_found` | |
| `piper_deprecated` | |
| `readiness_unavailable` | client-side |

Audio limits (`api.audio_limits`): `NEXUS_MAX_AUDIO_MB` sets `MAX_AUDIO_BYTES`/`MAX_AUDIO_B64_CHARS` (default not recoverable). Errors: `audio_too_large` (413 [INF]) and `invalid_base64`. Uploads are read up to limit+1 sentinel byte [S `@8ce2f5d`..`@8ce30af`].

### 1.2 Core pydantic schemas (`engine.nexusd.schemas`) [S `@8d1a690`..`@8d1aaf4`]

```python
class ChatMessage(BaseModel):
    role: Literal['system','user','assistant']
    content: str = Field(max_length=...)

class ChatRequest(BaseModel):      # "Clients typically send only the new user message"
    conversation_id: Optional[str] = Field(default=None, max_length=...)   # omitted -> server creates one
    messages: List[ChatMessage] = Field(min_length=1, max_length=...)

class ChatResponse(BaseModel):     # "Unified response contract"
    type: Literal['response'] = 'response'     # [S Literal['response']]
    text: str                                  # [INF]
    conversation_id: str                       # [INF]
    run_id: Optional[str]                      # [S]
    tool: Optional[Dict[str, Any]]             # {"type":"plan","data":{...}} | {"type":"tool","data":{...}} | None  [S docstring]
    kind: str = 'answer'                       # "action"|"answer"|"confirm"|"error" [S @8cfeab8; default 'answer' INF]
```

Plans use dataclasses (`plans.schemas`) [S `@8d1a44d`]:
- `PlanProposal{name, args: Dict, confirm: str, permission: str}`
- `PlanStep{tool, args, retry, timeout_ms: Optional[int]}`
- `PlanResult{status, display: Optional[str], artifacts: List = [], telemetry}`

Registered plans: `plan.app.open_and_focus`, `plan.clipboard.write`, `plan.email.draft`, `plan.notepad.write`, `plan.sequence`.

### 1.3 Event bus, envelope, event types

`EventBus` is broadcast-only, with one `asyncio.Queue(maxsize=?)` per subscriber [S `@8d13fde`]. Design rules from the docstring:
- the engine never stalls on slow subscribers;
- `QueueFull` drops events silently;
- dead connections are removed;
- optional **sinks** can persist events, and sink failures never break the engine.

`main` adds the sink `store.add_run_event`.

**Canonical envelope** [S `@8d14024`, DB]:

```json
{"type":"plan.step.ended","ts":"2026-10-21T07:13:03.281Z","seq":23,
 "run_id":"6e30f02d33f64c3497f3cff12e918b71","conversation_id":"a72330b5-1cd6-4fa8-89b3-dc9a96b1c958","data":{...}}
```

- `ts`: UTC ISO-8601 with milliseconds and a `Z` suffix (`+00:00` is replaced).
- `seq`: a **process-global** monotonically increasing counter, not per run. In the DB, seq values 16, 23 and 190 all come from one conversation.
- `run_id`: uuid4 hex. `conversation_id`: uuid4 with dashes [DB].

Event types:

| Type | Producer | `data` (observed [DB] or [INF]) |
|---|---|---|
| `run.started` | orchestrator.emit_run_started | `{source:"chat", text}` [DB] |
| `run.state` and `state.changed` | emit_state publishes both, every time | `{state}`. Observed: `thinking`, `acting`, `idle` [DB]. Client also handles `confirming`, `listening` [S `@8be5c2d`] |
| `run.ended` | emit_run_ended | `{status:"ok"\|"error", error_code?, error_message?}` [DB/S] |
| `assistant.message` | orchestrator | `{text, speak: bool, kind:"action"\|"answer"\|...}` [DB] |
| `assistant.delta` | chat_stream (SSE) | text chunk [INF] |
| `assistant.plan` + `plan.proposed` | _emit_plan_proposal | `{plan:{name, args, confirm:"Open and focus Chrome?", permission:"normal"}}` [DB] |
| `assistant.tool` + `tool.proposed` | _emit_tool_proposal | `{tool:{name, args, confirm, permission}}` [INF, mirrors plan] |
| `plan.started` | plans.runner | `{name, permission}` [DB] |
| `plan.step.started` | runner | `{name, index, tool, args}` [DB] |
| `tool.result` | runner / _execute_tool | `{tool, result:{status, message, data}}` [DB] |
| `plan.step.ended` | runner | `{name, index, tool, status, ms, result}` [DB] |
| `plan.completed` | runner | `{name, ms, status}` [DB] |
| `error.raised` | orchestrator | `{code:"RuntimeError"\|"action_failed"\|..., message}` [DB/S] |
| `stt.started`, `stt.ended`, `transcript.final` | routes_listen | `{stt_run_id/run_id, conversation_id, text?, error?, wake_triggered?}` [S names] |
| `tts.started`, `tts.ended` | routes_tts | `{tts_run_id, error?}` |
| `agent.step` | core.agent via main's `set_publisher` | screen/web-agent progress, run/conv `system` [S `@8d15725`] |
| `pill.notify` | integrations | `{title, text, source}` |
| `reminder.due`, `focus.done` | productivity scheduler (`run_scheduler`) | shown on the pill and as a Windows tray notification [S `@8d3d795`] |
| `media.now_playing` | now_playing watcher | client `show_now_playing` |
| `reminder.clear` | tools | client clears a pending reminder card |

The client also dispatches tool names that arrive in `tool.result`: `screen.point`, `teleprompter.start/stop` and `input.send_keys` media keys. These run in the client [S `@8be5a6b`..`@8be5b35`].

**Persistence caveat [INF]:** `run_events` has foreign keys to `runs` and `conversations` with `PRAGMA foreign_keys=ON`, and `add_run_event` swallows errors. As a result, events whose `run_id` is not a real run (`stt-…`, `tts-…`, `system`) are not persisted. All 13 persisted types in the DB are the run-lifecycle types.

### 1.4 Run / confirm lifecycle

Pipeline priority order (`_run_core_pipeline` docstring [S `@8cfcc50`]):
1. memory fast-path;
2. confirmation fast-path;
3. deterministic plan/tool intent;
4. LLM path (`tool_call` / `plan_call` / plain response).

All tool dispatch goes through `_route_as_tool`, which "execute[s] it when it is safe, otherwise propose[s] it" [S `@8cfc45a`].

Observed sequences in the DB:

```
deterministic plan:
  run.started > run.state/state.changed(thinking) > assistant.plan > plan.proposed > run.state(acting)
  > plan.started > plan.step.started > tool.result > plan.step.ended > plan.completed > assistant.message
  > run.state(idle) > run.ended(ok)

tool:     run.started > state(thinking) > state(acting) > tool.result > assistant.message > state(idle) > run.ended
answer:   run.started > state(thinking) > assistant.message > state(idle) > run.ended
error:    ... > error.raised > run.ended(error)     (runs.error_code='RuntimeError', "Model error (503): The built-in model is still loading.")
```

**Permission tiers:** `normal | sensitive | destructive` [S `@8d4bdb2`]. Per-tool overrides come from `NEXUS_TOOL_PERMISSIONS="tool:tier,tool:tier"` [S `@8d40c46`].
- `normal` runs immediately. A `plan.proposed` is still emitted, but "No plan currently requires confirmation" [S `@8cfc6c3`].
- `sensitive` and `destructive` produce a proposal and leave the run open (`_PipelineResult.ended=False`, "confirming state that leaves the run open"). The prompt is "Proceed?". Destructive prompts are prefixed "This cannot be undone." [S `@8cfc63e`, `@8cfc664`].
- The pending action is persisted in `conversations.pending_type` / `pending_json` / `pending_updated_at`.
- The LLM prompt gets a `PENDING CONFIRMATION:` block [S `@8cfab40`].

Resolution happens in one of two ways:
1. **Button press:** POST `/v1/confirm {conversation_id, confirmed}` (`Orchestrator.handle_confirm`; replies "Got it." / "Cancelled.").
2. **Voice:** "yes/no" goes through `/v1/chat` and the confirmation classifier [S `@8cfd329`..`@8cfd535`].

The client shows `_awaiting_confirm` and HUD state `confirming` [S `@8be5c39`].

---

## 2. SQLite schema (`%LOCALAPPDATA%\heynixi\nexus.db`)

PRAGMAs applied on open [S `@8d1be90`..`@8d1bee5`]: `journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON; secure_delete=ON`. One persistent connection uses `check_same_thread=False` behind a threading lock. `PRAGMA user_version` = 0, so there is no versioned migration. All migrations are additive (`_ensure_columns`).

### 2.1 `SQLiteStore._init_db` (verbatim [S `@8d1bf03`..`@8d1d0c7`], confirmed [DB])

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    memory_summary TEXT NOT NULL DEFAULT '',
    memory_updated_at TEXT NOT NULL DEFAULT '',
    messages_since_summary INTEGER NOT NULL DEFAULT 0,
    pending_type TEXT NOT NULL DEFAULT '',
    pending_json TEXT NOT NULL DEFAULT '',
    pending_updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS global_memories (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- migrations
ALTER TABLE messages ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
ALTER TABLE messages ADD COLUMN ts TEXT NOT NULL DEFAULT '';
UPDATE messages SET created_at = ts WHERE (created_at IS NULL OR created_at = '') AND ts IS NOT NULL AND ts != '';
UPDATE messages SET ts = created_at WHERE (ts IS NULL OR ts = '') AND created_at IS NOT NULL AND created_at != '';
-- _ensure_columns('conversations', updated_at/memory_summary/memory_updated_at/pending_*: TEXT NOT NULL DEFAULT '', messages_since_summary: INTEGER NOT NULL DEFAULT 0)
UPDATE conversations SET updated_at = created_at WHERE updated_at = '' OR updated_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_messages_convo_created ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_convo_started ON runs(conversation_id, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_profile_facts_updated ON profile_facts(updated_at);
CREATE INDEX IF NOT EXISTS idx_profile_notes_created ON profile_notes(created_at);
CREATE INDEX IF NOT EXISTS idx_reminders_created ON reminders(created_at);
```

### 2.2 `core.sessions.SessionManager._ensure_schema` [S `@8d07090`..`@8d0741b`]

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    ended_at         TEXT,
    end_reason       TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT '',
    title            TEXT NOT NULL DEFAULT '',
    summary          TEXT NOT NULL DEFAULT '',
    turn_count       INTEGER NOT NULL DEFAULT 0,
    pruned           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_activity ON sessions(last_activity_at DESC);
ALTER TABLE messages ADD COLUMN session_id TEXT;          -- if PRAGMA table_info(messages) lacks it
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
```

Session lifecycle SQL [S `@8d074ce`..`@8d089ea`]:
- find the open session: `ended_at IS NULL`, latest by conversation;
- bump: `turn_count+1`, `last_activity_at`;
- idle close: `end_reason='idle'` after `NEXUS_SESSION_IDLE_S`;
- create: `INSERT ... turn_count=1`;
- tag messages: `UPDATE messages SET session_id=? WHERE conversation_id=? AND session_id IS NULL`;
- prune: after `NEXUS_HISTORY_DAYS`, `DELETE FROM messages WHERE session_id=?` then `pruned=1` and `wal_checkpoint(TRUNCATE)`;
- titles: a no-LLM `_fallback_title` (quoting the first ask, default `Untitled`), plus a summary.

On startup `_settle_history` closes sessions left open and applies retention [S `@8d154a0`].

### 2.3 `tools.productivity.ProductivityStore` (same DB file, separate connection, `executescript`) [S `@8d3a67e`..`@8d3aa9e`]

```sql
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, done_at TEXT);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS habit_logs (habit_id INTEGER NOT NULL, day TEXT NOT NULL,
    PRIMARY KEY (habit_id, day));
CREATE TABLE IF NOT EXISTS timed_reminders (id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, due_at TEXT NOT NULL, fired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS focus_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL, minutes INTEGER NOT NULL, started_at TEXT NOT NULL,
    ends_at TEXT NOT NULL, ended INTEGER NOT NULL DEFAULT 0);
-- tools.registry (memory / routines tools) [S @8d3c800, @8d3cd94]
CREATE TABLE IF NOT EXISTS global_memories (key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS routines (name TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
```

### 2.4 Notable store operations [S `@8d1d1f0`..`@8d1f532`]
- **Timestamps:** `_utc_ts` uses ISO ms + `Z` for messages, runs and events. Sessions use seconds + `+00:00` [DB].
- **Runs:** `start_run` inserts status `'running'`. `end_run(status, error_code, error_message)` sets the final state. Statuses seen: `running|ok|error`. The error_code `action_failed` is used for handled tool failures [S `@8cfb6f3`].
- **Data clear** (`clear_user_data`): runs in `BEGIN IMMEDIATE`, then `DELETE FROM` each of `run_events, messages, (runs), sessions, conversations, global_memories, reminders, profile_facts, profile_notes`, with rollback on error. The export uses the same `_USER_DATA_TABLES`.
  - [INF] The productivity tables (tasks, notes, habits, timed_reminders, focus_sessions, routines) are **not** in that list.
- **purge_text_everywhere** ("forget my name"): runs `LIKE` deletes across `run_events.json`, `messages.content`, `conversations.memory_summary`, `runs.error_message` and sessions title/summary, then `wal_checkpoint(TRUNCATE)`.
- **fetch_recent_messages_for_prompt(max_messages, max_chars):** `ORDER BY created_at DESC LIMIT ?`.

Other files in the data dir:

| File | Contents | Evidence |
|---|---|---|
| `onboarding-v2.done` | contains `completed` | [FS] |
| `startup-guard.json` | `{"unfinished": 0}`. A crash-loop guard that sets `NEXUS_SAFE_MODE=1`. | [FS] [S `@8bfda64`] |
| `dictation-personalization.json` | dictionary, snippets, per-app styles | [S `@8bb8272`] |
| `models/selected.json` | the selected model | [S `@8cf461f`] |
| `logs/{nexus.log, client.log, hang-stacks.txt, crashes/}` | logs | |
| `nixi-llama-server.log` | llama-server output | [S `@8cef34a`] |

---

## 3. Settings schema

Storage is a **dotenv file**, not QSettings or the registry. Its path is `paths.env_file()`: `NEXUS_ENV_PATH`, else `<config_dir>/.env` [INF filename, S `@8d176e9` "Dotenv file used by both processes."]. `config_dir` is `NEXUS_CONFIG_DIR`, else `<data_dir>/config` [S `@8d175cd`/`@8d175df`]. It does not exist yet on this PC because nothing has been saved.

How it is written and read:
- `save_settings` atomically rewrites only the managed keys, using a temp file + fsync + replace. It preserves all other lines and adds the header `# heynixi user settings` [S `@8bfc7c6`, `@8bfc8dc`].
- `apply_to_environment` pushes the values into `os.environ`, and `from_environment()` reads them back.
- `restart_needed()` returns display names (`talk key`, `dictation key`, `speech model`, `wake phrase`) for keys that require a restart. The docs say all settings need a restart.

`app.settings_store.Settings` dataclass, with the `_KEYS` mapping [S `@8bfcb26`..`@8bfcd75`]:

| Field | Env key | Values / validation | Default |
|---|---|---|---|
| dictation_mode | `NEXUS_DICTATION_MODE` | `exact\|clean\|polished` | `clean` [S `@8bfc198`] |
| ptt_mode | `NEXUS_PTT_MODE` | `hold\|toggle` ("Command trigger mode") | `hold` [LOG] |
| ptt_key | `NEXUS_PTT_KEY` | key name ("Command hotkey") | `right ctrl` [S `@8bfc32c`, LOG] |
| dictation_key | `NEXUS_DICTATION_KEY` | key name | `right alt` [S `@8bfcaa0`, LOG] |
| silence_timeout_s | `NEXUS_SILENCE_TIMEOUT_S` | number, 1–10 | ? |
| wake_phrase | `NEXUS_WAKE_PHRASE` | text, no newline/NUL, max_length; `""` = hands-free off | `hey nixi` [S `@8d60ddf`] |
| hud_rest | `NEXUS_HUD_REST` | flag ("idle dock") | ? |
| stt_backend | `NEXUS_STT_BACKEND` | `parakeet\|faster_whisper` | `parakeet` [S `@8bfc1e3`] |
| audio_device | `NEXUS_AUDIO_DEVICE` | mic name ("Microphone") | system default |
| history_days | `NEXUS_HISTORY_DAYS` | int, 0–3650 ("History retention") | ? |
| hud_character | `NEXUS_HUD_CHARACTER` | character id (`DEFAULT_CHARACTER` in app.mascot) | ? |
| hud_color | `NEXUS_HUD_COLOR` | `#RRGGBB` ("Notch colour") | `DEFAULT_NOTCH` (likely `#000000` [INF]) |
| hud_eyes | `NEXUS_HUD_EYES` | `#RRGGBB` ("Eye colour") | `DEFAULT_EYES` (likely `#FFFFFF` [INF]) |
| start_with_windows | `NEXUS_START_WITH_WINDOWS` | flag; mirrored to the HKCU Run key | ? |
| hud_hide_fullscreen | `NEXUS_HUD_HIDE_FULLSCREEN` | flag | ? |
| hud_outfit | `NEXUS_HUD_OUTFIT` | one of `OUTFIT_NAMES` (`headphones`, `shades`, `glasses`, plus a ≤5-char "none" [INF]) | ? |
| hud_seasonal | `NEXUS_HUD_SEASONAL` | flag | ? |
| hud_music | `NEXUS_HUD_MUSIC` | flag ("Show what's playing", on unless `0/off/false`) | on [S `@8be05e4`] |

Other client env knobs (not in the Settings UI) [S]:
- Hotkeys and keys: `NEXUS_PANEL_KEY` (default `f9` [LOG]).
- Sound: `NEXUS_CHIME`, `NEXUS_CHIME_VOLUME`.
- Session timing: `NEXUS_FOLLOWUP_S`, `NEXUS_WAKE_QUIET_S`, `NEXUS_MAX_UTTERANCE_S`, `NEXUS_MAX_SESSION_S`, `NEXUS_PARTIAL_MS` (700 ms per the docstring `@8d0b1f3`), `NEXUS_DICTATION_SILENCE_MS`.
- Typing: `NEXUS_WRITE_CHAR_MS`, `NEXUS_SPEECH_WORDS`.
- Wake detection: `NEXUS_WAKE_WORD`, `NEXUS_WAKE_THRESHOLD`, `NEXUS_WAKE_SIMILARITY`, `NEXUS_WAKE_DIAGNOSTICS`, `NEXUS_VAD_RMS_THRESHOLD`, `NEXUS_SILERO_VAD_MODEL`.
- HUD: `NEXUS_HUD_BLUR`, `NEXUS_HUD_DOCK`, `NEXUS_HUD_MASCOT`, `NEXUS_HUD_DISPLAY`, `NEXUS_HUD_SCALE`, `NEXUS_CUA_WINDOW`, `NEXUS_PROMPTER_IN_CAPTURE`.
- Startup and app: `NEXUS_SAFE_MODE`, `NEXUS_SKIP_ONBOARDING`, `NEXUS_SINGLETON_PORT`, `NEXUS_POLISH_TIMEOUT_S`.
- Logging: `NEXUS_CLIENT_LOG_MAX_BYTES`, `NEXUS_CLIENT_LOG_BACKUPS`.

The wake listener accepts mishearings of the phrase, e.g. `hey notch`, `hey nixie`, `hey nexi`, `hey nicky` and about 30 more [S `@8d60e03`..`@8d60f36`].

---

## 4. Paths, env vars, models, STT/TTS

### 4.1 `engine.nexusd.paths` [S `@8d172a8`..`@8d17bca`]

| Function | Override | Installed default |
|---|---|---|
| `data_dir()` | `NEXUS_DATA_DIR` | win32: `%LOCALAPPDATA%\heynixi`; darwin: `~/Library/Application Support/heynixi`; else `$XDG_DATA_HOME or ~/.local/share/heynixi`. A source checkout (detected by `pyproject.toml` + `nexus_app.py` + `engine/nexusd`) uses `PROJECT_ROOT/runtime` [INF]. |
| `config_dir()` | `NEXUS_CONFIG_DIR` | `<data_dir>/config` |
| `env_file()` | `NEXUS_ENV_PATH` | `<config_dir>/.env` |
| `database_path()` | `NEXUS_DB_PATH` | `<data_dir>/nexus.db` |
| `logs_dir()` | `NEXUS_LOG_DIR` | `<data_dir>/logs` |
| `sites_config_path()` | `NEXUS_SITES_PATH` | `<config_dir>/sites.json` |

Install-dir runtime layout [FS]. `_configure_bundled_assets` uses `setdefault` to point the loaders here [S `@8b5fe91`]:

```
runtime/llama/llama-server.exe (+ ggml-*.dll, ggml-vulkan.dll, mtmd.dll)   -> NEXUS_LLAMA_SERVER
runtime/models/llm/Qwen3.5-0.8B-Q4_K_M.gguf          (532,517,120 B)        -> NEXUS_LOCAL_GGUF / NEXUS_BUILTIN_GGUF
runtime/models/llm-vision/Qwen3.5-0.8B-mmproj-F16.gguf (204,987,232 B)      -> NEXUS_LOCAL_MMPROJ
runtime/models/huggingface/hub/models--istupakov--parakeet-tdt-0.6b-v3-onnx -> HF_HUB_CACHE
   (snapshots/*/config.json, vocab.txt, encoder-model.int8.onnx, decoder_joint-model.int8.onnx)
runtime/models/silero_vad.onnx                                              -> NEXUS_SILERO_VAD_MODEL
```

### 4.2 Engine env vars (complete list found in the app range)

| Area | Variables |
|---|---|
| Server | `NEXUS_PORT`, `NEXUS_API_URL`, `NEXUS_ALLOWED_ORIGINS`, `NEXUS_STATIC_DIR`, `NEXUS_OPEN_UI`, `NEXUS_UI_URL`, `NEXUS_UVICORN_LOG_LEVEL`, `NEXUS_MAX_AUDIO_MB`, `NEXUS_DISABLE_WMI_BYPASS` |
| Logging | `NEXUS_LOG_LEVEL`, `NEXUS_LOG_MAX_BYTES`, `NEXUS_LOG_BACKUPS`. Format: `%(asctime)s %(levelname)s [run=%(run_id)s convo=%(conversation_id)s] %(name)s: %(message)s` [S `@8d1472c`] |
| LLM | `NEXUS_LLM` (`auto`\|`small`\|`off`), `NEXUS_LLM_BACKEND` (`auto` default\|`off`\|`ollama` in a source checkout only), `NEXUS_OLLAMA_URL` (default `http://127.0.0.1:11434`, overridden to the bundled front), `NEXUS_FAST_MODEL` (source default `qwen3.5:2b` [S `@8cf3948`]), `NEXUS_SMART_MODEL`, `NEXUS_LLM_THINK`, `NEXUS_LLM_TIMEOUT_S`, `NEXUS_OLLAMA_KEEP_ALIVE`, `NEXUS_LLAMA_SERVER`, `NEXUS_LOCAL_GGUF`, `NEXUS_BUILTIN_GGUF`, `NEXUS_LOCAL_MMPROJ`, `NEXUS_PERSONA` |
| Orchestration | `NEXUS_TOOL_TIMEOUT_S`, `NEXUS_TOOL_PERMISSIONS`, `NEXUS_SESSION_IDLE_S`, `NEXUS_HISTORY_DAYS`, `NEXUS_SPEAK` (`all`\|`errors`; the default speaks only questions, failures and conversation) |
| STT | `NEXUS_STT_BACKEND`, `NEXUS_PARAKEET_MODEL`, `NEXUS_PARAKEET_QUANT`, `NEXUS_PARAKEET_PROVIDER`, `NEXUS_WHISPER_MODEL`, `NEXUS_WHISPER_DEVICE`, `NEXUS_WHISPER_COMPUTE`, `NEXUS_WHISPER_CPU_THREADS`, `NEXUS_WHISPER_VAD`, `NEXUS_VAD_RMS_THRESHOLD` |
| TTS | `NEXUS_TTS_BACKEND`, `NEXUS_TTS_VOICE`, `NEXUS_TTS_TIMEOUT_S`, `NEXUS_TTS_CMD` (legacy Piper) |
| Tools | `NEXUS_BROWSER`, `NEXUS_BROWSER_PROFILE`, `NEXUS_CHROME_PATH`, `NEXUS_CDP_PORT`, `NEXUS_SEARCH_ENGINE`, `NEXUS_SCREENSHOT_DIR`, `NEXUS_SCREEN_MAX_DIM`, `NEXUS_DEFAULT_DISPLAY` |

All of these are [S].

### 4.3 Bundled LLM (`core.bundled_llm`) [S `@8cee563`..`@8cf096c`]
- `configure()` runs once and picks the backend: `bundled` / `unavailable` / `off` / `ollama` (a source checkout only). An installed build never uses a user's Ollama or a `.env` URL.
- **llama-server spawn args** (observed tokens): `--host 127.0.0.1 --port <free port> -ngl <N> --jinja --no-webui [--mmproj <projector>]`, with `-m <gguf>` [INF, too short to see].
  - The process uses `CREATE_NO_WINDOW`; output goes to `<NEXUS_DATA_DIR>/nixi-llama-server.log`.
  - It is assigned to a kill-on-close Windows **Job Object**.
  - `_revive` restarts it at most every 10 s if it dies. [LOG] shows exit code 3221225477 (0xC0000005) followed by a restart.
- An **Ollama-compatible front** (`ThreadingHTTPServer` thread `nixi-llm-front` on `127.0.0.1:<random>`, 57923 in the log) translates between Ollama and OpenAI formats:

  | Front endpoint | Behaviour |
  |---|---|
  | `GET /api/tags`, `/api/ps` | list models; names come from `NEXUS_FAST_MODEL` / `NEXUS_SMART_MODEL`, which are set to `LOCAL_MODEL="nixi-local"`; `details.family="qwen35"` |
  | `GET /api/version` | `nixi-bundled` |
  | `GET /health` | `ready` / `loading` / `error` |
  | `POST /api/show` | `capabilities` includes `completion` and `vision` |
  | `POST /api/chat` | forwarded to llama-server `/v1/chat/completions`; streams as `application/x-ndjson` chunked |

  Option mapping in `to_openai`:
  - `format` (schema) becomes `response_format: {type: json_schema}`, or `json_object`;
  - `think` becomes `chat_template_kwargs.enable_thinking`;
  - `num_predict` becomes `max_tokens`;
  - `temperature`, `top_p`, `top_k`, `repeat_penalty` and `tools` pass through;
  - images become `image_url data:image/png;base64,…`.

  Front error messages: 503 "The built-in model is still loading." and "This model can't see images…".
- `core.llm` makes FAST/SMART calls with routing by request type (composition regex `@8cf3b96`). It falls back from SMART to FAST and remembers CPU placement on GPU OOM. `warm_models()` runs at startup.

### 4.4 Model catalog (`core.model_catalog`) [S `@8cf4ed7`..`@8cf5446`]

- **Download URL template:** `https://huggingface.co/unsloth/{repo}/resolve/main/{file}`.
- **Download process:** the file is written to `.part` and checked against the SHA-256 pin. A mismatch fails with "download was corrupted (checksum mismatch)". A disk check requires the size plus 2 GB headroom.
- **Selection:** stored in `<data_dir>/models/selected.json` (`selected_id`).
- **Hardware detection:** reads GPUs from the registry class `{4d36e968-…}`, using `HardwareInformation.qwMemorySize`. Integrated and virtual adapters are filtered out by regex. CPU and RAM come from the registry and psutil, never WMI.
- **Rating:** each model is rated `fast` / `won't fit` etc. with `tokens_per_s` and `reply_seconds`, from a bandwidth-class estimate.

| id | label | repo / file | sha256 | notes |
|---|---|---|---|---|
| `qwen3.5-0.8b` (BUILT_IN) | Qwen3.5 0.8B (built in) | Qwen3.5-0.8B-GGUF / Qwen3.5-0.8B-Q4_K_M.gguf | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` | Ships with app; quick drafts/polish; on-screen actions on simple pages (bytes: 532,517,120 [FS]) |
| `qwen3.5-2b` | Qwen3.5 2B | Qwen3.5-2B-GGUF / Qwen3.5-2B-Q4_K_M.gguf | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` | Recommended upgrade: 10/10 on the hard on-screen suite, better writing |
| `qwen3.5-4b` | Qwen3.5 4B | Qwen3.5-4B-GGUF / Qwen3.5-4B-Q4_K_M.gguf | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` | Stronger writing/reasoning for 6 GB+ GPUs |
| `qwen3.5-9b` | Qwen3.5 9B | Qwen3.5-9B-GGUF / Qwen3.5-9B-Q4_K_M.gguf | `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8` | High quality for 10 GB+ GPUs |
| `qwen3.5-27b` | Qwen3.5 27B (Power) | Qwen3.5-27B-GGUF / Qwen3.5-27B-Q4_K_M.gguf | `84b5f7f112156d63836a01a69dc3f11a6ba63b10a23b8ca7a7efaf52d5a2d806` | Power tier for 24 GB+ (RTX 4090/5090) |

Entry fields: `label, repo, file, bytes, sha256, params_b, verified, notes`. The `bytes` and `params_b` numbers are not recoverable except for the built-in file. The VRAM/RAM need (`need_gb`) is computed from bytes, not stored. The vision projector applies only to the built-in model.

### 4.5 STT (`core.stt` facade, singleton, double-checked lock)

- **Backends:** `parakeet` (default) and `faster_whisper`. `whispercpp` is remapped to faster_whisper. The retired cloud backend `elevenlabs` is read as parakeet.
- **Partials are always transcribed locally** (`STTEngine.local()`) [S `@8d0b00a`].
- **parakeet:** uses onnx-asr with model `nemo-parakeet-tdt-0.6b-v3`, quant `int8`, on `CPUExecutionProvider`.
  - Override with `NEXUS_PARAKEET_PROVIDER`.
  - ORT session options: `session.intra_op.allow_spinning` / `inter_op` set, and the CPU memory arena is disabled.
  - Expects 16 kHz mono 16-bit PCM.
  - [LOG] "Loading Parakeet nemo-parakeet-tdt-0.6b-v3 (int8) on ['CPUExecutionProvider']".
- **faster_whisper:**
  - Model resolution: `NEXUS_WHISPER_MODEL`, else local `runtime/models/whisper/faster-whisper-{small,base,tiny}`, else download. Known names: large-v3-turbo, distil-large-v3, medium, small, base, tiny, tiny.en.
  - Device: `NEXUS_WHISPER_DEVICE` (`auto`, which probes CUDA safely; `cpu`; `cuda`).
  - Compute: `NEXUS_WHISPER_COMPUTE` (`int8` default; `float16` on cuda).
  - VAD: `NEXUS_WHISPER_VAD` (vad_filter).
  - RMS gate: `NEXUS_VAD_RMS_THRESHOLD`, default 150 on the 0–32767 scale, measured over the loudest 0.5 s window.
  - Decode options: `language`, `beam_size`, and hotwords from `core.vocabulary`.
  - Audio is decoded with PyAV directly.
- **Artefact filter** (`core.transcript_filter`): drops hallucinations such as "thanks for watching", lone `okay.`/`ding.`/`beep.`, bracketed `[..]`, and repetition loops [S `@8d0f4d2`].

### 4.6 TTS (`core.tts` facade -> WAV bytes)

- **windows** (default): `WindowsSpeechTTS` runs `powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand <utf-16le b64>`. The script uses `System.Speech` `SpeechSynthesizer` and takes a JSON request `{operation: probe|synthesize, voice, text}`.
  - `probe` returns `{available, voices}`.
  - `synthesize` writes WAV to stdout.
  - Voice: `NEXUS_TTS_VOICE`, falling back to the system default. Timeout: `NEXUS_TTS_TIMEOUT_S`.
  - Script at [S `@8d115a7`..`@8d11a49`].
- **piper** (legacy, deprecated): `piper.exe --model voice.onnx --output-raw --sentence-silence …`. Text goes in on stdin and raw PCM comes out. Auto-detected under `runtime/`, or via `NEXUS_TTS_CMD`. A stale Kokoro setting migrates to windows.

---

## 5. MCP server (`heynixi.exe --mcp`, `engine.nexusd.mcp_server`) [S `@8d160d5`..`@8d1728b`]

- **Transport:** stdio, newline-delimited JSON-RPC 2.0. The server reopens inherited std handles via `GetStdHandle`/`open_osfhandle` because the GUI-subsystem exe may start with `sys.stdin=None`.
- **Protocol version:** `2025-06-18`.
- **`initialize` result:** `{protocolVersion, capabilities:{tools:{listChanged:false}}, serverInfo:{name:"heynixi", version}, instructions:"Local tasks, notes, habits, reminders and focus timer from the user's heynixi app; use notify to show a short message on their pill."}`.
- **Methods:** `initialize`, `tools/list`, `tools/call`; anything else returns "Method not found:". A bad line returns "Parse error".
- **Forwarding:** calls go to `http://127.0.0.1:<port>`. The port comes from `<data_dir>/engine.port`, falling back to `NEXUS_PORT`. Requests are `POST /v1/integrations/tool {name, args}` (`Content-Type: application/json`) or `/v1/integrations/notify`.
- **Results:** `{content:[{type:"text",text}], isError}`. If the engine is down: "heynixi isn't running. Start the app and try again."; other failures: "heynixi error: …".
- **Registration snippets:**
  - Claude Code: `claude mcp add heynixi -- "%LOCALAPPDATA%\Programs\heynixi\heynixi.exe" --mcp`
  - Codex (`~/.codex/config.toml`): `[mcp_servers.heynixi] command=... args=["--mcp"]`

Tools. `inputSchema` is `{type:"object", properties, required}`. Arg names of 5 characters or fewer are [INF].

| MCP tool | Engine tool | Description (verbatim) | Args |
|---|---|---|---|
| `add_task` | task.add | Add an item to the user's to-do list. | `text`: string, required [INF] |
| `list_tasks` | task.list | List the user's open to-do items, numbered. | — |
| `complete_task` | task.done | Mark a to-do item done, by its number or words. | `text`: string, required [INF] |
| `add_note` | note.add | Save a quick note for the user. | `text`: string, required [INF] |
| `search_notes` | note.list | Read the user's recent notes, optionally filtered by words. | `query`: string, optional [S] |
| `log_habit` | habit.log | Check in a habit for today (e.g. workout, reading). | `habit`: string, required [S] |
| `habit_status` | habit.status | Habit streaks and this week's counts. | — |
| `add_reminder` | reminder.add | Set a reminder. Include the time in the text, e.g. 'in 20 minutes to stretch' or 'at 6pm to call Sam'; it pops up on the user's pill when due. | `text`: string, required [INF] |
| `list_reminders` | reminder.list | List saved reminders. | — |
| `start_focus` | focus.start | Start a focus (pomodoro) timer. | `minutes`: integer [S] |
| `focus_status` | focus.status | Time left in the focus session. | — |
| `notify` | (notify endpoint) | Show a short message on the user's heynixi pill (e.g. 'Build finished'). | `text` (required [INF]), `title` ("Shown on the pill.") [S] |

`focus.stop` and `task.clear_done` are allow-listed on `/v1/integrations/tool` but not exposed as MCP tools.

---

## 6. Security (`engine.nexusd.security`) [S `@8d1ab1c`..`@8d1b935`]

**There is no auth token or header** between the app and the engine. No `Authorization`, `Bearer` or custom `X-*` auth strings exist in the app range. The trust model is "loopback plus native client":

1. **Bind:** the server listens on `127.0.0.1` only.
2. **`BrowserRequestGuard`** (ASGI middleware). A request "looks like a browser" when it has any `sec-fetch-*` header or a `User-Agent` starting with `Mozilla/`. Native clients send neither and pass through. A browser request is checked in order:
   - The **Host header** must be loopback (`localhost`, `127.0.0.1`, `[::1]`). This defeats DNS rebinding. Otherwise the JSON response is `Untrusted host`; a websocket is closed instead.
   - If `Sec-Fetch-Site` is `cross-site`, or the `Origin` is not trusted, the response is `Untrusted browser origin`. The status codes are not recoverable (403/400 [INF]).
3. **Trusted origins:** `trusted_browser_origins(ports)` returns `http://localhost:<p>`, `http://127.0.0.1:<p>` and `http://[::1]:<p>` for the engine and UI ports, plus entries from `NEXUS_ALLOWED_ORIGINS` (comma-separated). Those entries are passed through `_loopback_origin`, which rejects non-loopback hosts, userinfo, paths, queries and fragments. The same list feeds `CORSMiddleware`.
4. **WebSocket `/v1/events`:** `browser_origin_is_trusted(origin)`. A missing Origin is treated as a native client and allowed. An untrusted Origin causes close code 1008. Rationale from the docstring: "CORS does not apply to WebSocket handshakes … prevents an arbitrary web page from subscribing to local speech and action events."
5. **Integrations surface:** limited to the allow-list; nothing there can type, click or open things.

For hark: either replicate this guard, or add a per-launch random token written next to `engine.port`. Adding a token would be strictly stronger, because any local process can currently call the API.

---

## 7. Open questions

1. Numeric defaults that cannot be recovered: `silence_timeout_s`, `history_days`, `NEXUS_SESSION_IDLE_S`, `NEXUS_MAX_AUDIO_MB`, `-ngl` value / context size (`-c`), event-queue `maxsize`, WS keepalive timeout, `REQUEST_TIMEOUT_S`, catalog `bytes`/`params_b`. Running the app with `/v1/config` and `/v1/models/recommend` would answer most of these.
2. Exact short field names (`text`, `kind`, `tool`, `id`, `mode`, `name`, `args`) and the third `WriteRequest` field. A one-off `GET /openapi.json` on the running engine (FastAPI default, unless disabled) would give the full schema.
3. HTTP verbs are inferred. Confirm them via `/openapi.json` too.
4. Whether `/v1/events` sends a keepalive/ping on its `wait_for` timeout, or a hello message on connect.
5. `/v1/chat/stream` SSE payload shape (`assistant.delta` fields, and whether a terminal event exists). The desktop client does not use it.
6. Whether `runs` is in `_USER_DATA_TABLES` (the name is too short to see), and whether productivity tables are really excluded from export/clear.
7. Default `DEFAULT_CHARACTER`, the full `OUTFIT_NAMES`, and the palette defaults. These belong to UI scope.
8. Smart model default in a source checkout (probably `qwen3.5:4b`). In the bundled build both FAST and SMART are `nixi-local`.
