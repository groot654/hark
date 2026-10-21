# 03 — heynixi desktop client: UI, mascot, dictation, audio

Scope: every `app.*` module of heynixi 0.2.1 (build `19c58a3`, built 2026-10-18), the Windows PySide6 client.
Target: the spec for the "togo" reimplementation.

## 0. Method and conventions

* **Sources.**
  - `strings-ascii.txt` from the analysis folder.
  - A direct read-only decode of the Nuitka constants blob inside `heynixi.exe`. The decoder script is in the session scratchpad (`nuitka_blob.py`).
  - The runtime logs (`client.log`, `nexus.log`) and the install docs.
* **Why the blob decode.** It recovers numbers, tuples and dicts that the ASCII string dump loses, for example `(340, 34)`, `{'stop': 'Command', …}`, and floats. Nothing was executed or modified.
* **Offsets.** Every `0x8b…` / `0x8c…` value is a **file offset in heynixi.exe** and matches column 1 of `strings-ascii.txt`. The app constants span `0x8baea21` (`.app.about_dialog`) to `0x8c09000` (`app.win_foreground`).
* **Observed vs inferred.** Each claim carries one of three tags:
  - **[O]** is observed: a literal string or constant, or a log line.
  - **[I]** is inferred: a name↔value pairing or a behaviour reconstructed from code order.
  - **[I?]** is a low-confidence inference.
* **Why some names are guesses.** Nuitka deduplicates names per module, so a module-level `X = value` only shows the name next to its value the first time that name appears. Many constant names were already used inside functions, so several pairings below are inferred from source order.
* **Naming.** Modules call themselves "NEXUS" internally: env vars `NEXUS_*`, thread names `nexus-*`, log `nexus.hud`. The product, the window titles and the mascot use "heynixi"/"Nixi". Old copy also says "notch".

---

## 1. HUD / pill / notch (`app.hud`, `app.hud_music`)

### 1.1 Concept (module docstring 0x8bca9d5) [O]

"The voice HUD - one shape that morphs."

* **One surface.** A single rounded rectangle whose width, height and corner radius animate together. Content cross-fades inside it, and nothing is ever added or removed. The design brief is "the notch on an iPhone, on Windows".
* **Four rules:**
  1. It never takes focus while closed.
  2. It shows the *tail* of the live transcript, elided on the LEFT.
  3. It stays up for the whole session; replies don't schedule a fade, only session end does.
  4. Confirmation yes/no buttons live on the closed capsule.

### 1.2 Window flags and placement

| Item | Value | Tag / offset |
|---|---|---|
| Base flags | `Qt.Tool \| FramelessWindowHint \| WindowStaysOnTopHint`. A tool window keeps it off the taskbar. `NEXUS_CUA_WINDOW=1` switches it to a normal `Window` for UI-automation tests | [O] 0x8bc0c90–0x8bc0cfe |
| Extra flags | `WindowDoesNotAcceptFocus` (while closed), `WA_TranslucentBackground`, `WA_ShowWithoutActivating` | [O] 0x8bc1470 |
| Focus | Focusable only when expanded ("closed is untouchable, open takes focus"). Changing flags un-maps the window, so it is re-shown and its opacity restored. To actually get keyboard focus it borrows the foreground thread's input queue (`engine.nexusd.tools.win_focus.focus_hwnd`); plain `activateWindow()` was refused by Windows | [O] 0x8bc2a5e, 0x8bc2cce |
| Exclude from capture | Only in teleprompter mode: `SetWindowDisplayAffinity(hwnd, 0x11 = WDA_EXCLUDEFROMCAPTURE)`. `NEXUS_PROMPTER_IN_CAPTURE=1` disables it | [O] 0x8bc5e3e, value 17 at 0x8bc5d66 |
| Backdrop | No blur by default. `NEXUS_HUD_BLUR=1` tries `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=38, DWMSBT_TRANSIENTWINDOW=3)`. With Windows "Transparency effects" off (`HKCU\…\Themes\Personalize\EnableTransparency`) the fill is fully opaque | [O] 0x8bc06a7, 0x8bc0508 |
| Animations | Reads `SPI_GETCLIENTAREAANIMATION` (0x1042). When off, springs and pops are skipped and the mascot snaps between expressions | [O] 0x8bc05bb |
| Display | `NEXUS_HUD_DISPLAY` (a number, or `primary`/`main`/`default`). It falls back to Qt screen order. Default is the primary screen | [O] 0x8bc3460, 0x8bc349c |
| Vertical position | `_place()` uses `availableGeometry().y + _NOTCH_TOP` / `_TOP_FRACTION`, horizontally centred. The candidate value for `_TOP_FRACTION` is 0.035 | [I?] 0x8bc390d, module consts 0x8bcb5cf |
| Dock at top | `NEXUS_HUD_DOCK=top` gives a flush notch (flat top, rounded bottom corners). Otherwise it is a floating pill, rounded all round | [O] 0x8bc0b74, 0x8bc7d8f |
| Scale | `NEXUS_HUD_SCALE`, applied through `_s(v)`. The 3.0 next to it is probably the clamp maximum | [O] 0x8bcb5e1 / [I?] |
| Deferred reveal | `VoiceHUD(reveal_now=False)` stays hidden until the engine connects. Then `reveal()` shows it with a greeting | [O] 0x8bc1f30 |

### 1.3 Geometry (base px, before `NEXUS_HUD_SCALE`)

Module-level constants are at 0x8bcb485–0x8bcba86.

| Constant | Value | Tag |
|---|---|---|
| `_BASE_C_W, _BASE_C_H` (closed active capsule) | **340 × 34** | [O] value, [I] pairing |
| `_BASE_LIVE_W` (normal live-speech width) | **164** | [I] |
| `_BASE_E_W, _BASE_E_H` (expanded drawer) | **520 × 400** | [I] |
| `_BASE_INPUT_H` (text box in the drawer) | **36** | [I] |
| `_BASE_REST_W, _BASE_REST_H` (resting dock/notch) | **104 × 30** | [I] |
| `_BASE_BAND_H` (face band height in notch mode) | **54** | [I] |
| Face rect (onboarding docstring "HUD proportions") | 84 × 45 face, 340 × 88 command capsule with face band, 120 × 88 dictation pill | [O] 0x8bf3b4a |
| Rest button row | Three glyphs (Command pointer, Dictate mic, Write pen), each a **26 px** hit target. Centre y = 22 in a 26-px row; the onboarding copy says "13px glyphs, 30px apart, a 22px blue ring". Hover fill alpha 34, press fill alpha 62 | [O] 0x8bc306c, 0x8bf010a, 0x8bc8759 |
| Rest-open hover | Opens immediately when the pointer arrives; closes after the pointer leaves (`leaveEvent` timer 280 ms) | [O] 280 at 0x8bca715 |
| Input field | `QLineEdit` placeholder `Ask Nixi…`, send button `↑`, radius = `_INPUT_H/2`, padding 14, font 13 px, button font 15 px, button blue `rgb(10,118,240)`, hover `rgb(42,146,255)`, focus ring `rgba(10,132,255,0.6)` | [O] 0x8bc2555–0x8bc291b |
| Card | `_CARD_W` and `_CARD_ROW` exist. Row font 11 px; prose wrap max ~800 px width, max 12 rows; `wrap_rows()` default max_rows 7 | [O] 0x8bc5295–0x8bc571b |
| Other module ints (unpaired) | `(780,) 1.32 22 (32,) (420,) 7 4200 7000 80 170 16 33.0 160 1.2 1.06 760 0.82` | [O], pairing [I?] — see 1.5 |

### 1.4 Colours (`app.hud`, dark pill)

Module order at 0x8bcb485. Names are paired in source order, so most are [I]; the comment column says which are [O].

| Name | RGBA | Comment |
|---|---|---|
| `C_GLASS_TINT` | (11,12,15,**190**) | translucent fill when blur is on |
| `C_GLASS_TINT_OPAQUE` | (11,12,15,**232**) | default fill (no blur) |
| `C_BG` | (11,12,15,**252**) | name [O] |
| `C_BORDER` | (148,163,184,42) | |
| `C_TEXT` | (244,246,248,245) | "bright white = your speech" |
| `C_DIM` | (148,163,184,205) | placeholder / greeting / hint |
| `C_META` | (148,163,184,135) | timestamps |
| (state accent) | (42,112,224) | probably `C_LISTEN`; the prompter uses `C_LISTEN` |
| (unknown) | (31,35,41) | |
| `C_THINK` | (59,130,246) | blue |
| (warn/confirm) | (245,158,11) | amber |
| `C_SPEAK` | (34,197,94) | green; name [O] |
| (idle) | (170,170,182) | |
| `C_ERROR` | (239,68,68) | red; show_error is "muted, not red" in copy |
| `C_CONFIRM` (light pill) | (146,64,14) | name [O] 0x8bc9c25 |
| light error | (153,27,27) | |
| Light-notch text | `C_TEXT` (28,35,45), `C_DIM` (66,78,94), `C_META` (92,102,116), `_FLOAT_EDGE` (0,0,0,42) | [O] 0x8bc1b60 — used when the notch colour is light (`light_surface()`) |
| Notch fill default | `_NOTCH_FILL` (0,0,0) | [O] |
| Specular top-edge highlight | (255,255,255,0) → (255,255,255,56), one pixel tall, brightest at the centre | [O] 0x8bc835b |
| Chat bubbles | `C_BUBBLE_ME` (255,255,255,18) dark / (0,0,0,18) light; text (255,255,255,235) | [O] 0x8bc9512 |
| Hover-label chip | bg (25,25,29,245), border (255,255,255,90), font 17 px | [O] 0x8bc71de |
| Tabs (segmented) | track (0,0,0,20)/(255,255,255,20), selected (0,0,0,32)/(255,255,255,46); items `Chat`, `History`; tab slide 180 ms OutCubic | [O] 0x8bc970f, 0x8bc15c1 |
| History row highlight | (29,78,216) | [O] |
| Buttons | Glyphs use the **eye colour** ("red eyes, red buttons"), full strength under the pointer (alpha 200 otherwise) | [O] 0x8bc8664 |
| Yes/No | `C_YES` / `C_NO`, glyphs `✓` and `✕` on (12,12,16) | [O] 0x8bca36e |

