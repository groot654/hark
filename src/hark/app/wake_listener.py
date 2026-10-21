"""Hands-free listening for the wake phrase.

`BurstCollector` cuts the always-open microphone into bursts of speech (with a little audio from
just before each one starts, so the "hey" isn't clipped) and hands each finished burst on to be
transcribed and checked for the wake phrase. `Endpointer` decides when a request that follows
a bare "Hey Hark" is over. Both work on 32 ms frames and run on the audio thread.
"""

from __future__ import annotations

import ctypes
from collections import deque
from collections.abc import Callable

import numpy as np

FRAME_S = 0.032
SPEECH_THRESHOLD = 0.5


def frames(seconds: float) -> int:
    return max(1, round(seconds / FRAME_S))


class BurstCollector:
    def __init__(
        self,
        prob: Callable[[np.ndarray], float],
        on_burst: Callable[[np.ndarray], None],
        preroll_s: float = 0.45,
        end_silence_s: float = 0.6,
        max_s: float = 9.0,
        min_speech_s: float = 0.25,
    ) -> None:
        self.prob = prob
        self.on_burst = on_burst
        self._preroll: deque[tuple[np.ndarray, bool]] = deque(maxlen=frames(preroll_s))
        self._end_silence = frames(end_silence_s)
        self._max = frames(max_s)
        self._min_speech = frames(min_speech_s)
        self.reset()

    def reset(self) -> None:
        self._preroll.clear()
        self._frames: list[np.ndarray] = []
        self._flags: list[bool] = []
        self._active = False
        self._speech = 0
        self._silence = 0

    def take(self) -> tuple[list[np.ndarray], list[bool]]:
        """Hand over a burst still in progress (frames and whether each was speech), then start afresh."""
        taken = (self._frames, self._flags) if self._active else ([], [])
        self.reset()
        return taken

    def feed(self, frame: np.ndarray) -> None:
        speaking = self.prob(frame) >= SPEECH_THRESHOLD
        if not self._active:
            self._preroll.append((frame, speaking))
            if speaking:
                self._active = True
                self._frames = [f for f, _ in self._preroll]
                self._flags = [s for _, s in self._preroll]
                self._speech, self._silence = 1, 0
            return
        self._frames.append(frame)
        self._flags.append(speaking)
        if speaking:
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self._end_silence or len(self._frames) >= self._max:
            burst, enough = np.concatenate(self._frames), self._speech >= self._min_speech
            self.reset()
            if enough:
                self.on_burst(burst)


class Endpointer:
    """After "Hey Hark" alone: wait for the request, end it after a pause, give up if nothing comes."""

    def __init__(self, end_silence_s: float = 0.8, no_speech_s: float = 5.0, max_s: float = 15.0) -> None:
        self._end_silence = frames(end_silence_s)
        self._no_speech = frames(no_speech_s)
        self._max = frames(max_s)
        self.reset()

    def reset(self) -> None:
        self._count = 0
        self._speech = 0
        self._silence = 0

    def feed(self, prob: float) -> str:
        """'continue', 'end' (request finished) or 'cancel' (nothing was said)."""
        self._count += 1
        if prob >= SPEECH_THRESHOLD:
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._speech == 0:
            return "cancel" if self._count >= self._no_speech else "continue"
        if self._silence >= self._end_silence or self._count >= self._max:
            return "end"
        return "continue"


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def battery_saver_on() -> bool:
    """Hands-free listening rests while Windows battery saver is on."""
    status = _PowerStatus()
    try:
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return False
    except (AttributeError, OSError):
        return False
    return status.SystemStatusFlag == 1
