"""Local speech recognition.

Fast default: NVIDIA Parakeet TDT 0.6B v3 (int8 ONNX, CC-BY-4.0) via onnx-asr.
Optional: faster-whisper "small" when the `whisper` extra is installed.
Models download to %LOCALAPPDATA%\\togo\\models on first use.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from togo.native import use_bundled_msvc_runtime
from togo.paths import models_dir

log = logging.getLogger(__name__)

PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"
WHISPER_MODEL = "small"
SHORT_AUDIO_S = 3.0
PAD_S = 1.0


class SpeechRecognizer:
    def __init__(self, backend: str = "parakeet") -> None:
        self.backend = backend
        self._model = None
        self._lock = threading.Lock()
        self.ready = threading.Event()
        self.error: str | None = None

    def load(self) -> None:
        started = time.monotonic()
        try:
            use_bundled_msvc_runtime()
            if self.backend == "whisper":
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    WHISPER_MODEL, device="cpu", compute_type="int8",
                    download_root=str(models_dir() / "whisper"),
                )
            else:
                import onnx_asr

                path = models_dir() / PARAKEET_MODEL
                self._model = onnx_asr.load_model(
                    PARAKEET_MODEL, path=str(path), quantization="int8",
                    providers=["CPUExecutionProvider"],
                )
            log.info("STT %s ready in %.1fs", self.backend, time.monotonic() - started)
        except Exception as exc:  # surfaced through /v1/system/health
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("STT failed to load")
        finally:
            self.ready.set()

    def load_async(self) -> None:
        threading.Thread(target=self.load, name="stt-load", daemon=True).start()

    def transcribe(self, samples: np.ndarray, rate: int = 16_000) -> str:
        if samples.size < rate // 4:  # under 250 ms: nothing worth decoding
            return ""
        if samples.size < rate * SHORT_AUDIO_S:
            # Parakeet often returns nothing for a short phrase with background noise, unless it
            # has some quiet around it (63/72 -> 71/72 "Hey Togo" clips heard in tests).
            pad = np.zeros(int(rate * PAD_S), dtype=samples.dtype)
            samples = np.concatenate([pad, samples, pad])
        self.ready.wait(timeout=120)
        if self._model is None:
            raise RuntimeError(self.error or "speech recognition is not loaded")
        audio = samples.astype(np.float32) / 32768.0
        with self._lock:
            if self.backend == "whisper":
                segments, _info = self._model.transcribe(audio, language="en", vad_filter=False, beam_size=1)
                text = " ".join(s.text for s in segments)
            else:
                text = self._model.recognize(audio, sample_rate=rate)
        return " ".join(str(text).split())
