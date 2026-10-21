"""Microphone capture at 16 kHz mono, the rate every local recogniser here expects."""

from __future__ import annotations

import io
import logging
import threading
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BLOCK_MS = 32  # 512 samples, Silero VAD's frame size at 16 kHz
BLOCK_SAMPLES = SAMPLE_RATE * BLOCK_MS // 1000


class Recorder:
    """Collects int16 frames between start() and stop().

    `on_level` receives a 0..1 loudness value per block so the HUD can draw
    its meter; `on_frame` receives the raw block for VAD or wake detection.
    """

    def __init__(
        self,
        device: int | str | None = None,
        on_level: Callable[[float], None] | None = None,
        on_frame: Callable[[np.ndarray], None] | None = None,
    ) -> None:
        self.device = device
        self.on_level = on_level
        self.on_frame = on_frame
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self.recording = False

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=BLOCK_SAMPLES,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        info = sd.query_devices(self._stream.device, "input")
        log.info("microphone opened: name=%r rate=%d", info["name"], SAMPLE_RATE)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def start(self) -> None:
        with self._lock:
            self._frames = []
            self.recording = True
        self.open()

    def stop(self) -> np.ndarray:
        with self._lock:
            self.recording = False
            frames, self._frames = self._frames, []
        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(frames)

    def _callback(self, indata, _frames, _time, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        block = indata[:, 0].copy()
        with self._lock:
            if self.recording:
                self._frames.append(block)
        if self.on_frame is not None:
            self.on_frame(block)
        if self.on_level is not None:
            rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
            self.on_level(min(1.0, rms / 6000.0))


def to_wav_bytes(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


def from_wav_bytes(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise ValueError("expected 16-bit mono WAV")
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