**Rim glow palettes** (four colours each, conical gradient that flows in degrees/s) [O] 0x8bcb75f; names [I] from `_rim_target` 0x8bc6912:

| Palette | Colours |
|---|---|
| `_PAL_LIGHT` (idle/listening) | (236,241,255) (198,212,245) (255,255,255) (214,224,250) |
| `_PAL_GOOD` (done) | (52,211,153) (120,236,190) (34,197,94) (170,244,210) |
| `_PAL_BAD` (error) | (255,84,84) (255,132,112) (226,44,44) (255,160,140) |
| `_PAL_WAIT` (thinking/acting) | (255,196,64) (255,158,58) (255,222,122) (250,180,84) |

The rim target values come from `_rim_target` and `_advance_fx` at 0x8bc6912 [O]. Their mapping to states is [I].

| State | Amount | Speed (°/s) |
|---|---|---|
| listening | level-driven, 0.35 … | 30 → 60 |
| good | 0.7 | 40 / 140 |
| nothing / hint | 0.15 | 25 |
| thinking / acting | 0.4 | 80 / 280 |
| speaking | 0.12 | 70 |

* **Smoothing.** Exponential approach with k ≈ 0.1–0.2, full turn 360°, 18 stroke layers, base alpha 0.026. The rim is "a flowing glow that fades gradually into the pill … reads as light, not a white bezel."
* **Listening halo.** `_paint_glow` uses `_GLOW_FREQ/_ALPHA_MIN/_ALPHA_MAX/_LAYERS/_MARGIN/_COLOR`. Candidates from the module: alpha 15–40, margin 10.0, phase rate 33.0. It is marked "PLACEHOLDER pending real design references" [O] 0x8bc895a.

### 1.5 Timings

| Item | Value | Tag |
|---|---|---|
| Reply hold `reading_hold_ms` | `max(_HOLD_MS=4200, min(_HOLD_MS_MAX=7000, 2000 + 300·words))`. Docstring: "About 300 ms a word plus two seconds to look up, bounded." | [O] 0x8bc10b8, 4200/7000 at 0x8bcba2c; formula [I] |
| `announce(text, hold_ms=2600)` | greeting / one-off message | [O] 0x8bcc53e |
| Notification (reminder.due etc.) | `NOTIFY_HOLD_MS`; tray balloon 8000 ms | [O]/[I] |
| Card (`show_card`) | timer 15000 ms max and 1200 per … (rows); `end_card` grace 1500 ms | [O] 0x8bc5295, [I] formula |
| Now-playing card | peek 4500 ms, requested 9000 ms; media-button keep-alive 6000 ms; clock refresh 500 ms | [O] 0x8bc582f, 0x8bca856 |
| Dictation done / message | 550 ms / 1500 ms (`_DICTATION_DONE_MS`/`_DICTATION_MSG_MS`) | [I?] 0x8bcc5d1 |
| Tick | `_TICK_MS` = 16 (60 fps) | [I] |
| Fade / morph | `_FADE_IN_MS`, `_FADE_OUT_MS` (InCubic), `_MORPH_OPEN_MS` (OutBack, overshoot `_MORPH_OVERSHOOT`), `_MORPH_CLOSE_MS` (Linear). Candidate values from the module tail: 80, 170, 160, 1.2, 1.06, 760 | names [O], values [I?] |
| Shape spring (notch mode) | `_SPRING_K`, `_SPRING_ZETA`, c = 2·√k·ζ; integration sub-step 1/240 s (0.004167); dt clamp 0.05 s; settle at < 0.5 px and < 8 px/s | [O] 0x8bc3166–0x8bc3240 |
| Content fade-in | "Rows fade in over the back half of a growth, never mid-squash" (0.45 progress) | [O] 0x8bc3377 |
| Opacity floor | 0.01 (`_set_opacity`); rest alpha `_REST_ALPHA` ≈ 0.95 [I?]; `NEXUS_HUD_REST=0` disables the idle dock | [O] |
| Mouse look | Eyes follow the cursor within 1100 px (scale 380/220 px) | [O] 0x8bc6827 |
| Fullscreen poll | `QTimer` 1000 ms | [O] 0x8bc1ebe |
| History timestamps | < 90 s → "now"? ; minutes `m`; hours `h`; `yesterday` (< 2 days); days `d` (< 7); else `%d %b` | [O] 0x8bc1228 |

### 1.6 States and transitions

* **`set_state(name)` values** [O] (`_STATE_FACE`, `_DICTATION_FACE`, `_rim_target`, `_hud_activity_state`): `idle`, `listening`, `thinking`, `acting`, `speaking`, `confirming`, `error`.
* **Dictation sub-states:** `listening`, `transcribing`, `done`, `nothing` (no speech), `error`, `hint`.

```
          (launch, hidden) --reveal()/announce("Nixi is ready")-->  REST
REST  = resting dock/notch (104x30; face only, buttons grow out on hover)
REST --ptt/wake/click--> leaving rest -> ACTIVE capsule (340x34, live width 164, grows to fit answer)
ACTIVE: listening -> thinking/acting -> (speaking|confirming|error) -> flash_success (bars draw a tick + chime)
ACTIVE --hold_then_fade(hold_ms)--> fade_out -> entering rest
ACTIVE --F9/toggle_expanded--> EXPANDED drawer 520x400 (Chat/History tabs + "Ask Nixi…" input), focusable
any --begin_dictation--> DICTATION pill (compact; app icon + 5 dots) -> done/error -> back
any --show_card--> CARD (list: tasks/notes/…); --show_now_playing--> MUSIC card; --begin_prompter--> PROMPTER strip
```

* **Log lines** [O] 0x8bc2f74 … 0x8bc3c40: `hud: entering rest`, `hud: leaving rest`, `hud: fade_out -> %.2f`, `hud: fade_out refused, session is live`, `hud: fade_out ignored, not active`, `hud: full-screen app in front, stepping aside`, `hud: full-screen app gone, back at rest`.
* **Session flag.** `begin_listening()` sets `_session`. Only `hold_then_fade()` and `end_session()` clear it. `fade_out()` refuses while the session is live (docstring 0x8bc3c6e) [O].
* **Header line** [O]:
  - Placeholders: `Ready — say Hey Nixi`, `Working on it...`, `Confirm?`, `Something went wrong`, `Say something, or type below` (empty chat).
  - Drawer history strings: `Looking...`, `Nothing here yet`, `Untitled`.
  - Startup greetings: `Nixi is ready`, `Use the tray to talk` (when hotkeys fail) [O] 0x8be3291.
* **Live words.** Each word fades in (`_WORD_IN_S`, stagger `_WORD_STAGGER_S`, values 0.28 / 0.045) with a "shimmer" sweep on interim text [O]/[I] 0x8bcd6f3.
* **Level indicator.** Four bars track the mic level while listening; other states show a slow travelling wave (bar_w 2.4, gap 1.5, cap 2.9). On success the bars "draw themselves into a tick" stroke-first (`_DONE_STROKE` 1.6 px; check geometry 6.5/4.6/4.2) [O] 0x8bc9da4–0x8bca047.
* **Dictation pill.** The focused app's icon plus five independently-phased dots:
  - listening: level-driven
  - transcribing: a single travelling wave
  - static: done
  - colours: `C_THINK` / `C_ERROR` etc.
  - No status text [O] 0x8bc8fce.
  - Dot geometry: base 2.6, amp 1.1, gap 0.85 (`_DOT_BASE/_DOT_AMP/_DOT_GAP`) [I].
* **Hover tips** `_BUTTON_TIPS` [O] 0x8bcb887: `stop → "Command"`, `dictation → "Dictate"`, `write → "Write"`, `more → "Type a message · F9"`. While a question is pending the right-hand controls become yes/no.
* **Signals emitted by the HUD** [O] 0x8bca856: `stop_clicked`, `mic_clicked`, `dictation_clicked`, `write_clicked`, `confirm_yes`, `confirm_no`, `submitted(str)`, `history_requested`, `session_chosen("session:<id>")`, `media_action`, `prompter_toggle`, `prompter_close`.

### 1.7 Cards

* **Card titles** `_CARD_TITLES` (0x8bed6e5) [O]: `task.list → "Your list"`, `note.list → "Notes"`, `habit.status → "Habits"`, `reminder.list → "Reminders"`, `memory.recall → "Remembered"`, `day.briefing → "Today"`, `routine.list → "Routines"`.
* **Answer titles** [O]: `screen.read → "On screen"`.
* **Notification titles** [O] 0x8be56f6: `reminder.due → "Reminder"`, `focus.done → "Focus session"`, otherwise `"Message"`. `pill.notify` is shown the same way and also as a tray balloon `heynixi - <title>`.
* **Card rows.** The prefix `. ` renders a dot marker and `- ` renders a checkbox; long lists show `Scroll to read` [O] 0x8bc5646.
* **Agent steps.** `agent.step` events go to `set_reply()`. `assistant.plan` / `assistant.tool` list tool names. Tools needing `permission: sensitive` raise `confirm` ("Proceed?") and the state `confirming` [O] 0x8be56f6–0x8be5983.
* **Long answers.** `show_text(title, text)` wraps prose into a card when `answer_fits_line()` is false [O] 0x8bc5383.
* **Now playing** (`app.hud_music`, docstring 0x8bce280) [O]:
  - Layout: cover art (default gradient `#5E8BFF → #B07CFF`), title, artist, progress bar `0:42 ━━●── -3:20` (or `Live`), and three filled transport glyphs (previous / play-pause / next) in the eye colour.
  - Card adds below the face band: ART 6.0, BAR_ROW 10.0, padding 12, 16/22 sizes.
  - Fallback label `Now playing`.
  - Turned off by `NEXUS_HUD_MUSIC=0` / the setting "Show what's playing".
* **Reaction badges** [O] 0x8bccdf6:
  - `charging → bolt (#FFD60A)`, `unplugged`, `download → arrow (#0A84FF)`, `screenshot → viewfinder`, `timer → bell (#FF9F0A)`.
  - Faces: charging/download/screenshot/timer → `happy`/`surprised`/`wink` per the `_REACTION_FACES` dict.
  - Never shown during dictation, the teleprompter, or full-screen step-aside.

