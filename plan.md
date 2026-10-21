# Hark roadmap

Working order: top to bottom. Each item is built, tested (automated tests plus a check in the real app),
committed and pushed before the next one starts. Defaults marked **(default)** are what gets built unless
you say otherwise; anything that installs software on this PC or costs money is asked first.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

## Done so far

- Engine, speech recognition (Parakeet), speech gate (Silero VAD), hotkeys, tray, settings window
- Voice commands, dictation (three styles), productivity tools, memory, daily briefing
- Built-in AI model (llama.cpp + Qwen3.5-0.8B): chat, writing, rewriting, polished dictation, multi-step requests
- Notch: eye reactions, focus countdown, voice-paced teleprompter
- 211 automated tests; private repo at https://github.com/groot654/hark

---

## 1. Only one Hark at a time `[x]` (small)

**Result.** Done. A second launch exits in about 0.6 s and the running Hark shows "Hark is already
running." Checked with a separate test copy; 216 tests pass. The lock is per data folder, so test copies
with their own `HARK_DATA_DIR` don't collide with the real one.

**Problem.** Launching Hark twice gives two notches on top of each other, and both answer every hotkey.

**Plan.**
- A Windows named mutex (`Local\Hark.SingleInstance`) is taken at startup, before the engine, hotkeys or
  microphone start.
- If it's already held, the new launch asks the running Hark (through its engine, using the saved port and
  token) to show "Hark is already running" in its notch, then exits.
- `hark --engine` (headless) and `hark --mcp` (item 4) are exempt: they don't own hotkeys or a notch.

**Tests.** Unit test for the lock; a real check that launches Hark twice and confirms one notch, one set of
processes, and the message on the first one.

## 2. "Hey Hark" wake phrase `[ ]` (large)

**Goal.** Say "Hey Hark, open Spotify" without touching a key. Off by default; turned on in Settings.

**Plan.** The same approach heynixi uses, not a separate keyword model:
- While idle, the open microphone runs through the speech gate. A burst of speech (up to ~9 s, with ~0.45 s
  of audio kept from just before it started) is transcribed by Parakeet.
- The opening words are fuzzy-matched against "hey hark" and its common mishearings (hey hawk, hey hack,
  a hark, hey arc…, to be tuned with real recordings). Leading fillers ("um", "okay", "so") are skipped.
- Anything after the phrase is run as the command. The phrase alone opens a normal listening session
  that ends when you stop talking.
- Pauses while push-to-talk, dictation or the teleprompter is using the microphone, and while Windows
  battery saver is on.
- Why not openWakeWord: its ready-made models are licensed non-commercially (CC BY-NC-SA), and training a
  custom "hey hark" model needs hours of GPU time.

**Cost.** Transcribing only happens when speech is heard, but in a busy room (calls, TV) it uses noticeably
more CPU; Settings will say so.

**Tests.** Matcher unit tests (aliases, fillers, near-misses that must *not* trigger such as "hey Mark");
end-to-end with recorded Windows voices; then your own voice, which I can't test.

**Decision.** Wake phrase stays "Hey Hark" **(default)**. A two-syllable name triggers by accident less
often; we can revisit after real use.

## 3. Clicking things on screen `[ ]` (medium)

**Goal.** "Click the send button", "press Save", "open the File menu", "where's the search box?"

**Plan.**
- Windows UI Automation (already installed via `comtypes`) reads the controls of the window in front:
  buttons, links, menu items, tabs, checkboxes, list items, edit boxes. The search is bounded (depth,
  element count, ~1.5 s) so a huge page can't freeze Hark.
- Spoken names are fuzzy-matched against control names. The best match is invoked through its UI
  Automation pattern (Invoke / Toggle / Select / Expand), falling back to a mouse click at its centre.
- A short highlight ring shows what's being clicked. "Where's X?" only shows the ring.
- Safety **(default)**: an exact single match is clicked straight away; an unclear match or several
  candidates get a "Click 'Send message'?" confirmation; Hark never clicks inside its own windows.

