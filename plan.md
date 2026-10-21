# Togo roadmap

Working order: top to bottom. Each item is built, tested (automated tests plus a check in the real app),
committed and pushed before the next one starts. Defaults marked **(default)** are what gets built unless
you say otherwise; anything that installs software on this PC or costs money is asked first.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

## Done so far

- Engine, speech recognition (Parakeet), speech gate (Silero VAD), hotkeys, tray, settings window
- Voice commands, dictation (three styles), productivity tools, memory, daily briefing
- Built-in AI model (llama.cpp + Qwen3.5-0.8B): chat, writing, rewriting, polished dictation, multi-step requests
- Notch: eye reactions, focus countdown, voice-paced teleprompter
- 211 automated tests; private repo at https://github.com/groot654/togo

---

## 1. Only one Togo at a time `[x]` (small)

**Result.** Done. A second launch exits in about 0.6 s and the running Togo shows "Togo is already
running." Checked with a separate test copy; 216 tests pass. The lock is per data folder, so test copies
with their own `TOGO_DATA_DIR` don't collide with the real one.

**Problem.** Launching Togo twice gives two notches on top of each other, and both answer every hotkey.

**Plan.**
- A Windows named mutex (`Local\Togo.SingleInstance`) is taken at startup, before the engine, hotkeys or
  microphone start.
- If it's already held, the new launch asks the running Togo (through its engine, using the saved port and
  token) to show "Togo is already running" in its notch, then exits.
- `togo --engine` (headless) and `togo --mcp` (item 4) are exempt: they don't own hotkeys or a notch.

**Tests.** Unit test for the lock; a real check that launches Togo twice and confirms one notch, one set of
processes, and the message on the first one.

## 2. "Hey Togo" wake phrase `[x]` (large)

**Result.** Done. Turn it on from the tray ("Listen for “Hey Togo”") or Settings.
- Recogniser test (3 Windows voices × 3 speeds, light noise): "Hey Togo" found in 50/54 bursts,
  look-alikes ("Hey Mark", "Hey Park ranger", "I parked", "Togo the herald", "heart rate") rejected 63/63.
  Short phrases are padded with silence before transcribing, which lifted short noisy clips from 63/72 to 71/72.
- In the real app with recorded speech: one breath, a 1 s pause, a 2.5 s pause, the phrase alone (cancels
  after 5 s) and "Hey Mark" (ignored) all behave correctly. About 1 s from end of speech to action.
- Known limit: fast or slurred speech is sometimes heard as "Hey Mark", which can't be accepted without
  triggering on the name Mark.
- This laptop is often in battery saver mode, where hands-free listening rests (Togo now says so once).
  If you'd rather it kept listening, that can become a setting.
- Hands-free does nothing while the PC is locked (checked against the real lock screen). Still to confirm
  once you're back: that it resumes after you unlock.
- Still needed: a try with your own voice and accent.

**Goal.** Say "Hey Togo, open Spotify" without touching a key. Off by default; turned on in Settings.

**Plan.** The same approach heynixi uses, not a separate keyword model:
- While idle, the open microphone runs through the speech gate. A burst of speech (up to ~9 s, with ~0.45 s
  of audio kept from just before it started) is transcribed by Parakeet.
- The opening words are fuzzy-matched against "hey togo" and its common mishearings (hey hawk, hey hack,
  a togo, hey arc…, to be tuned with real recordings). Leading fillers ("um", "okay", "so") are skipped.
- Anything after the phrase is run as the command. The phrase alone opens a normal listening session
  that ends when you stop talking.
- Pauses while push-to-talk, dictation or the teleprompter is using the microphone, and while Windows
  battery saver is on.
- Why not openWakeWord: its ready-made models are licensed non-commercially (CC BY-NC-SA), and training a
  custom "hey togo" model needs hours of GPU time.

**Cost.** Transcribing only happens when speech is heard, but in a busy room (calls, TV) it uses noticeably
more CPU; Settings will say so.

**Tests.** Matcher unit tests (aliases, fillers, near-misses that must *not* trigger such as "hey Mark");
end-to-end with recorded Windows voices; then your own voice, which I can't test.

**Decision.** Wake phrase stays "Hey Togo" **(default)**. A two-syllable name triggers by accident less
often; we can revisit after real use.

## 3. Clicking things on screen `[x]` (medium)

**Result.** Done. "Click send", "press the save button", "select the bold tab", "open the File menu",
"point at the search box", "where's the send button?".
- Real check on Calculator: "click 7", "click plus", "press the three button", "click equals" gave
  "Display is 10"; each click took 0.03–0.16 s and the highlight ring lands exactly on the control at
  this PC's 125% scaling.