### 1.8 Full-screen and multi-monitor (`app.fullscreen_watch`, docstring 0x8bbbead) [O]

* **Poll.** `poll(notch_hwnd)` runs every ~1 s.
* **Full-screen rule.** The foreground window must be on the notch's own monitor (`MonitorFromWindow`, `MONITOR_DEFAULTTONEAREST`). Then either:
  - `SHQueryUserNotificationState` ∈ {`QUNS_RUNNING_D3D_FULL_SCREEN`(3), `QUNS_PRESENTATION_MODE`(4)}, or
  - the window rect covers the whole monitor, is not `IsZoomed`, and has no `WS_CAPTION` (0x00C00000 = 12582912).
* **Ignored shell windows** `SHELL_CLASSES`: `WorkerW, Progman, Shell_TrayWnd, Shell_SecondaryTrayWnd, MultitaskingViewFrame, XamlExplorerHostIslandWindow, TopLevelWindowForOverflowXamlIsland, Windows.UI.Core.CoreWindow, ForegroundStaging`. heynixi's own PID is also ignored.
* **Debounce.** `Debounce(hide_after=2, show_after=1)`.
* **Failure.** On probe failure it reports "not fullscreen" (`full-screen probe failed; leaving the notch shown`).
* **Scope.** It hides only the *resting* notch. A session the user started (hotkey or wake) always shows. Setting: "Hide during full-screen apps" / `NEXUS_HUD_HIDE_FULLSCREEN`.

---

## 2. Mascot "Nixi" (`app.mascot`, `app.mascot_wardrobe`, `app.look_palette`, `app.ios_ui`)

### 2.1 Face engine (docstring 0x8bda022) [O]

* **Drawing.** The face is painted with QPainter, so it is crisp at any scale.
* **Motion.** Every feature rides a damped spring.
  - Eyes dart every 1–2 s with jitter.
  - Each mood change starts with a blink and a small hop; idle hops on its own.
  - Thinking floats three dots; sleepy floats z's.
  - With Windows animations off the face snaps between expressions.
* **Character interface** `Character`: `expression`, `advance(dt, name, level, look)`, `paint(p, rect, opacity)`, `settle(name, look)`, `poke(look)`. Characters register through `register_character(name, label, factory)`.
* **Selection.** `NEXUS_HUD_CHARACTER` / setting `hud_character` (default `glow`).
* **Built-in style** `FaceStyle('glow','Glow', eyes='pill', eye_w 0.5, eye_h 0.62, eye_gap 0.82, brows=False, mouth=False, details=False, glow=2.0)` [O] 0x8bdb552. The shipped look is **pill-shaped glowing eyes with no pupils, brows or mouth**: "A solid eye of light with no pupil: the whole eye moves to look, tilts to look worried or sad, squashes when happy and closes to a line" (0x8bd98d0). The renderer also supports oval eyes with pupils, brows, mouth, tongue, teeth, cheeks, blush and tears.
* **Blink and timing.**
  - First blink after 1.5–4 s, then every 2–5 s, with an occasional double blink.
  - Hops every 5–10 s (`_hop_at`).
  - Glances 0.6–2.2 s apart.
  - Frame dt is 1/60.
* **Springs** (stiffness, damping) [O] 0x8bdb215:

| Feature | Spring |
|---|---|
| look_x / look_y | (300, 0.6) |
| brow_l / brow_r | (180, 0.55) |
| brow_tilt | (150, 0.6) |
| pupil | (160, 0.5) |
| eye_size | (180, 0.6) |
| blush | (40, 1.0) |
| dots | (60, 1.0) |
| zzz | (40, 1.0) |
| tears | (60, 1.0) |
| glow | (120, 0.85) |
| stretch | (320, 0.45) |
| default | (220, 0.75) |

* **Pokes** (docstring 0x8bd8bf0). One click gives a blink, a hop and a glance toward the click. A couple of clicks make it **giggle**; more make it **dizzy** (eyes circle, 4.5 s) and then **woozy**. The poke window is 0.9 s; boop lasts 0.6 s.
* **Listening.** Eyes widen and glow with the mic level: eye_size +0.05…0.2, glow +0.45, mouth_open.

### 2.2 Expressions (moods) [O] 0x8bda9d6–0x8bdb1cc

Fields: eye_size, pupil, look_x/y, brow_l/r/tilt, smile, smirk, mouth_open, mouth_w, open_l/r, shut_l/r, squint, cheeks, blush, tongue, tears, dots, zzz, wavy, glow.

| Mood | Distinguishing values |
|---|---|
| idle | smile 0.6, mouth_w 0.6, glow 0.3 |
| hover | eye_size 1.06, pupil 1.12, brows 0.55, smile 0.95, mouth 0.5/0.9, cheeks 0.5, blush 0.4, glow 0.55 |
| listening | eye_size 1.08, pupil 1.12, brows 0.6, look_y −0.1, glow 0.5 |
| thinking | look (0.65, −0.85) (up-right), brow_r 0.85, brow_tilt −0.15, smirk 0.8, squint 0.12, **dots 1.0** |
| concentrate (acting) | eye_size 1.04, look (−0.1, −0.5), **tongue 1.0**, glow 0.4 |
| talking (speaking) | pupil 1.05, smile 0.6, mouth_open 0.3, mouth_w 0.72 |
| happy | squint 0.7, pupil 1.2, smile 1.0, mouth_open 0.8, cheeks 0.7, blush 0.8, glow 0.8 |
| wink | shut_l 1.0, smirk 0.3 |
| nervous (confirming) | brow_tilt 0.9, smile −0.05, **wavy 1.0** |
| sad (error) | open 0.84, brow_tilt 0.95, smile −0.75, **tears 1.0** |
| meh (nothing/hint) | open 0.5, look (−0.4, 0.15), smile −0.25 |
| surprised | eye_size 1.15, brows 1.0, mouth_open 0.7 |
| sleepy | open 0, pupil 0.88, brows −0.35, **zzz 1.0** |
| play reactions | boop, giggle, dizzy, woozy |

* **HUD state → face** `_STATE_FACE` [O] 0x8bcb93b: `listening→listening, thinking→thinking, acting→concentrate, speaking→talking, confirming→nervous, error→sad`.
* **Dictation → face** `_DICTATION_FACE` [O] 0x8bcb8d6: `listening→listening, transcribing→concentrate, done→happy, error→sad, nothing→meh, hint→meh`.
* **Rest faces.** Hover gives `hover` looking toward the hovered button. Button gaze targets [O] 0x8bcb838: `stop(-0.7,0.85)`, `dictation(0,0.95)`, `write(0.7,0.85)`. The face goes `sleepy` after `_SLEEP_AFTER_S` idle and `happy` while music plays.
* **Teleprompter gaze.** The eyes follow the word being read, left to right, looking down.

### 2.3 Wardrobe (docstring 0x8bdd452) [O]

* **Outfits** `OUTFITS` (0x8bddb70):

| id | label | kind |
|---|---|---|
| `none` | None | overlay |
| `headphones` | Headphones | overlay |
| `shades` | Shades | skin |
| `glasses` | Glasses | overlay (reading glasses) |
| `bow` | Bow | overlay (`#FF9CC5` / `#E0457F`) |

  Settings validation allows exactly these five (0x8bfca76).
* **Seasonal looks** `SEASONS` [O] 0x8bddb70:

| Look | Dates | Style |
|---|---|---|
| `pumpkin` | Oct 24 – Oct 31 | eye skin, orange `#FF9F1C` / `#FFD08A` |
| `snow` | Dec 1 – Jan 6 | overlay of falling flakes |
| `hearts` | Feb 10 – Feb 14 | heart eye skin, pinks `#FF5C8A` / `#FFB3C8` / `#FF6FA8` |

  Switch: `NEXUS_HUD_SEASONAL` / "Seasonal looks".
* **Heart eyes.** `show_love()` fires when the user thanks or praises Nixi (`engine.nexusd.core.quick_replies.is_praise`). The reaction is `{'love': (2.4 s, 'Aw, thank you.')}` with five floating hearts [O] 0x8bddc4b.
* **Music.** While media plays, headphones are worn automatically and the face sways and bobs with the speaker peak (`app.output_meter`). Dance: tilt ≈ sin·7°, lift 0.07 of the face height, beat ≈ `_BEAT_HZ` [O]/[I] 0x8bdc709.
* **Other wardrobe colours** [O]: accent `#3882F6`, greys `#E9EBF0`, `#AEB3BF`, `#2F3442`, `#12141A`.

### 2.4 Customisable look (`app.look_palette`) [O] 0x8bd23be

* **Notch presets:** Black `#000000`, Graphite `#1F2329`, Deep navy `#111D35`, Plum `#30213C`, Forest `#15342A`, White `#F4F6F8`.
* **Eye presets:** White `#FFFFFF`, Ice blue `#8FD8FF`, Mint `#8FF0C4`, Amber `#FFD18A`, Pink `#FFB8D8`.
* **Defaults.** `DEFAULT_NOTCH='#000000'`, `DEFAULT_EYES='#FFFFFF'` (env `NEXUS_HUD_COLOR` / `NEXUS_HUD_EYES`, validated `#RRGGBB`).
* **Slider maths.**
  - The pill slider goes black → hues → white; `_PILL_BLACK_END`=0.06 and `_PILL_WHITE_START`=0.94 [I]. Lightness range is (0.12, 0.82) and there is a separate "shade" slider.
  - The eye slider goes black, then white, then glow colours (0.14 / 0.78 …).
* **Contrast.** `light_surface()` uses WCAG luminance > 0.35, which switches the HUD to the dark-ink light palette. `readable_eye_colour()` shifts the eyes darker on a light pill or lighter on a dark pill only when the contrast ratio is below `MIN_EYE_CONTRAST = 1.8`.

### 2.5 App-wide light theme (`app.ui_theme`, `app.ios_ui`) [O] 0x8c022c5, 0x8bd0c06

