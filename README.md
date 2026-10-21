# Hark

A private voice assistant for Windows. Hold a key, speak, and Hark runs the command, types your dictation into the
app in front, or answers. Speech recognition runs on your PC; nothing is sent to the cloud.

## Features

- **Voice commands**: open and close apps and websites, web search, volume and media keys, keyboard shortcuts,
  window control, lock/shutdown (with confirmation), battery and system stats.
- **Dictation** into any app, in three styles (exact, clean, polished), with spoken punctuation ("comma",
  "new paragraph"), lists ("bullet", "number one"), corrections ("scratch that", "make that"), a personal
  dictionary and snippets. Chat apps get a casual style and code editors stay literal.
- **Productivity**: to-dos, notes, reminders and timers, habits with streaks, focus sessions, routines,
  a daily briefing.
- **Memory**: "remember that…" facts used in later conversations.
- **AI features** (need a local model): chat, writing ("write a reply saying…"), rewriting the selected text,
  multi-step "take care of this…" requests.
- **Notch HUD**: a small bar with animated eyes at the top of the screen that shows listening, thinking and results.

## Requirements

- Windows 10/11, Python 3.12, [uv](https://docs.astral.sh/uv/)
- Optional: [Ollama](https://ollama.com) with a small model (e.g. Qwen) for the AI features

## Run

```sh
uv sync
uv run hark            # notch + engine
uv run hark --engine   # engine only, no UI
```

The first launch downloads the Parakeet speech model (~640 MB) to `%LOCALAPPDATA%\hark\models`.

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