**Tests.** Grammar and matcher unit tests; a real check against Notepad and Calculator (open, click
buttons, verify the result), done with your apps closed or untouched.

## 4. MCP mode `[ ]` (small–medium)

**Goal.** Let Claude Code, Claude Desktop and other MCP clients use Hark: add to-dos and notes, set
reminders, log habits, start a focus timer, show a message on the notch ("Build finished").

**Plan.**
- `hark --mcp` runs a stdio MCP server using the official Python SDK (`mcp`, MIT licence).
- It forwards calls to the running Hark through a new allow-listed engine endpoint,
  `/v1/integrations/tool`. Only safe tools are exposed: nothing that types, clicks, opens apps or deletes.
- If Hark isn't running, tools answer "Hark isn't running. Start it and try again."
- README gets the setup lines, e.g. `claude mcp add hark -- "<path>\hark.exe" --mcp`.

**Tests.** Allow-list and endpoint tests; a real round trip with an MCP client (list tools, add a to-do,
see it in Hark).

## 5. The bigger panel `[ ]` (large)

**Goal.** F9 (or a click on the notch) opens a drawer under the notch, as in heynixi:
- **Chat** tab: type a question or command ("Ask Hark…") and see the conversation.
- **History** tab: past conversations with times ("5m", "yesterday"…); open one or start a new one.
- **System Check** (tray menu): microphone, hotkeys, speech model, AI model, disk space, each with
  a plain fix when something is wrong.

**Plan.** New engine endpoints for conversation history; the drawer (520×400) takes keyboard focus only
while open and closes with Esc or a click outside; System Check is a separate small window.

**Tests.** Endpoint tests; offscreen renders of every panel state; a real check typing a command.

## 6. Start at sign-in, and an installer `[ ]` (medium)

**Plan.**
- Settings gets "Start Hark when I sign in" (a per-user `Run` registry entry, no admin rights).
- Installer **(default)**: PyInstaller builds the app folder; Inno Setup wraps it into a per-user
  `HarkSetup.exe` that installs to `%LOCALAPPDATA%\Programs\Hark` with a Start-menu shortcut and an
  uninstaller. Models are still downloaded on first run, which keeps the installer small (~250 MB).
- Before building: **I'll ask before installing Inno Setup** (via `winget`) on this PC.
- Not included: code signing. Without a certificate (paid, roughly $200–400/year) Windows SmartScreen
  shows a warning on first install. Your call later.

**Tests.** Install on this PC, launch from the Start menu, check autostart after sign-in, uninstall
cleanly (your data in `%LOCALAPPDATA%\hark` is kept unless you choose to remove it).

## 7. Choosing a larger AI model `[ ]` (small)

**Plan.** Settings → AI model size:

| Option | File | Size | Notes |
|---|---|---|---|
| Small (default) | Qwen3.5-0.8B Q4_K_M | 0.53 GB | current; fastest |
| Medium | Qwen3.5-2B Q4_K_M | 1.28 GB | better writing and planning |
| Large | Qwen3.5-4B Q4_K_M | 2.74 GB | best; needs ~3.5 GB free memory |

- Each file pinned by SHA-256 and downloaded only when chosen, with progress in the notch.
- Before switching, Hark checks free memory and warns. This PC has 17 GB, but only about 1 GB was free
  when checked, so Large may need other apps closed.
- The AI evaluation (commands, chat, writing, rewriting, planning) is re-run on each size and the results
  written here, so the choice is based on evidence.

---

## Loose ends to check along the way

- Replies spoken aloud: there's a "tts/enabled" setting, but nothing uses it yet.
- The "now playing" music card: the engine sends it; the notch's music layout hasn't been checked.
- Teleprompter pace (155 words a minute) and the eye reactions need a try with your real voice.