| Token | Hex |
|---|---|
| INK | #101114 |
| SECONDARY / MUTED | #6E6E73 |
| TERTIARY / FAINT | #8A8A8E |
| GROUPED_BG / FILL | #F2F2F7 |
| FIELD / CARD / WHITE | #FFFFFF |
| SEPARATOR / LINE | #E5E5EA |
| BLUE (brand) | #3882F6 |
| BLUE_SOFT | #EAF2FE |
| GREEN (switch) | #34C759 |
| switch off | #E9E9EB |
| SUCCESS | #1E9E62 |
| WARNING | #B7791F |
| ERROR | #D64545 |
| hover / pressed | #DEDEE3 / #D1D1D6 |
| primary button | INK, hover #2A2D33, pressed #000000 |
| onboarding extras | #626972, #DFE2E5, #34D399, #F5A524 |

* **Fonts** [O]:
  - Display: `"Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI"`.
  - Text: `"Segoe UI Variable Text", …`, letter-spacing 97.5 %, `PreferNoHinting`.
  - HUD: `Segoe UI Variable Text`, falling back to `Segoe UI`, set by pixel size.
  - App chrome font: `Segoe UI`.
  - Dialog base 10 pt; settings page title 19 pt/700; About name 24 px/700; Privacy title 18 pt/700.
* **Widgets.**
  - Cards: radius 14, border rgba(0,0,0,.06). Fields: radius 10, min-height 36. Buttons: radius 18.
  - iOS switch: 48×29 knob, 240 ms OutCubic, rendered to PNG for `QCheckBox::indicator`.
  - Grouped list rows: 52 px.
  - `PrimaryButton`: a black capsule, 300×50 by default, that scales to 0.97 when pressed.
  - Backdrop: a faint lilac/blue glow with dither noise (seed 7).
* **Tray menu stylesheet** (dark) [O] 0x8be354e: bg `rgba(16,16,19,0.98)`, radius 14, items 9 px 22 px, text `rgba(240,240,245,0.92)`.
* **Brand icon.** A radial gradient on (12,12,14) using `C_ACCENT` (59,130,246); asset `assets/brand/notch-mark.png` [O].

---

## 3. UI text (verbatim)

### 3.1 Tray menu (`NexusApp._build_tray`) [O] 0x8be3801

* **Menu items:** `Open heynixi`, `History`, `New Conversation`, `Teleprompter`, `Settings`, `Setup Guide`, `Privacy && Data`, `System Check`, `About heynixi`, `Quit heynixi`.
* **Tooltip:** `heynixi`. The window title becomes `heynixi — <State>` or `Offline`.

### 3.2 Settings dialog (`app.settings_dialog`) [O] 0x8bf8f0d–0x8bfaf74

* **Window and layout.** Window title `heynixi Settings`, 840×560. The left nav (190 px) has the sections `General`, `Voice & microphone`, `Dictation style`, `Command & hotkeys`, `Privacy & history`, `AI model`. Buttons are Save / Cancel.
* **Intro:** "Changes to how Nixi looks apply when you save. Others apply the next time heynixi starts."

| Page (title — description) | Rows (label: control / options / tooltip) |
|---|---|
| **General** — "Choose how heynixi stays available while you work." | `Start heynixi when I sign in` (switch) · `Keep heynixi visible while idle` (switch) · `Hide during full-screen apps` · `Show what's playing` · `Outfit` (combo: None/Headphones/Shades/Glasses/Bow) · `Seasonal looks` · `Pill colour` (colour slider) · `Pill shade` (slider, disabled for black/white) · `Eye colour` (slider) · `Live preview` ("Live notch colour and eye colour preview"; contrast note: "These are too close to see Nixi's eyes, so they'll be shown a little darker or lighter.") · Info card **"Three modes. One floating dock."** / "Command, Dictate, and Write stay together above your work. The same capsule grows to show the active conversation." |
| **Voice & microphone** — "Select your input and local speech experience." | `Microphone` (combo: `Windows default microphone` + devices; missing: `Unavailable configured device (…)`) · `Speech recognition` (combo: `Parakeet — Fast, efficient (recommended)`=parakeet, `Whisper — Better recognition`=faster_whisper; tooltips "Parakeet is the fast, efficient default speech recognizer." / "Whisper can provide better recognition performance, especially on difficult speech. It uses more CPU/GPU resources and may respond more slowly."; help text "Parakeet is the fast, efficient default. Whisper … Both run locally on this PC.") · `End after silence` (QDoubleSpinBox 1.0–10.0, step 0.25, 2 decimals, suffix " seconds") |
| **Dictation style** — "Choose how spoken words become clean text." | `Writing style` combo: `Clean — remove fillers and format`=clean, `Polished — smart formatting`=polished, `Exact — preserve spoken wording`=exact · caption "Your words, in your style." / "Clean handles punctuation and spoken layout. Polished adds a bounded formatting pass when available and falls back to Clean. Exact keeps the transcribed wording." · button `Personal dictionary, snippets && app styles…` |
| **Command controls & hotkeys** — "Set how you start and stop voice actions." | `Command trigger` (`Hold to talk`=hold / `Press once to toggle`=toggle) · `Command hotkey` (line edit, placeholder `right ctrl`) · `Dictation hotkey` (placeholder `right alt`) · `Wake phrase` (line edit, placeholder `Off — type a phrase to enable`, max 80) |
| **Privacy & history** — "Review retention and how configured services handle data." | `Keep verbatim history` (spin 0–3650, suffix " days", 0 = `Keep forever`) · note "Speech recognition and the AI model both run on this PC - nothing you say or write is sent to a cloud service. Polished falls back to Clean if the model is unavailable." |
| **AI model** | see 3.6 |

* **Messages:**
  - Save error: `Settings were not saved`.
  - Success: `Settings saved` / "Restart heynixi to apply the new " + names joined ("talk key", "dictation key", "speech model", "wake phrase").
  - Personalization: "Couldn't load dictation preferences" / "Couldn't save dictation preferences".
* **Persisted settings** (`settings_store`, written into `.env` with the header `# heynixi user settings`) [O] 0x8bfcb24:

| Env | Field | Default |
|---|---|---|
| NEXUS_DICTATION_MODE | dictation_mode | clean |
| NEXUS_PTT_MODE | ptt_mode | hold |
| NEXUS_PTT_KEY | ptt_key | right ctrl (max 40) |
| NEXUS_DICTATION_KEY | dictation_key | right alt |
| NEXUS_SILENCE_TIMEOUT_S | silence_timeout_s | 2 (1–10) |
| NEXUS_WAKE_PHRASE | wake_phrase | hey nixi |
| NEXUS_HUD_REST | hud_rest | 1 |
| NEXUS_STT_BACKEND | stt_backend | parakeet |
| NEXUS_AUDIO_DEVICE | audio_device | "" (max 160) |
| NEXUS_HISTORY_DAYS | history_days | 30 (0–3650) |
| NEXUS_HUD_CHARACTER | hud_character | glow |
| NEXUS_HUD_COLOR / _EYES | hud_color / hud_eyes | #000000 / #FFFFFF |
| NEXUS_START_WITH_WINDOWS | start_with_windows | 1 |
| NEXUS_HUD_HIDE_FULLSCREEN | hud_hide_fullscreen | on |
| NEXUS_HUD_OUTFIT | hud_outfit | none |
| NEXUS_HUD_SEASONAL / _MUSIC | hud_seasonal / hud_music | on |

* **Restart fields.** Restart-only changes are ptt_key, dictation_key, stt_backend and the wake phrase. Look settings apply live through `set_character`, `set_look` and `set_outfit`.

### 3.3 Dictation personalization dialog [O] 0x8bb943c

* **Window.** Title `Personalize Dictate`, 710×490. Tabs `Dictionary`, `Snippets`, `Per-app style`.
* **Dictionary.** Columns `Spoken` | `Written`. "Add names or jargon the recognizer consistently gets wrong. Corrections apply after transcription."
* **Snippets.** Columns `Spoken trigger` | `Insert this text` (multi-line editor, placeholder "Text to insert, including line breaks", row height 78). "Say the trigger alone, or say ‘insert’ followed by it. Longer sentences will not expand unexpectedly."
* **Per-app style.** Columns `App executable` | `Style` (combo: Default/Casual/Formal/Code). "Use the target app's executable name (for example, notepad.exe). Code preserves wording; Casual cleans speech; Formal also expands common contractions."
* **Buttons:** `Add`, `Remove selected`, Save / Cancel.
* **Errors:** `Check dictation preferences`, `Duplicate … entry`, `Too many per-app styles`, `Use an executable name (for example, notepad.exe) and a listed style`.

### 3.4 Onboarding / Setup guide "Meet Nixi" (`app.onboarding_dialog`) [O] 0x8bf3b4a, 0x8bf5039–0x8bf5dac

* **Window.** Frameless, non-modal, draggable. Designed at 760×620 and scaled. Window title `Meet Nixi`.
* **Controls.** `‹ Back`, `Skip` (tooltip "Skip the guide"), page dots, and the primary button: `Get started` on page 1, `Continue` in between, `Start using Nixi` on the last page. Arrow/PageUp/PageDown keys navigate.
* **First-run marker.** `%LOCALAPPDATA%\heynixi\onboarding-v2.done`; `NEXUS_SKIP_ONBOARDING` skips it. A blocking system-check result keeps the guide showing on the next launch.

