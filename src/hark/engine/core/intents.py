"""Deterministic command grammar.

Each rule maps a spoken pattern to a tool call. Rules are tried in order and
the first match wins, so more specific phrasings come first. Anything that
matches nothing falls through to the language model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from hark.engine.tools.timeparse import words_to_number


@dataclass
class Intent:
    tool: str
    args: dict = field(default_factory=dict)
    phrase: str = ""


_POLITE = re.compile(
    r"^(?:(?:hey |ok(?:ay)? |hi )?hark[,.!]?\s*)?(?:(?:can|could|would|will) you\s+|please\s+|i want you to\s+|"
    r"i(?:'d| would) like (?:you )?to\s+|go ahead and\s+)*",
    re.I,
)
_TRAIL = re.compile(r"(?:\s*,?\s*(?:please|for me|thanks|thank you|now))+\s*[.!?]*$", re.I)


def normalise(text: str) -> str:
    text = text.strip().strip(" .!?")
    text = _POLITE.sub("", text, count=1)
    text = _TRAIL.sub("", text)
    return " ".join(text.split())


def _num(token: str) -> int:
    return int(words_to_number(token))


Rule = tuple[re.Pattern, Callable[[re.Match], Intent | None]]
RULES: list[Rule] = []


def rule(pattern: str):
    compiled = re.compile(pattern, re.I)

    def register(fn: Callable[[re.Match], Intent | None]):
        RULES.append((compiled, fn))
        return fn

    return register


N = r"(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|a hundred)"

# ---- greetings, thanks, small talk ----------------------------------------------
@rule(r"^(?:good morning|morning|start my day briefing|(?:give me )?(?:my |the )?(?:daily )?briefing)$")
def _briefing(m):
    return Intent("briefing.daily")


@rule(r"^(?:thanks|thank you|cheers|nice work|good job|well done|you're the best|love you)(?: so much)?(?: hark)?$")
def _thanks(m):
    return Intent("persona.thanks")


@rule(r"^(?:what(?:'s| is) the time|what time is it|time|tell me the time)(?: now| right now)?$")
def _time(m):
    return Intent("system.time")


@rule(r"^(?:what(?:'s| is) (?:the |today's )?date|what day is (?:it|today)|today's date)(?: today)?$")
def _date(m):
    return Intent("system.date")


# ---- memory -----------------------------------------------------------------------
@rule(r"^remember (?:that )?(.+)$")
def _remember(m):
    return Intent("memory.remember", {"fact": m.group(1)})


@rule(r"^(?:what do you (?:remember|know) about me|what do you remember|what have you remembered|list (?:my )?memories)$")
def _memories(m):
    return Intent("memory.list")


@rule(r"^forget (?:about |that )?(.+)$")
def _forget(m):
    return Intent("memory.forget", {"needle": m.group(1)})


# ---- reminders ----------------------------------------------------------------------
@rule(r"^(?:remind me|ping me|nudge me|alert me|set a reminder|create a reminder|reminder)\b(.*)$")
def _remind(m):
    return Intent("reminder.add", {"text": m.group(1).strip()})


@rule(r"^(?:what are |show |list )?(?:my )?(?:upcoming )?reminders$")
def _reminders(m):
    return Intent("reminder.list")


@rule(rf"^(?:set (?:a |an )?)?(?:timer|alarm) for {N} ?(seconds?|minutes?|hours?)$")
def _timer(m):
    return Intent("reminder.add", {"text": f"in {m.group(1)} {m.group(2)} timer done"})


@rule(rf"^(?:set (?:a |an )?)?{N} ?(seconds?|minutes?|hours?) timer$")
def _timer2(m):
    return Intent("reminder.add", {"text": f"in {m.group(1)} {m.group(2)} timer done"})


# ---- tasks --------------------------------------------------------------------------
@rule(r"^(?:add|put) (.+?) (?:to|on) (?:my |the )?(?:to-?do(?: list)?|todo(?: list)?|tasks?(?: list)?|list)$")
def _task_add(m):
    return Intent("task.add", {"title": m.group(1)})


@rule(r"^(?:add (?:a )?task|new task|create (?:a )?task|add (?:a )?to-?do)[:,]? (.+)$")
def _task_add2(m):
    return Intent("task.add", {"title": m.group(1)})


@rule(r"^(?:what(?:'s| is| are) (?:on )?my (?:to-?do(?: list)?|todo(?: list)?|tasks?(?: list)?)|show (?:me )?my (?:to-?dos?|tasks?)(?: list)?|(?:my )?(?:to-?do|task) list|list (?:my )?tasks)$")
def _task_list(m):
    return Intent("task.list")


@rule(r"^(?:mark|tick|check off|cross off|complete|finish|i (?:finished|did|completed))(?: the)? "
      r"(?!(?:my |the )?(?:focus|pomodoro|deep work)\b)(.+?)(?: task)?(?: as)?(?: done| complete| completed| off)?$")
def _task_done(m):
    return Intent("task.complete", {"needle": m.group(1)})


@rule(r"^(?:clear|remove|delete) (?:all )?(?:the )?(?:completed|done|finished) tasks$")
def _task_clear(m):
    return Intent("task.clear_completed")


# ---- notes --------------------------------------------------------------------------
@rule(r"^(?:take|make|add|jot down|write down) (?:a )?(?:quick )?note[:,]?(?: that| saying)? (.+)$")
def _note(m):
    return Intent("note.add", {"body": m.group(1)})


@rule(r"^(?:jot down|write down|note down)(?: that)? (.+)$")
def _note_jot(m):
    return Intent("note.add", {"body": m.group(1)})


@rule(r"^note (?:that |to self )?(.+)$")
def _note2(m):
    return Intent("note.add", {"body": m.group(1)})


@rule(r"^(?:search|find|look up|look for) (?:my )?notes? (?:for |about )?(.+)$")
def _note_search(m):
    return Intent("note.search", {"query": m.group(1)})


@rule(r"^(?:show|read|list|open) (?:me )?(?:my )?(?:recent |last )?notes$|^what are my notes$")
def _note_list(m):
    return Intent("note.list")


# ---- habits & focus ------------------------------------------------------------------
@rule(r"^(?:log|track|mark) (?:my |the )?(.+?) (?:habit|for today|as done today)$|^(?:log|track) habit (.+)$")
def _habit(m):
    return Intent("habit.log", {"name": m.group(1) or m.group(2)})


@rule(r"^(?:how(?:'s| is) my|what(?:'s| is) my) (.+?) streak$")
def _streak(m):
    return Intent("habit.streak", {"name": m.group(1)})


@rule(rf"^(?:start|begin) (?:a |an )?(?:{N}[- ]minute )?(?:focus|pomodoro|deep work)(?: session| timer| mode)?(?: for {N} minutes)?(?: (?:on|for) (.+))?$")
def _focus(m):
    minutes = m.group(1) or m.group(2)
    return Intent("focus.start", {"minutes": _num(minutes) if minutes else 25, "label": m.group(3)})


@rule(r"^(?:stop|end|cancel|finish) (?:the |my )?(?:focus|pomodoro|deep work)(?: session| timer| mode)?$")
def _focus_stop(m):
    return Intent("focus.stop")


# ---- routines -------------------------------------------------------------------------
@rule(r"^(?:create|make|save|set up) (?:a )?routine (?:called|named) (.+?)(?:[:,]\s*| (?:to|that|which|will) )(.+)$")
def _routine_save(m):
    return Intent("routine.save", {"name": m.group(1), "steps": m.group(2)})


@rule(r"^(?:run|start|do) (?:the |my )?routine (.+)$|^(?:run|start|do) (?:my )?(.+?) routine$")
def _routine_run(m):
    return Intent("routine.run", {"name": m.group(1) or m.group(2)})


@rule(r"^(?:list|show|what are) (?:my )?routines$")
def _routines(m):
    return Intent("routine.list")


# ---- agent mode ------------------------------------------------------------------------
@rule(r"^(?:take care of this|handle this|take care of it|do this for me)[:,]?\s+(.+)$")
def _agent(m):
    return Intent("agent.run", {"goal": m.group(1)})


# ---- volume & media ---------------------------------------------------------------------
@rule(rf"^(?:set |change |put )?(?:the )?volume (?:to|at) {N}(?: ?%| percent)?$")
def _vol_set(m):
    return Intent("volume.set", {"percent": _num(m.group(1))})


@rule(rf"^(?:turn |crank )?(?:the )?(?:volume|sound) (up|down)(?: by {N}(?: ?%| percent)?)?$|^(?:turn it |make it )?(louder|quieter|softer)$")
def _vol_change(m):
    direction = (m.group(1) or m.group(3)).lower()
    step = _num(m.group(2)) if m.group(2) else 10
    return Intent("volume.change", {"delta": step if direction in ("up", "louder") else -step})


_NOT_DICTATED = r"^(?!(?:type|write|draft|note|remind|add|search|google|reply|respond|tell)\b)"


@rule(_NOT_DICTATED + r".*\b(?:too loud|so loud|too noisy|hurting my ears|turn it down)\b")
def _too_loud(m):
    return Intent("volume.change", {"delta": -20})


@rule(_NOT_DICTATED + r".*\b(?:can(?:'t| not|not) hear|(?:can )?barely hear|too quiet|too soft|turn it up)\b")
def _too_quiet(m):
    return Intent("volume.change", {"delta": 20})


@rule(r"^(?:mute|silence)(?: the)?(?: volume| sound| audio| computer| pc)?$")
def _mute(m):
    return Intent("volume.mute", {"muted": True})


@rule(r"^unmute(?: the)?(?: volume| sound| audio| computer| pc)?$")
def _unmute(m):
    return Intent("volume.mute", {"muted": False})


@rule(r"^(?:what(?:'s| is) the volume|current volume)$")
def _vol_get(m):
    return Intent("volume.get")


@rule(r"^(?:pause|resume|play|unpause|stop)(?: the)?(?: music| song| video| playback| it)?$")
def _play_pause(m):
    return Intent("media.key", {"action": "play_pause"})


@rule(r"^(?:next|skip)(?: this)?(?: track| song| one)?$|^skip(?: this)?(?: track| song)?$")
def _next(m):
    return Intent("media.key", {"action": "next"})


@rule(r"^(?:previous|last|go back(?: to the)?)(?: track| song)$|^previous$")
def _prev(m):
    return Intent("media.key", {"action": "previous"})


@rule(r"^(?:what(?:'s| is) (?:playing|this song)|what song is (?:this|playing)|who(?:'s| is) (?:singing|playing)|now playing)$")
def _now_playing(m):
    return Intent("media.now_playing")


# ---- keys & typing -----------------------------------------------------------------------
@rule(r"^(?:press|hit|push|tap) (?:the )?(.+?)(?: key| button)?(?: (\w+) times)?$")
def _press(m):
    return Intent("input.keys", {"keys": m.group(1), "times": _num(m.group(2)) if m.group(2) else 1})


@rule(r"^(?:type|type out|enter)[:,]? (.+)$")
def _type(m):
    return Intent("input.type", {"text": m.group(1)})


@rule(r"^(?:copy|copy that|copy this)$")
def _copy(m):
    return Intent("input.keys", {"keys": "ctrl c"})


@rule(r"^(?:paste|paste it|paste that)$")
def _paste(m):
    return Intent("input.keys", {"keys": "ctrl v"})


@rule(r"^(?:undo|undo that)$")
def _undo(m):
    return Intent("input.keys", {"keys": "ctrl z"})


@rule(r"^(?:select all|select everything)$")
def _select_all(m):
    return Intent("input.keys", {"keys": "ctrl a"})


@rule(r"^(?:save|save (?:this|it|the file))$")
def _save(m):
    return Intent("input.keys", {"keys": "ctrl s"})


@rule(r"^(?:new tab|open (?:a )?new tab)$")
def _new_tab(m):
    return Intent("input.keys", {"keys": "ctrl t"})


@rule(r"^(?:close (?:this |the )?tab)$")
def _close_tab(m):
    return Intent("input.keys", {"keys": "ctrl w"})


@rule(r"^(?:minimi[sz]e|hide)(?: this| the)?(?: window| app)?$")
def _minimise(m):
    return Intent("window.minimise")


@rule(r"^(?:maximi[sz]e)(?: this| the)?(?: window| app)?$")
def _maximise(m):
    return Intent("window.maximise")


@rule(r"^(?:show (?:the )?desktop|minimi[sz]e everything)$")
def _desktop(m):
    return Intent("input.keys", {"keys": "windows d"})


@rule(r"^(?:take a screenshot|screenshot|capture (?:the )?screen)$")
def _screenshot(m):
    return Intent("input.keys", {"keys": "windows shift s"})


# ---- system ---------------------------------------------------------------------------------
@rule(r"^(?:how(?:'s| is) (?:my |the )?(?:battery|computer|pc|system)(?: doing)?|battery(?: level| status)?|system (?:stats|status)|how much (?:ram|memory|cpu)(?: am i using| is (?:in use|being used))?|cpu usage|memory usage)$")
def _stats(m):
    return Intent("system.stats")


@rule(r"^lock (?:the |my )?(?:screen|computer|pc)$")
def _lock(m):
    return Intent("system.lock")


@rule(r"^(?:shut ?down|turn off) (?:the |my )?(?:computer|pc)$|^shut ?down$")
def _shutdown(m):
    return Intent("system.shutdown")


@rule(r"^(?:restart|reboot) (?:the |my )?(?:computer|pc)$")
def _restart(m):
    return Intent("system.restart")


# ---- teleprompter & look ---------------------------------------------------------------------
@rule(r"^(?:start|open|show) (?:the )?teleprompter$")
def _prompter(m):
    return Intent("teleprompter.start")


@rule(r"^(?:stop|close|hide) (?:the )?teleprompter$")
def _prompter_stop(m):
    return Intent("teleprompter.stop")


@rule(r"^(?:change|switch|set) (?:your )?(?:colou?rs?|look|theme) to (\w+)$")
def _look(m):
    return Intent("look.set", {"look": m.group(1).lower()})


# ---- web & apps (last: "open X" is the broadest pattern) ---------------------------------------
@rule(r"^(?:search|look up|google) (?:for )?(.+?) on (google|youtube|bing|amazon|wikipedia|github|maps|reddit|spotify|images)$")
def _search_on(m):
    return Intent("web.search", {"query": m.group(1), "engine": m.group(2).lower()})


@rule(r"^(?:search (?:on )?|look up on )(google|youtube|bing|amazon|wikipedia|github|maps|reddit|spotify)(?: for)? (.+)$")
def _search_on2(m):
    return Intent("web.search", {"query": m.group(2), "engine": m.group(1).lower()})


@rule(r"^(?:play|watch) (.+?) on youtube$")
def _youtube(m):
    return Intent("web.search", {"query": m.group(1), "engine": "youtube"})


@rule(r"^(?:google|search for|search the web for|search|look up) (.+)$")
def _search(m):
    return Intent("web.search", {"query": m.group(1), "engine": "google"})


@rule(r"^(?:open|go to|visit|launch|navigate to|take me to) ((?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?)$")
def _url(m):
    return Intent("web.open", {"url": m.group(1)})


@rule(r"^(?:close|quit|exit|kill) (?:the )?(.+?)(?: app| window)?$")
def _close(m):
    return Intent("app.close", {"name": m.group(1)})


@rule(r"^(?:open|launch|start|run|bring up|show me|switch to|go to|fire up) (?:the |my )?(.+?)(?: app| application| program| website| site)?$")
def _open(m):
    return Intent("app.open", {"name": m.group(1)})


# ---- compound commands -------------------------------------------------------------------------
_SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|then|after that|and also|and)\b\s*", re.I)


def match_one(text: str) -> Intent | None:
    phrase = normalise(text)
    if not phrase:
        return None
    for pattern, build in RULES:
        if m := pattern.match(phrase):
            intent = build(m)
            if intent is not None:
                intent.phrase = phrase
                return intent
    return None


def match(text: str) -> list[Intent]:
    """Match a whole utterance, splitting "open Spotify and then play" into steps.

    A split is only accepted when every part is itself a command, so
    "remember that I like salt and pepper" stays a single memory.
    """
    single = match_one(text)
    parts = [p for p in _SPLIT.split(normalise(text)) if p]
    if len(parts) > 1:
        steps = [match_one(p) for p in parts]
        if all(steps) and not (single and single.tool in UNSPLITTABLE):
            return steps  # type: ignore[return-value]
    return [single] if single else []


UNSPLITTABLE = {"memory.remember", "note.add", "task.add", "reminder.add", "input.type", "routine.save",
                "agent.run", "web.search"}