- "Press …" stays a key press when every word is a key name ("press control s", "press enter").
- An unclear match ("click later" → "Send later") asks first; a missing one says so; Togo never clicks
  in its own windows. A general "ask before acting" hook was added for tools.

**Goal.** "Click the send button", "press Save", "open the File menu", "where's the search box?"

**Plan.**
- Windows UI Automation (already installed via `comtypes`) reads the controls of the window in front:
  buttons, links, menu items, tabs, checkboxes, list items, edit boxes. The search is bounded (depth,
  element count, ~1.5 s) so a huge page can't freeze Togo.
- Spoken names are fuzzy-matched against control names. The best match is invoked through its UI
  Automation pattern (Invoke / Toggle / Select / Expand), falling back to a mouse click at its centre.
- A short highlight ring shows what's being clicked. "Where's X?" only shows the ring.
- Safety **(default)**: an exact single match is clicked straight away; an unclear match or several
  candidates get a "Click 'Send message'?" confirmation; Togo never clicks inside its own windows.

**Tests.** Grammar and matcher unit tests; a real check against Notepad and Calculator (open, click
buttons, verify the result), done with your apps closed or untouched.

## 4. MCP mode `[x]` (small–medium)

**Result.** Done. `togo --mcp` (official MCP Python SDK 2.3) exposes 13 tools: add/list/complete to-dos,
add/search notes, log habit and streak, add/list reminders, start/stop/status of the focus timer, and a
notch message. A real round trip with the SDK's client (protocol 2025-11-25) added and listed to-dos,
started a focus timer, set a reminder and showed a message; with Togo not running, tools answer "Togo isn't
running. Start it and try again." A focus timer started this way also shows its countdown in the notch.
Setup lines for Claude Code and Claude Desktop are in the README. Not registered in your own Claude
config; say if you'd like that done.

**Goal.** Let Claude Code, Claude Desktop and other MCP clients use Togo: add to-dos and notes, set
reminders, log habits, start a focus timer, show a message on the notch ("Build finished").

**Plan.**
- `togo --mcp` runs a stdio MCP server using the official Python SDK (`mcp`, MIT licence).
- It forwards calls to the running Togo through a new allow-listed engine endpoint,
  `/v1/integrations/tool`. Only safe tools are exposed: nothing that types, clicks, opens apps or deletes.
- If Togo isn't running, tools answer "Togo isn't running. Start it and try again."
- README gets the setup lines, e.g. `claude mcp add togo -- "<path>\togo.exe" --mcp`.

**Tests.** Allow-list and endpoint tests; a real round trip with an MCP client (list tools, add a to-do,
see it in Togo).

## 5. The bigger panel `[x]` (large)

**Result.** Done. F9, a click on the resting notch, or a left-click on the tray icon opens the panel.
- **Chat**: type commands or questions; replies, confirmations ("yes"/"no") and actions work as with voice;
  text Togo writes goes into the app you were in.
- **History**: every exchange is now kept (not dictation, not background speech) and grouped into
  conversations (a new one after 10 minutes of quiet, or "＋ New"); pick one to read and continue it. The
  "keep history for N days" setting is now applied at startup (0 keeps it forever).
- **System Check** (tray): microphone, hotkeys, hands-free, speech model, AI model, disk space, memory, each
  with a fix when something's wrong. On this PC it flags memory: about 0.7 GB free when checked.
- Checked in the real app: typed commands, a typed "no" to a confirmation, history, new and reopened
  conversations; on the real screen the panel takes keyboard focus straight away.

**Goal.** F9 (or a click on the notch) opens a drawer under the notch, as in heynixi:
- **Chat** tab: type a question or command ("Ask Togo…") and see the conversation.
- **History** tab: past conversations with times ("5m", "yesterday"…); open one or start a new one.
- **System Check** (tray menu): microphone, hotkeys, speech model, AI model, disk space, each with
  a plain fix when something is wrong.

**Plan.** New engine endpoints for conversation history; the drawer (520×400) takes keyboard focus only
while open and closes with Esc or a click outside; System Check is a separate small window.

**Tests.** Endpoint tests; offscreen renders of every panel state; a real check typing a command.

## 6. Start at sign-in, and an installer `[x]` (medium)

**Result.** Done. `dist\TogoSetup-0.1.0.exe` (80 MB) installs per user with no admin prompt, adds Start-menu
entries and (optionally) start at sign-in. Tested end to end with a silent install: the installed Togo runs,
answers commands, and the uninstaller stops it, removes the program, the shortcut and the sign-in entry, and
keeps your data. Bugs found by these tests and fixed:
- The first uninstaller stopped *every* process named Togo.exe, which also stopped the Togo you run from
  source. It now stops only the copy in its own folder.
