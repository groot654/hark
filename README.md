# Hark

A private voice assistant for Windows. Hold a key, speak, and Hark runs the command, types your dictation into the
app in front, or answers. Speech recognition runs on your PC; nothing is sent to the cloud.

## Features

- **Hands-free**: say "Hey Hark, open Spotify", or "Hey Hark", a pause, then the request. Off by default;
  turn it on from the tray or Settings. Speech not addressed to Hark is dropped without being kept.
- **Voice commands**: open and close apps and websites, web search, volume and media keys, keyboard shortcuts,
  window control, lock/shutdown (with confirmation), battery and system stats.
- **Dictation** into any app, in three styles (exact, clean, polished), with spoken punctuation ("comma",
  "new paragraph"), lists ("bullet", "number one"), corrections ("scratch that", "make that"), a personal
  dictionary and snippets. Chat apps get a casual style and code editors stay literal.
- **Productivity**: to-dos, notes, reminders and timers, habits with streaks, focus sessions, routines,
  a daily briefing.
- **Memory**: "remember that…" facts used in later conversations.
- **AI features**, from a built-in model that runs on your PC: chat, writing ("write a reply saying…"),
  rewriting the selected text, polished dictation, multi-step "take care of this…" requests, and understanding
  commands phrased in ways the grammar doesn't cover. Questions about you ("what's my name?") are answered
  straight from what you've asked Hark to remember.
- **Notch HUD**: a small bar with animated eyes at the top of the screen that shows listening, thinking and results.
  The eyes react (heart eyes when thanked, a happy squint when something's done, a puzzled look when not), and
  a running focus session shows as a countdown.
- **Teleprompter**: copy a script and say "start teleprompter". It scrolls just below the notch while you speak,
  holds when you pause, and is hidden from screen recording and sharing. Click to pause, scroll to nudge, Esc to close.

## Requirements

- Windows 10/11, Python 3.12, [uv](https://docs.astral.sh/uv/)

## Run

```sh
uv sync
uv run hark            # notch + engine
uv run hark --engine   # engine only, no UI
```

The first launch downloads, into `%LOCALAPPDATA%\hark\models`:

- the Parakeet speech model (~640 MB)
- llama.cpp's `llama-server` (b11402, Vulkan build) and the Qwen3.5-0.8B model (Q4_K_M, ~570 MB together),
  both checked against pinned SHA-256 hashes

Commands work while the downloads run. To use [Ollama](https://ollama.com) or another OpenAI-compatible server
instead, pick "Ollama or another server" under Settings → Privacy & AI, or run `uv run hark --llm external`;
`--llm off` runs without a model.

| Key | Action |
| --- | --- |
| Hold Right Ctrl | Command |
| Hold Right Alt | Dictation |
| F9 | Panel |

## Layout

- `src/hark/app` – PySide6 client: notch HUD, hotkeys, microphone, voice-activity detection, text insertion, settings
- `src/hark/engine` – local FastAPI engine (127.0.0.1, per-launch token): speech-to-text, command grammar,
  orchestrator, tools, SQLite store, reminders
- `docs/re` – reference notes used while designing the behaviour

## Tests

```sh
uv run pytest
```
