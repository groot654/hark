"""The built-in AI model: llama.cpp's llama-server running a small Qwen model.

On first use both are downloaded into %LOCALAPPDATA%\\hark\\models and checked
against pinned SHA-256 hashes. The server runs as a child process on a free
127.0.0.1 port, tied to a Windows job object so it dies with Hark even if Hark
crashes. Everything works without it; the AI features just stay unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from hark.native import copy_msvc_runtime
from hark.paths import logs_dir, models_dir

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Asset:
    url: str
    sha256: str
    size: int

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


LLAMA_RELEASE = "b11402"
LLAMA_SERVER = Asset(
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/llama-{LLAMA_RELEASE}-bin-win-vulkan-x64.zip",
    "e8fbe4e2c00ee4b6706f3c68b7f267f51270ede3ef1d377ffe1c318d70d25eec",
    33_308_213,
)
@dataclass(frozen=True)
class ModelChoice:
    name: str  # what the server calls it
    asset: Asset
    ram_gb: float  # free memory it needs to run comfortably


_QWEN = "https://huggingface.co/unsloth/{0}-GGUF/resolve/main/{0}-Q4_K_M.gguf"
MODELS = {
    "small": ModelChoice("qwen3.5-0.8b", Asset(_QWEN.format("Qwen3.5-0.8B"),
                         "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517", 532_517_120), 1.0),
    "medium": ModelChoice("qwen3.5-2b", Asset(_QWEN.format("Qwen3.5-2B"),
                          "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223", 1_280_835_840), 2.0),
    "large": ModelChoice("qwen3.5-4b", Asset(_QWEN.format("Qwen3.5-4B"),
                         "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", 2_740_937_888), 3.5),
}
DEFAULT_SIZE = "small"
MODEL_NAME = MODELS[DEFAULT_SIZE].name
CONTEXT_TOKENS = 8192
START_TIMEOUT = 120


class LocalModelError(RuntimeError):
    pass


class LocalModel:
    def __init__(self, root: Path | None = None, size: str = DEFAULT_SIZE) -> None:
        self.choice = MODELS.get(size, MODELS[DEFAULT_SIZE])
        self.root = root or models_dir()
        self.server_dir = self.root / f"llama-{LLAMA_RELEASE}"
        self.model_path = self.root / "llm" / self.choice.asset.filename
        self.state = "idle"  # idle | downloading | starting | ready | error | stopped
        self.progress = 0.0  # 0..1 while downloading
        self.error: str | None = None
        self.url = ""
        self._proc: subprocess.Popen | None = None
        self._job = None
        self._lock = threading.Lock()

    # ---- status ------------------------------------------------------------------------
    def status(self) -> dict:
        return {"state": self.state, "progress": round(self.progress, 3), "error": self.error, "model": self.choice.name}

    def memory_short(self) -> float | None:
        """Free memory in GB when it's less than this model needs, else None."""
        import psutil

        free = psutil.virtual_memory().available / 1e9
        return free if free < self.choice.ram_gb else None

    @property
    def installed(self) -> bool:
        return self.model_path.exists() and (self.server_dir / "llama-server.exe").exists()

    # ---- download ----------------------------------------------------------------------
    def ensure_installed(self) -> None:
        """Download and verify the server and the model if they're missing. Safe to call again after a failure."""
        if self.installed:
            self.progress = 1.0
            return
        self.state = "downloading"
        total = (0 if (self.server_dir / "llama-server.exe").exists() else LLAMA_SERVER.size) + \
                (0 if self.model_path.exists() else self.choice.asset.size)
        done = 0

        def report(n: int) -> None:
            nonlocal done
            done += n
            self.progress = done / total if total else 1.0

        if not (self.server_dir / "llama-server.exe").exists():
            archive = self.root / LLAMA_SERVER.filename
            _download(LLAMA_SERVER, archive, report)
            staging = self.server_dir.with_name(self.server_dir.name + ".tmp")
            shutil.rmtree(staging, ignore_errors=True)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)
            exe = next(staging.rglob("llama-server.exe"), None)
            if exe is None:
                raise LocalModelError("llama-server.exe not found in the llama.cpp download")
            shutil.rmtree(self.server_dir, ignore_errors=True)
            exe.parent.rename(self.server_dir)
            shutil.rmtree(staging, ignore_errors=True)
            archive.unlink(missing_ok=True)
        if not self.model_path.exists():
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            _download(self.choice.asset, self.model_path, report)
        self.progress = 1.0
        self.state = "idle"

    # ---- process -----------------------------------------------------------------------
    def start(self) -> str:
        """Install if needed, launch llama-server and wait until the model is loaded. Returns the base URL."""
        with self._lock:
            if self.state == "ready" and self._proc and self._proc.poll() is None:
                return self.url
            self.error = None
            try:
                self.ensure_installed()
                self.state = "starting"
                self.url = self._launch()
                self.state = "ready"
                return self.url
            except Exception as exc:
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                self._kill()
                raise

    def _launch(self) -> str:
        copy_msvc_runtime(self.server_dir)
        port = _free_port()
        args = [
            str(self.server_dir / "llama-server.exe"),
            "--model", str(self.model_path),
            "--alias", self.choice.name,
            "--host", "127.0.0.1",
            "--port", str(port),
            "--ctx-size", str(CONTEXT_TOKENS),
            "--parallel", "2",  # router and chat prompts each keep a cached slot
            "--threads", str(_physical_cores()),
            "--n-gpu-layers", "99",
            "--jinja",
            "--reasoning", "off",
            "--no-webui",
        ]
        log.info("starting llama-server on port %d", port)
        server_log = open(logs_dir() / "llama-server.log", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        self._proc = subprocess.Popen(
            args, cwd=self.server_dir, stdout=server_log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        server_log.close()
        self._job = _kill_with_parent(self._proc)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise LocalModelError(f"llama-server exited with code {self._proc.returncode}; see llama-server.log")
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    log.info("built-in model ready at %s", url)
                    return url
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise LocalModelError("llama-server did not become ready in time")

    def stop(self) -> None:
        with self._lock:
            self._kill()
            self.state = "stopped"

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


# ---- helpers ---------------------------------------------------------------------------
def _download(asset: Asset, dest: Path, report=lambda n: None) -> None:
    """Stream to dest.part, verify size and SHA-256, then move into place."""
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    log.info("downloading %s", asset.url)
    with httpx.stream("GET", asset.url, follow_redirects=True, timeout=httpx.Timeout(30, read=60)) as resp:
        resp.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                digest.update(chunk)
                report(len(chunk))
    size = part.stat().st_size
    if size != asset.size or digest.hexdigest() != asset.sha256:
        part.unlink(missing_ok=True)
        raise LocalModelError(f"{asset.filename} failed verification (got {size} bytes)")
    os.replace(part, dest)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _physical_cores() -> int:
    import psutil

    return max(1, min(8, psutil.cpu_count(logical=False) or 4))


def _kill_with_parent(proc: subprocess.Popen):
    """Put the child in a job object that is closed (killing the child) when Hark exits."""
    if sys.platform != "win32":
        return None
    try:
        import win32api
        import win32con
        import win32job

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
        win32job.AssignProcessToJobObject(job, handle)
        return job  # must stay referenced: closing the handle kills the server
    except Exception:
        log.exception("could not tie llama-server to Hark's lifetime")
        return None
