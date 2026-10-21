"""Silero VAD (MIT) speech gate: decides whether a recording contains speech.

Downloads silero_vad.onnx (~2 MB) on first use. Falls back to an energy gate
if the model is unavailable so push-to-talk never breaks.
"""

from __future__ import annotations

import logging
import threading
import urllib.request

import numpy as np

from hark.native import use_bundled_msvc_runtime
from hark.paths import models_dir

log = logging.getLogger(__name__)

SILERO_URL = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
FRAME = 512  # samples at 16 kHz
SPEECH_THRESHOLD = 0.30
MIN_SPEECH_FRAMES = 3  # ~96 ms of consecutive speech


class SileroVad:
    def __init__(self) -> None:
        self._session = None
        self._lock = threading.Lock()
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def load(self) -> bool:
        path = models_dir() / "silero_vad.onnx"
        try:
            if not path.exists():
                log.info("downloading Silero VAD")
                urllib.request.urlretrieve(SILERO_URL, path)
            use_bundled_msvc_runtime()
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            self._session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
            return True
        except Exception:
            log.exception("Silero VAD unavailable; using energy gate")
            return False

    def reset(self) -> None:
        self._state[:] = 0
        self._context[:] = 0

    def frame_prob(self, frame: np.ndarray) -> float:
        """Speech probability of one 512-sample int16 frame."""
        if self._session is None:
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            return min(1.0, rms / 1500.0)
        x = (frame.astype(np.float32) / 32768.0).reshape(1, -1)
        x = np.concatenate([self._context, x], axis=1)
        with self._lock:
            out, self._state = self._session.run(
                None, {"input": x, "state": self._state, "sr": np.array(16000, dtype=np.int64)}
            )
        self._context = x[:, -64:]
        return float(out[0][0])

    def gate(self, samples: np.ndarray) -> tuple[bool, float]:
        """Return (heard_speech, peak_probability) for a whole recording."""
        self.reset()
        peak, run, best_run = 0.0, 0, 0
        for start in range(0, len(samples) - FRAME + 1, FRAME):
            prob = self.frame_prob(samples[start:start + FRAME])
            peak = max(peak, prob)
            run = run + 1 if prob >= SPEECH_THRESHOLD else 0
            best_run = max(best_run, run)
        return best_run >= MIN_SPEECH_FRAMES, peak