- Togo started at sign-in (pythonw, no console) quit at once: the web server's logging setup fails without
  stderr. It now uses Togo's own logging.
- Code signing is still not done (a paid certificate); Windows SmartScreen will warn on first install.

**Earlier notes.**
- Done: Settings → General → "Start Togo when I sign in" (off by default; not switched on for you).
- Done: `packaging\build.ps1` builds `dist\Togo` (244 MB): `Togo.exe` (no console) and `togo-mcp.exe`
  (console, for MCP clients). The built app was tested as a separate copy: speech model and built-in AI
  model start (it copies the C++ runtime next to llama-server itself), it answered a question,
  `togo-mcp.exe` listed its 13 tools and added a to-do, and UI Automation found Calculator's buttons.
- Waiting on you: Inno Setup isn't installed on this PC. With your OK I'll run
  `winget install JRSoftware.InnoSetup` (a per-user install, about 7 MB), build `TogoSetup.exe`
  from `packaging\togo.iss`, then install, launch, check autostart and uninstall it to test.

**Plan.**
- Settings gets "Start Togo when I sign in" (a per-user `Run` registry entry, no admin rights).
- Installer **(default)**: PyInstaller builds the app folder; Inno Setup wraps it into a per-user
  `TogoSetup.exe` that installs to `%LOCALAPPDATA%\Programs\Togo` with a Start-menu shortcut and an
  uninstaller. Models are still downloaded on first run, which keeps the installer small (~250 MB).
- Before building: **I'll ask before installing Inno Setup** (via `winget`) on this PC.
- Not included: code signing. Without a certificate (paid, roughly $200–400/year) Windows SmartScreen
  shows a warning on first install. Your call later.

**Tests.** Install on this PC, launch from the Start menu, check autostart after sign-in, uninstall
cleanly (your data in `%LOCALAPPDATA%\togo` is kept unless you choose to remove it).

## 7. Choosing a larger AI model `[x]` (small)

**Result.** Done: Settings → Privacy & AI → Built-in model size (or `togo --model medium`). Scored on the
same 23 cases (commands the grammar doesn't catch, factual questions, writing, rewriting, multi-step plans,
polished dictation), all tools stubbed, on this PC:

| Size | Score | Median reply | Slowest | Notes |
|---|---|---|---|---|
| Small (0.8B) | 18/23 | 0.39 s | 1.0 s | says Sydney is Australia's capital; plans are just a focus timer |
| Medium (2B) | 20/23 | 0.69 s | 2.2 s | all commands and questions right; plans sensible but over-eager (adds a focus timer) |
| Large (4B) | 21/23 (22 in substance: "That is sixty" was marked wrong) | 1.30 s | 4.0 s | the only one that fixes "Me and him goes…" grammar; needs ~3.5 GB free |

Recommendation: **Medium** for this PC. It fixes the wrong answers and weak commands at under a second,
and fits in the 1–3 GB of memory usually free here. Large is best when memory allows. The default stays
Small (fastest, smallest download) until you choose. The Medium and Large files (1.3 GB + 2.7 GB) were
downloaded for this test and are in `%LOCALAPPDATA%\togo\models\llm`; delete whichever you won't use.

**Plan.** Settings → AI model size:

| Option | File | Size | Notes |
|---|---|---|---|
| Small (default) | Qwen3.5-0.8B Q4_K_M | 0.53 GB | current; fastest |
| Medium | Qwen3.5-2B Q4_K_M | 1.28 GB | better writing and planning |
| Large | Qwen3.5-4B Q4_K_M | 2.74 GB | best; needs ~3.5 GB free memory |

- Each file pinned by SHA-256 and downloaded only when chosen, with progress in the notch.
- Before switching, Togo checks free memory and warns. This PC has 17 GB, but only about 1 GB was free
  when checked, so Large may need other apps closed.
- The AI evaluation (commands, chat, writing, rewriting, planning) is re-run on each size and the results
  written here, so the choice is based on evidence.

---

## Loose ends to check along the way

- Replies spoken aloud: there's a "tts/enabled" setting, but nothing uses it yet. Not built; say if you
  want it (Windows' own voices would do, no download).
- "What's playing?": checked. It reads the current media session (it picked up a video playing in Chrome
  with title, channel and position) and shows a plain text card. heynixi's richer card with artwork and
  play/pause/next buttons would be a separate feature.
- Teleprompter pace (155 words a minute) and the eye reactions need a try with your real voice.
- Found while testing and fixed: hands-free now ignores speech while the PC is locked; the panel is fully
  opaque; "Privacy & AI" tab name.