| # | Page | Headline | Subtitle | Hint row |
|---|---|---|---|---|
| 1 | Meet | **Meet Nixi** ("Nixi" in blue) | "Your voice, in control. Right on your PC." | "Nixi lives at the top of your screen. Go on, point at it." |
| 2 | Command | "Just say “Hey Nixi”" | "Open apps, search the web, set reminders. It happens while you’re still talking." | [wave chip “Hey Nixi …”] or hold [Right Ctrl] and talk. Demo: "Hey Nixi, open Spotify" (music app "Good Vibes") |
| 3 | Dictate | "Dictate into anything" | "Talk instead of type, in any app. Clean, punctuated text lands at your cursor." | [Right Alt] hold, talk, let go · say [“comma”] [“new line”]. Demo: "Hey team, the launch is tomorrow. Please review the README." (New message / To) |
| 4 | Write | "Ask it to write" | "Emails, notes, replies. Describe it, and Nixi writes it where you’re working." | Click into a text box, tap [pen:Write] and say what you need. Demo: "Write a thank-you note to Sam" → "Hi Sam,\n\nThank you for jumping in on the launch this week…\n\nCheers,\nAlex" (Untitled - Notepad) |
| 5 | Screen | "It sees what you see" | "Ask about anything on your screen, or where to click. Nixi points right at it." | chips “What’s on my screen?” “Summarize this page” “Where’s the Save button?”. Demo: "Show me where the Export button is" → ring + "Click here" (Photos: Crop/Adjust/Filters/Export) |
| 6 | Teleprompter | "A teleprompter that listens" | "Copy your script and read. It scrolls with your voice, so you never lose your place." | Copy your script, then say [“Start teleprompter”] · Esc closes. Demo strip "Teleprompter · NN%" with the script "Hi everyone, I’m Alex. Today I’ll show you how Nixi works…" |
| 7 | Day | "Your day, handled" | "Lists, reminders, timers and notes, without opening a single app." | Just say it: “Hey Nixi …” or hold Right Ctrl. Bubbles: "What’s on my list?", "Remind me at 5pm", "Add bread to my list", "Timer for 10 minutes"; card "Your list": Milk, Eggs, Call Sam, Bread |
| 8 | Setup | "Private by design" | "Everything runs on this PC. Your voice never leaves it." | iOS card: `Listen for “Hey Nixi”` (switch), `Start with Windows` (switch), `Microphone` (combo `Default microphone` / `Unavailable (…)`); footnote "Change these anytime in Settings."; status `Checking this PC…` → "This PC is ready." / "Ready. <note>" / "Needs attention: <problem>" (colours ok #1E9E62, warning #B7791F, error #D64545) |
| 9 | Done | "You’re all set" | "Nixi lives at the top of your screen. Try one of these:" | tiles ▶ “Hey Nixi, open YouTube”, ☰ “What’s on my list?”, ⏱ “Set a timer for 5 minutes”, 📷 “Take a screenshot”; footer "Ask “What can you do?” any time." |

* **Save failure:** "Settings could not be saved."
* **Applying choices.** Choices are applied immediately ("A 'restart heynixi' box at the end of a welcome is the wrong last impression"). Toasts: `“Hey Nixi” is on` (2600 ms) or `“Hey Nixi” turns on next time heynixi starts` (4200 ms) [O] 0x8be47c7.

### 3.5 System check / readiness (`app.readiness`, `NexusApp._show_system_check`) [O] 0x8bf807a–0x8bf85fb

* **Request.** `GET /ready` (8 s timeout) plus a microphone summary that never opens the mic. Dialog progress text: `Checking heynixi…`.
* **Titles:** `heynixi is ready`, `heynixi is ready with notes`, `heynixi needs attention`.
* **Body:**
  - Lead: "Command controls your PC. Dictate inserts clean speech. Write turns an instruction into text."
  - Section headings: `Fix before relying on heynixi:`, `Status:`; bullets `• …`.
  - Footer: "Try Dictate in Notepad first. heynixi will never record audio during this system check."
  - First-run fallback: "… open System Check from the tray."
* **Item strings:** `Microphone: <name>`, `No default microphone`, `Default microphone unavailable (…)`, "Global hotkeys are unavailable; use the three buttons on the heynixi pill.", `Wake phrase unavailable: …`, `Unknown readiness error`, "The local engine readiness check failed (<code>: <msg>)."
* **Engine watchdog** (60 s after launch): "Engine didn't start — restart your PC if this keeps happening". Disconnect: "Engine disconnected. Attempting to reconnect…", then "Reconnected." [O] 0x8be5c4c, 0x8be558c.

### 3.6 AI model page (`app.model_picker`) [O] 0x8bde54a

* **Text.**
  - Title `AI model`; status `Checking this PC…`.
  - Card note: "Everything runs on this PC. Dictation and commands never need a model; it powers Write, Polished mode and on-screen actions."
  - Summary prefix: "This PC: …".
  - Runtime lines: "Using the built-in model runtime." / "The built-in model isn't running - restart heynixi." / "The local engine isn't reachable right now."
* **Model rows.** Name + `  · recommended` / `  · beta`, `X.X GB`, speed (`Fast`, `Good`, `Slow on this PC`, `Too big for this PC`) + ` · ~N s per reply`.
  - Buttons: `Use`, `In use`, `Download`, `Downloading…`, `NN%`, `Switching…`, `Too big`; error `Download failed: …`.
  - Built-in model id `qwen3.5-0.8b`.
* **API.** `POST/GET http://127.0.0.1:7860/v1/models/recommend | /download | /downloads (polled 1 s) | /select`. Changes apply immediately, not on Save.

### 3.7 Privacy dialog [O] 0x8bf7704–0x8bf7ca9

* **Window.** Title `heynixi Privacy & Data`, minimum width 600. Header "Your voice data, under your control".
* **Card "Local by default":** "Speech recognition, command routing, history, settings, and logs stay on this PC. heynixi does not retain microphone recordings; history is stored in your local database."
* **Card "When the network is used":** "Only for what you ask to reach the web: websites, searches, and Gmail drafts use their normal connection. Speech recognition, Write, answers, Polished, and screen reading all run on this PC - no audio, text, or screenshot is sent to a cloud AI service."
* **Card "What is kept":** "Verbatim conversation turns remain {for N days|forever}; session summaries may remain longer. Export creates a readable JSON copy. Clear permanently deletes history, memories, reminders, profiles, run events, and session summaries, but keeps settings, dictation personalization, and diagnostic logs."
* **Buttons:** `Export my data…`, `Clear history && memory…` (destructive), `Open diagnostic folder`, `Close`.
* **Export.**
  - Save dialog "Export heynixi data", default `~/Downloads/heynixi-data-YYYY-MM-DD.json`, filter "JSON files (*.json)".
  - Request: `GET /v1/data/export`. Results: "Export complete" / "Saved to:\n…" / "Export failed".
* **Clear.**
  - Confirm: "Permanently clear heynixi data?" / "This permanently deletes conversation history, memories, reminders, profile facts, run events, and session summaries. Settings and logs remain.\n\nThis cannot be undone."
  - Request: `POST /v1/data/clear {"confirmation":"CLEAR ALL NOTCH DATA"}`.
  - Results: "heynixi data cleared" / "History and memory were permanently deleted."; busy: "Finish the current action first" / "Stop listening or wait for the current action to finish before clearing data."
* **Diagnostics folder.** "Diagnostic files are stored at:\n…" [O] 0x8be4ab3–0x8be500e.

### 3.8 About dialog [O] 0x8baeafc

* **Contents.** Title `About heynixi`, minimum width 430, a 64-px `NixiBadge`, name `heynixi`, tagline "Your voice, in control.".
* **Build lines.** `Version X`, `\nBuild <commit[:12]>`, `\nBuilt <built_at>`, or `from source`. Values come from `BUILD-METADATA.json` (schema, product, version, commit, built_at).
* **Text.** "Command, Dictate and Write in one pill at the top of your screen. Speech and AI run on this PC." followed by `Local data: <dir>` and a `Close` button.

### 3.9 Misc HUD / app messages [O]

* **Hints and errors.**
  - Dictation: "Click into a text box first", "Click into the browser text field and try again", "Didn't catch that", "Couldn't insert text", "Dictation timed out".
  - Write: "Writing stopped", "Writing stopped because focus changed", "Writing stopped because the text field changed", "Couldn't return to the text field", "Couldn't return to the original text field", "Couldn't insert text. Click into the text field and try again.", "I didn't hear the instruction. Try again.", "Write needs attention", "Couldn't write", "Couldn't write that", "Writing is temporarily unavailable. Check System Check and try again.", "The writing service returned no text.", "The local writing model isn't ready yet. Give it a moment, then try again.", "Your PC is out of memory, so the writing model could not start. …".
  - Commands: "Not sure what to do with that", "Copy your script first, then say “start teleprompter”." (4200 ms).
  - Wake and safe mode: "“Hey Nixi” rests while battery saver is on" (3200 ms); safe mode: "heynixi had trouble starting, so “Hey Nixi”, the music card and extras are off for now. Restart heynixi to turn them back on." (9000 ms).
* **Drawer transcript.** `Heard: …`; an old session reads "That session — the words have aged out, only the title was kept."
* **Second launch.** "heynixi is already running - bringing it to the front."

---

## 4. Dictation pipeline

### 4.1 Flow (`NexusApp._dictation_press/_release`, `DictationTranscribeThread`, `insert_dictation_text`) [O]

1. **Key down** (Right Alt) or a click on the dictation glyph.
   - Capture the target synchronously with `win_foreground.get_foreground_target()`, which returns `ForegroundTarget(hwnd, pid, exe_path, focus_hwnd)` (focus_hwnd via `GetGUIThreadInfo`).
   - For browsers (`brave.exe, opera.exe, chrome.exe, msedge.exe, vivaldi.exe`) also capture a UIA **editor token** (`EditorFocusGuard.capture(timeout 0.08 s)`). If none: "Click into the browser text field and try again".
   - Show the pill within the **150 ms** budget. The app icon (`SHDefExtractIconW` → QImage) resolves afterwards on a thread.
   - Start `MicRecorder(on_level, on_speech_end, silence_ms=_DICTATION_SILENCE_MS)`; `NEXUS_DICTATION_SILENCE_MS` defaults to **2000**.
   - Log: `dictation press (ptt_active=… dictation_active=…)`.
2. **Key up.** Stop the recorder. Empty audio gives the `nothing` face.
   - Otherwise `DictationTranscribeThread` → `transcribe_wav()` = **`POST /v1/listen?mode=dictation`**, multipart `----nexusdictation`, field `file`=`dictation.wav` (audio/wav) plus `mode=dictation`, timeout 30 s; response `{"text": …}` [O] 0x8be059d–0x8be0987.
   - Then `DictationPersonalization.apply(transcript, mode, target, formatter)`, which runs the formatter.
3. **Polished.** `polish_dictation()` = `POST /v1/dictation/polish`, timeout `NEXUS_POLISH_TIMEOUT_S` (default 12, max 60). On any failure the deterministic Clean text is used [O] 0x8be0987.
4. **Job ordering.** Jobs are kept in spoken order (`_dictation_order`). Worker timeout is **95 s** for POLISHED and **35 s** otherwise ("Dictation worker timed out; releasing later utterances") [O] 0x8bea9bc.
5. **Insert** (`insert_dictation_text(text, target, restore_delay_ms=400, editor_guard)`):
   - `restore_foreground(hwnd, focus_hwnd)`: `IsWindow`; `IsIconic` → `ShowWindow(SW_RESTORE=9)`; `AttachThreadInput` (foreground ↔ target ↔ current); `BringWindowToTop`; `SetForegroundWindow`; `SetFocus(focus_hwnd)`; then **verify** that `GetForegroundWindow()==hwnd`.
   - Browser targets must also pass `EditorFocusGuard.matches(token, 0.05 s)`.
   - It **fails closed**: "dictation insert refused: no captured foreground target / could not restore hwnd=… / captured browser editor changed".
   - Then `ClipboardPaste.paste()` [O] 0x8bb3da1:
     - Snapshot all clipboard formats (`QMimeData`), `setText(text)`.
     - Remember `GetClipboardSequenceNumber()`.
     - `SendInput` Ctrl+V (`send_ctrl_v`).
     - After **400 ms**, restore the saved clipboard only if the sequence number is unchanged.
     - Consecutive dictations share the original saved clipboard.
     - If sequence numbers are unavailable the dictated text stays on the clipboard.
   - Paste is preferred over typing because "some IMEs and legacy edit controls drop or mis-time a WM_CHAR burst". `send_unicode_text` (KEYEVENTF_UNICODE `SendInput`) exists as a utility [O] 0x8c08de5, 0x8c08683.
6. **Click-started dictation.** It stops on a second click, on VAD end-of-speech, or on the "8s check". The 8 s check ends only takes with no speech (`_BTN_DICTATION_TIMEOUT_MS`); once speech is heard, VAD decides, up to the hard ceiling `_BTN_DICTATION_MAX_S` [O] 0x8beb223.
7. **Editor guard internals** (`app.editor_focus`) [O]:
   - One MTA UIA worker thread (`HeynixiEditorFocus`) with a queue of 1 and at most 64 leases. Read-only: it never changes focus or reads contents.
   - `capture_editable` accepts only an enabled, non-password element of ControlType Edit (50004) or Document (50030).
   - It walks up to 64 parents to check that the element belongs to the HWND.
   - Observed in the log: it failed to initialise (`No module named 'comtypes.stream'`) [O] nexus.log.

### 4.2 Modes (`app.dictation_formatter`, docstring 0x8bb6bc4) [O]

| Mode | Behaviour |
|---|---|
| **EXACT** | Interprets explicit formatting commands only and fixes spacing around them. Protected tokens kept |
| **CLEAN** (default) | EXACT + conservative spoken corrections (repairs), removal of hesitation fillers and adjacent stutters, sentence casing, implicit counted lists |
| **POLISHED** | CLEAN + explicitly-labelled list/steps/recipe structure + optional local rewriter. Rejected (falls back to CLEAN) on exception, empty or non-string output, loss of any protected value, or any new word not in an allow-list (`_SAFE_POLISH_ADDITIONS` = {the, an, a}; strippable model-added relations {then, together, it}) |

* **Pipeline order** (from `_format_dictation` 0x8bb6529, [I] order):
  1. `_coerce_mode`
  2. `_repair_spoken_number`
  3. `_exact` (`_normalize_spoken_domains` → `_render_numbered_items` → `_protect` → `_render_spoken_formats`)
  4. CLEAN steps: `_apply_corrections` → `_remove_fillers` → `_remove_repetitions` → `_finish_clean`
  5. `_implicit_spoken_list`
  6. POLISHED steps: `_explicit_polished_structure` / rewriter / `_strip_unspoken_relational_additions` / `_polished_content_is_preserved` / `_polished_fallback`
  7. `_restore`
* **Post-processing** (`format_dictation`): handle trailing `enter|new line|line break` and `new paragraph`, then "finish list punctuation after restoring protected numbers".

### 4.3 Spoken punctuation / layout map `_SPOKEN_FORMATS` [O] 0x8bb7c93

The pattern is `(?<!\w)…(?!\w)`, case-insensitive, and optional surrounding punctuation is absorbed (`_PUNCTUATION_FORMATS`).

| Say | Output |
|---|---|
| new paragraph | `\n\n` |
| new line / newline | `\n` |
| line break | `\n` |
| bullet / bullet point | `\n- ` |
| question mark | `?` |
| exclamation point / exclamation mark | `!` |
| full stop | `.` |
| open quote / close quote | `"` |
| semicolon | `;` |
| colon | `:` |
| comma | `,` |
| period | `.` |
| "coma" next to punctuation | `,` (ASR misspelling repair, `_STANDALONE_COMA_RE`) |
| enter (at end) | line break |

### 4.4 Other rules [O]

* **Fillers** `_FILLER_RE`: `(?<![\w'-])(?:uh+|um+|erm+|hmm+)(?![\w'-])`. The app-level `clean_dictation_text` also strips `\b(?:uh|um|erm|uhh)\b` and drops a result that is only filler.
* **Repair markers** `_CORRECTION_MARKER_RE` (0x8bb7a8f): `scratch that`, `scratch it`, `make that`, `actually make that`, `no, I mean`, `, actually …`, `… actually, …`. Bare "actually" without punctuation is left alone.
  - The edit scope is chosen by `_correction_start`: clause boundary, prepositions `At|In|On|To|For`, weekday/time phrases `(next|last|this) monday…tonight [at H[:MM] am/pm]`, and the last token.
  - Number repair: "<n> actually <m>" keeps the correction even when ASR inserts a false period.
* **Repetitions.** Adjacent repeated 4/3/2-word phrases and single words are collapsed, except the emphatic words {never, yes, way, no, very, so, really, had, that, much}.
* **Spoken domains.** `<label> [dot <middle>] dot <tld>` with tld ∈ com, org, net, io, ai, co, ca, dev, app, me, gg, tv, uk → `label.tld`. Personalization also joins `<user> at <domain> dot <tld>` into an email ("Join only a complete, simple address").
* **Numbered lists.** `number|item <one..ten|1-99>` markers produce `1. … 2. …`; markers inside protected values are ignored. Number words map one–ten to 1–10.
* **Implicit bullets** (CLEAN): `^(one..ten|2-9) (things|items|tasks|points|notes) (for|to|about) <title>[.:] <sentences>` → "title:" + `- ` bullets.
* **Explicit structure** (POLISHED):
  - List labels: `shopping list|grocery list|groceries|checklist|to-do (list)|task list:` with items split on `, ;`, and a trailing `and/or` merged.
  - Step labels: `steps|instructions|procedure|directions:` with sentences, or ordinals first…tenth/then/next/finally/lastly/after that, becoming numbered steps.
  - Recipes: `<title> ingredients: … steps|instructions|directions|method: …`.
  - Headings: lines like `Ingredients`, `Steps`, `Method`, `Recipe`.
* **Protected tokens** `_PROTECTED_RE` (VERBOSE, 0x8bb6ff3) are never altered: fenced and inline code, `func(...)`, URLs, emails, Windows paths, relative/POSIX paths, CLI flags, snake_case, dotted names, camelCase/PascalCase, `func()`, date/version tokens, `H:MM` times, numbers with currency/%/units. Placeholders use private-use chars `NEXUS…`.
* **Cleanup.** Sentence capitalisation, comma/space normalisation, lowercase after a comma for common continuation words (a large frozenset of conjunctions and pronouns, 0x8bb7b39 [I]), currency spacing `(?<=[A-Za-z])(?=[$€£¥]\d)`.

### 4.5 Personalization (`app.dictation_personalization`) [O] 0x8bb8225

* **Storage.** `<data_dir>/dictation-personalization.json` (schema'd, written atomically).
* **Sections.** `dictionary` {spoken→written}, `snippets` {trigger→text, multi-line}, `app_styles` {exe→style}.
* **Limits.** 100 entries; key 80 chars; value 4000 chars; exe regex `[a-z0-9_.-]{1,80}\.exe`; no control characters.
* **Dictionary.** Case-insensitive, whole-word, whitespace-flexible replacement. Longest keys first [I].
* **Brand fix.** `nixie|nixy|nixxi|nexi|nexie|nexy` → `Nixi`.
* **Snippets.** Expand only when the whole utterance is the trigger, or `insert <trigger>` / `type <trigger>`.
* **Per-app styles** `STYLES = (default, casual, formal, code)`:
  - `code` → EXACT
  - `casual` → CLEAN
  - `formal` → CLEAN + contraction expansion: can't→cannot, won't→will not, don't→do not, doesn't→does not, didn't→did not, i'm→I am, we're→we are, you're→you are, they're→they are (case-preserving, outside protected spans)
  - `default` → the global mode
  - The style is looked up by the **target's exe basename captured at mic-start**. **No built-in app→style mapping ships; it is entirely user-defined** [O] (empty defaults; "deterministic per-app Casual/Formal/Code styles" in SUPPORTED_FEATURES.md).

### 4.6 Write mode (related insertion path) [O] 0x8be0c18, 0x8bebc4d

* **Request.** The pen click captures the target and records an instruction (silence `_WRITE_SILENCE_MS`). If text is selected, it is read through UIA TextPattern (`app.selection.selected_text(pid, max 20000 chars)`). Then `POST /v1/write/stream` `{instruction, selected_text, source, pid}`, streamed in 96–100-byte reads.
* **Insertion.** Chunks are pasted a few complete words at a time (`_next_write_piece`, limit 28 chars, `NEXUS_WRITE_CHAR_MS`=100 ms tick). Writing stops if foreground or field ownership changes.

---

## 5. Audio

### 5.1 Capture (`app.audio`, `app.audio_device`) [O]

* **Format.** **16 kHz, mono, int16**, `blocksize=1280` (80 ms). Recordings are WAV (44-byte header).
  - Observed: `session audio: bytes=51244` = 44 + 25,600 samples × 2 = 1.6 s.
  - Observed: `microphone opened: device=None … rate=16000 channels=1 recognition_rate=16000`.
* **Device.** `NEXUS_AUDIO_DEVICE` selects by index or name (case-folded exact or partial).
  - Choices are de-duplicated per physical mic: WASAPI preferred, hiding "Microsoft Sound Mapper - Input" / "Primary Sound Capture Driver".
  - If 16 kHz is rejected, it retries same-name endpoints, then the native rate.
  - Resampling is done by `_CaptureConverter`: a 63-tap windowed-sinc (Hamming) low-pass at 0.95·Nyquist plus linear interpolation, down-mixed to mono.
  - Error text: "The microphone could not start. Check Windows microphone permissions, then choose your microphone in heynixi Settings."
* **MicRecorder.**
  - Per-block RMS → level 0..1 via `min(1, rms/6000)` for the HUD meter.
  - A VAD worker thread `nexus-vad` reads a queue of 8 and feeds the `SpeechGate`.
  - API: `snapshot()` (WAV without stopping, for partial polling), `consume()` (drops fired audio), `stop(tail_s)`.
  - Key-release tail: `KEY_RELEASE_TAIL_S` ≈ **0.3 s** [I]. The logs show ≈ 4 frames between total frames and gate frames on every take.
  - `seconds` length is the hard cap independent of content.
* **Player.** Non-blocking playback; a new clip cuts off the old one. Push-to-talk press interrupts playback (the only "barge-in"). **TTS is disabled by design**: `_speak()` is a no-op ("JEV-style: chime + pill only") [O] 0x8bef1a3.

### 5.2 VAD (`app.vad` SpeechGate, `app.silero_vad`) [O] 0x8c049fe, 0x8bfcfbc

| Parameter | Value |
|---|---|
| Model | `runtime/models/silero_vad.onnx` (or `NEXUS_SILERO_VAD_MODEL`); onnxruntime CPU, 1 thread; state h/c; prediction buffer 125 |
| Frame | **1280 samples** (80 ms), split internally (`predict` frame_size 480, `__call__` 640) and averaged |
| `SPEECH_THRESHOLD` (module default) | **0.5** |
| `CAPTURE_SPEECH_THRESHOLD` (used by MicRecorder) | **0.3** (log `threshold=0.300`) |
| `DEFAULT_SILENCE_MS` | **900** |
| `MIN_SPEECH_MS` | **200** (speech must persist 200 ms before it counts) [I] pairing |
| Command silence timeout | `NEXUS_SILENCE_TIMEOUT_S` = **2.0 s** (UI 1–10 s) → `MicRecorder(silence_ms=2000)` |
| Dictation silence | `NEXUS_DICTATION_SILENCE_MS` = **2000** |
| Max utterance | `NEXUS_MAX_UTTERANCE_S` = **20 s** (`too_long`) |
| Max session | `NEXUS_MAX_SESSION_S` = **90 s** |
| Stats | `peak_probability`, `max_speech_run`, `peak_rms`, `frames_processed`, `inference_errors`. Log: `speech gate at end: heard=%s peak=%.3f threshold=%.3f max_run=%d rms=%.1f frames=%d errors=%d` |

* **Hysteresis.** The session ends only after a continuous silence of `silence_ms`, and only once speech has been heard. `push()` returns True once per session.
* **`_on_speech_end` subtlety.** End on pause only if nothing has fired yet; mid-chain, the silence timeout and follow-up window decide (docstring 0x8be7434).

### 5.3 Push-to-talk / modes / hotkeys (`app.hotkeys`) [O]

* **Defaults.** `DEFAULT_PTT_KEY='right ctrl'`, `DEFAULT_PANEL_KEY='f9'` (combos allowed, e.g. `ctrl+shift+n`), `DEFAULT_DICTATION_KEY='right alt'`. Env: `NEXUS_PTT_KEY`, `NEXUS_PANEL_KEY`, `NEXUS_DICTATION_KEY`.
* **Hook.** A raw `WH_KEYBOARD_LL` hook on its own thread (`nexus-hotkeys`) with its own `GetMessageW` pump. Install timeout 5 s. Signals: `ptt_press/release`, `panel_toggle`, `dictation_press/release`, `escape_press`.
  - Auto-repeat is ignored (edge detection).
  - Generic modifier equivalents: 17→162/163, 16→160/161, 18→164/165.
* **Alt suppression.** A bare Right-Alt release is swallowed and a masked key (VK 0xE8) is injected so the menu bar does not activate; `_ALT_VKS` = {164,165,18,91,92}.
* **Key names.** ctrl/left ctrl/right ctrl, shift…, alt/alt gr, win, space, tab, enter, esc, backspace, delete, insert, home, end, page up/down, arrows, caps lock, print screen, pause, scroll lock, f1–f24, a–z, 0–9.
* **Modes.** `NEXUS_PTT_MODE` ∈ {`hold`, `toggle`}. In hold mode release ends the utterance (`reason='released'`); in toggle mode release does nothing and a second press or silence ends it.
* **Mid-sentence execution.** Every `NEXUS_PARTIAL_MS`=**250 ms** the app posts a snapshot (≥ `_PARTIAL_MIN_BYTES`=9600 B = 0.3 s) to `/v1/listen/partial`, one request in flight at a time.
  - Only "terminal" phrases fire early: `^(close|quit|mute|unmute|pause|play|next|previous|volume \w+|take a (screenshot|photo|picture)|lock)$`, at most 5 words, never ending in {to, for, up, write, type, about, and, search, then, with}.
  - App opens wait for the final transcript, except clauses already passed ("early open").
  - The displayed transcript only moves forward (`_TRANSCRIPT_HOLD_POLLS`).
* **Final command.** `POST /v1/listen/start {audio_b64, conversation_id, final, wake_triggered}`. Text commands go to `POST /v1/chat`.
* **Escape.** Escape closes the teleprompter.
* **Panel key.** F9 = `toggle_log` opens or closes the drawer.

### 5.4 Wake phrase (`app.wake_phrase`, `engine.nexusd.wake_config`) [O] 0x8c055fc, 0x8d607af

* **Approach.** Not a keyword spotter. The VAD-gated **burst collector** waits for a burst of speech, transcribes it through the engine, and string-matches the opening words.
  - Licence reason: openWakeWord models are CC BY-NC-SA.
  - Endpoint: `POST /v1/listen`, multipart `----nexuswake`, `file=burst.wav`, `mode=wake`, timeout 20 s.
  - The remainder after the phrase is routed as the command (one breath).
* **Phrase and matching.**
  - Phrase: `NEXUS_WAKE_PHRASE` (default **`hey nixi`**; "" / off / none / disabled = off).
  - Similarity: `NEXUS_WAKE_SIMILARITY` default **0.82** (floor 0.4). Short phrases need more evidence (constants 0.95/0.06/0.97/0.2/0.13).
  - Matching: difflib `SequenceMatcher` over the opening words; leading fillers {um, okay, ok, so, uh, erm, well} are skipped; only the opening is considered.
* **Aliases** `WAKE_ALIASES['hey nixi']`: hey nixi, hey nexi, hey nexie, hey nixy, hey nixie, hey nicksy, hey nicky, a nixi, ay nixi, hey nick see, hey nizy, hey nissy, hey nexty, hey nextie. A legacy 'hey notch' alias set also exists.
* **Timing.**
  - `MAX_BURST_S`=9.0, `PREROLL_S`=0.45, rolling handoff 0.7 s (`recent_audio_frames(0.7)`), stale handoff 3.0 s, wake queue 32, diagnostics every 5 s.
  - In-speech checks (`IN_SPEECH_MIN_S/PERIOD_S/MAX_BURST_S/WINDOW_S/END_OF_BURST_SKIP_S`) use the values {0.6, 2.5, 0.4, 2.0…}; per-check transcribe timeout 6 s; end-of-burst `MIN_BURST_S` and 4.0 [I?].
  - A mid-burst detection fires early; otherwise the completed burst is transcribed.
* **Logs.** `wake phrase heard`, `… mid-burst`, `wake phrase not detected in …`, and the opt-in `NEXUS_WAKE_DIAGNOSTICS=1` line.
* **Session after wake** (`_start_wake_session`, `_end_session`, `_should_follow_up`) [O]:
  - The wake listener releases the mic, plays the **wake chime** (volume ×1.4; skipped for pill clicks), calls `begin_listening`, and pre-rolls 0.7 s of frames.
  - Session end reasons: `released`, `stopped`, `wake_quiet`, `too_long`, `dictation_takeover`, `done`, `teleprompter`.
  - Follow-up window: `NEXUS_FOLLOWUP_S`, extended on new speech but never past the session ceiling. The quiet close is `NEXUS_WAKE_QUIET_S`. No follow-up after stop / too_long / ceiling, nor for push-to-talk.
  - Observed: a click-started session with silence ended `reason='wake_quiet'` after ~2 s (log 12:14:16–12:14:18).
* **Pauses.** The wake listener pauses on screen lock (`OpenInputDesktop` ≠ "Default"), on battery saver, and while the mic is busy, and reopens after resume from sleep (`_RESUME_GAP_S`, delay 3 s) [O] `app.system_events`.

### 5.5 Chimes (`app.chime`) [O] 0x8bb27f4

* **Synthesis.** The tone is synthesised, no WAV shipped: SR 48 kHz, length 0.55 s, attack 4 ms, release 40 ms. Partials (mult, amp, decay): (1, 1.0, 0.2), (2, 0.22, 0.13), (3, 0.06, 0.09).
* **Notes:**
  - **done**: 880 Hz at t=0, then 1318.51 Hz at +75 ms (A5 → E6).
  - **wake**: 659.25 Hz, then 987.77 Hz at +70 ms (E5 → B5).
* **Playback.** Own `OutputStream`, never `sd.play`. Falls back to `winsound.PlaySound` on a temp WAV `%TEMP%\notch_chime_*.wav`.
* **Behaviour.** Non-blocking, never raises, "quiet by default" (`NEXUS_CHIME_VOLUME`). `NEXUS_CHIME=0` turns it off. The wake chime is skipped if another chime is playing.
* **Echo guard.** Transcripts of only {ding, bong, dink, boop, beep, ping, bing} within 0.6 s of a chime are ignored (`_is_chime_echo`).

### 5.6 Output meter (`app.output_meter`) [O] 0x8bf6433

* **Source.** pycaw `IAudioMeterInformation.GetPeakValue()` on the default speakers, read once per frame on the Qt thread. Re-bound every 5 s (`_REBIND_S`). No capture or loopback.
* **Use.** Drives the dance sway only.

---

## 6. Other modules

### 6.1 Teleprompter (`app.teleprompter`, HUD prompter mode) [O] 0x8c006be

* **Start.** "start teleprompter" (engine tool `teleprompter.start`, or tray `Teleprompter`). The script comes from the **clipboard**. An empty clipboard gives "Copy your script first…".
* **Strip.** The pill widens to `_PROMPT_W` (≈ 0.6 of the screen width [I]) with a 4-line strip (`_PROMPT_LINES`).
  - The current line is kept second from the top.
  - Read words turn grey; the next word sits on a blue highlight that breathes with the mic.
  - A level meter shows "Listening  ·  NN%".
  - Labels: `Start reading — I’ll follow`, `Paused`, `Done`.
* **Recognition loop.** `_Listener` runs its own 16 kHz InputStream, a 2.0 s rolling window, transcribed every 0.25 s (`TICK_S`). The voice gate is RMS > 2500 (`VOICE_LEVEL` 0.12, `VOICE_HOLD_S` 0.35).
* **Tracking.** `ScriptTracker` aligns the tail of the recognised words to the script, preferring forward matches and allowing a little backward (constants 8 / 60 / 24, `MIN_MATCH`).
* **Pace.** `ReadingPace` advances at the measured reader pace, capped at `LEAD` words past the evidence, and holds on pause. Constants: 6, 2.5, 3.0, rates 0.2–…; pace timer 80 ms.
* **Controls.** Tap the pill to pause/resume; ✕ or "stop/close/end/exit/quit (the) teleprompter" closes it; Esc closes it. Done hold 2000–2500 ms.
* **Capture exclusion.** The window is excluded from screen capture while reading (see 1.2).

### 6.2 Pointer overlay ("show me where to click") (`app.pointer_overlay`) [O] 0x8bf6b20

* **Trigger.** Engine event `screen.point` → `_point_at(target)`. A thread (`nixi-pointer`) calls `engine.nexusd.tools.ui_agent.find_control` → `show_pointer(rect)`.
* **Window.** Frameless, topmost tool window with `WindowTransparentForInput` and `WindowDoesNotAcceptFocus`; translucent and click-through. The rect is in UIA screen pixels divided by devicePixelRatio.
* **Drawing.** A rounded ring (padding `_PAD`, alpha pulse sin, 5 Hz), accent (59,130,246), plus a white `Click here` chip (Segoe UI 10 bold, chip height 26). Hold `_HOLD_S` ≈ 4.0 s, then a 0.4 s fade. 16 ms tick. It never clicks.

### 6.3 Startup guard / hang watch [O]

* **startup_guard.** `<data_dir>/startup-guard.json {"unfinished": n}`.
  - `begin()` increments the counter. With `FAILED_STARTS_FOR_SAFE_MODE=2` unfinished starts, the next run sets `NEXUS_SAFE_MODE=1`, which disables the wake mic stream, the media reader, the PC-events watcher, the full-screen watcher and the outfit.
  - `mark_healthy()` runs after `HEALTHY_AFTER_MS=60000` or on a clean quit.
  - Log: `startup guard: %d unfinished starts, starting in safe mode`.
* **hang_watch.**
  - Heartbeat: a 1 s UI `QTimer` (`hang-watch` thread). After `HANG_AFTER_S=8.0` without a beat it writes `logs/hang-YYYYmmdd-HHMMSS.txt`: Python stacks plus the Windows Wait Chain of the UI thread (`OpenThreadWaitChainSession`/`GetThreadWaitChain`, object-type names table). Keeps `_MAX_REPORTS=10`.
  - Native backstop: `faulthandler.dump_traceback_later(12.0 s, repeat)` into `logs/hang-stacks.txt` (max 2 MB), re-armed every 4 s.
  - Logs: `UI thread unresponsive for %.1fs - details in %s` / `UI thread responsive again`.

### 6.4 Autostart (`app.autostart`) [O] 0x8bb1a94

* **Registry entry.** `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value name **`heynixi`**, `REG_SZ` = `"<path>\heynixi.exe"` (quoted).
* **Scope.** Only when packaged and `uninstall.exe` sits beside the exe. `sync(enabled)` adds or deletes the value to match. The setting "Start heynixi when I sign in" defaults to on. The uninstaller removes it.

### 6.5 Updater (`app.updater`) [O] 0x8c03914 — foundation only, no release server

* **Manifest** (JSON, ≤ 65,536 bytes, UTF-8):

```json
{
  "schema": 1, "product": "heynixi",
  "installer": { "version": "X.Y.Z", "published_at": "...", "url": "https://...",
                 "bytes": <int, ≤ MAX_INSTALLER_BYTES>, "sha256": "<64 hex>" },
  "signature": { "algorithm": "ed25519", "value": "<base64>" }
}
```

* **Signature.** Ed25519 over the canonical JSON of the document *without* `signature`: `json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=False)`, UTF-8.
* **Validation.**
  - Version regex `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`; it must be newer than the current version.
  - The URL must be HTTPS with no credentials or fragment.
* **Staging.**
  - Download with `User-Agent: heynixi-Updater/1`, 60 s timeout, 1 MiB blocks, Content-Length checked, into `<data_dir>/updates/<version>/heynixi-Setup-<v>.exe` (temporary `.download`).
  - Check SHA-256 and size.
  - Check Authenticode with `powershell Get-AuthenticodeSignature`, which must return `Valid`.
  - Never installs itself.

### 6.6 System events (`app.system_events`) [O]

* **Polling.** Every 2 s: lock state (`OpenInputDesktop`/`GetUserObjectInformationW` name ≠ Default), `GetSystemPowerStatus` (has_battery, plugged, percent, saver), and resume (timer gap `_RESUME_GAP_S` = 20 s [I]).
* **Folder watch.** `QFileSystemWatcher` on Downloads `{374DE290-…}` and Screenshots `{B7BEDE81-…}`, with a 600 ms debounce. Partial-download suffixes are ignored (`.part .crdownload .opdownload .tmp .aria2 .download .partial .!ut`). Screenshots must be `.png/.jpg/.jpeg`.
* **Signals:** `locked_changed`, `saver_changed`, `charger_changed`, `resumed`, `download_finished`, `screenshot_taken`. These drive mascot reactions and wake pauses.

### 6.7 Process and engine wiring (`app.nexus_app`) [O]

* **Single instance.** TCP bind on `127.0.0.1:7861` (`NEXUS_SINGLETON_PORT`); a second launch sends `b'show'`. AppUserModelID `notch.app`.
* **Engine.** `http://127.0.0.1:7860` (`NEXUS_PORT`). Websocket `ws://127.0.0.1:7860/v1/events` (ping 20 s / timeout 10 s, reconnect backoff 3→12 s).
* **Client log.** `%LOCALAPPDATA%\heynixi\logs\client.log`, format `%H:%M:%S message`, rotating (1 MB × 3, `NEXUS_CLIENT_LOG_MAX_BYTES/BACKUPS`).
* **Event types handled:** `agent.step`, `reminder.due`, `focus.done`, `pill.notify`, `ping`, `run.state`, `state.changed`, `assistant.message` (kind action/answer), `media.now_playing`, `assistant.plan`, `assistant.tool`, `tool.result`, `screen.point`, `teleprompter.start/stop`, `input.send_keys` (media keys keep the music card up), `reminder.clear`, `run.ended`.
* **REST used by the client:** `/ready`, `/v1/listen/start`, `/v1/listen/partial`, `/v1/listen` (wake + dictation), `/v1/dictation/polish`, `/v1/write/stream`, `/v1/chat`, `/v1/confirm`, `/v1/tts` (unused), `/v1/sessions?limit=40`, `/v1/sessions/<id>`, `/v1/data/export`, `/v1/data/clear`, `/v1/models/*`.
* **Spoken-reply budget.** `NEXUS_SPEECH_WORDS`=28, though TTS is off. History: `NEXUS_HISTORY_DAYS`=30.

---

## 7. Observed runtime sequence (client.log, 2026-10-21)

```
wake listener started: phrase='hey nixi' backend=PhraseWakeListener
hotkeys: ptt='right ctrl' panel='f9' dictation='right alt' mode='hold'
first-run check: marker=…\onboarding-v2.done present=False -> setup guide opened (first_run=True)
ptt press (active=False mode=hold) -> recording started -> session end (reason='released' followup=False)
speech gate at end: heard=True peak=0.756 threshold=0.300 max_run=4 rms=482.9 frames=16 errors=0
session audio: bytes=51244 fired_any=False -> final transcript: chars=9 ran=0 deliberate=True
indicator clicked (ptt_active=False) -> … session end (reason='wake_quiet') (no speech, ~2 s)
```

* **HUD pattern in nexus.log:** `leaving rest` on press, then `fade_out -> 1.00` ~8–12 s later, then `entering rest`.
* **Unrelated engine failure:** the bundled LLM server crashed (0xC0000005) and returned 503 on `/api/chat`.

## 8. Open questions / unresolved constants

* **HUD names:** exact pairing of `_FADE_IN_MS`, `_FADE_OUT_MS`, `_MORPH_OPEN_MS`, `_MORPH_CLOSE_MS`, `_MORPH_OVERSHOOT`, `_SPRING_K`, `_SPRING_ZETA`, `_R_CLOSED`, `_R_OPEN`, `_HOLD_MS_LONG`, `_DRAWER_W` and `_EXPANDED_H` against the raw module tail (780, 1.32, 22, 32, 420, 7, 80, 170, 16, 33.0, 160, 1.2, 1.06, 760, 0.82).
* **Wake worker constants:** `IN_SPEECH_*`, `END_OF_BURST_SKIP_S` and `MIN_BURST_S`.
* **Follow-up and quiet timers:** `NEXUS_FOLLOWUP_S` and `NEXUS_WAKE_QUIET_S`. They are read as floats; the defaults are probably among the 4.0/5.0 class constants [I?].
* **Next step:** a bytecode-level Nuitka decompile (REA) would settle all of these if needed.
