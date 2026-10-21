"""Client for a local OpenAI-compatible chat server (bundled llama-server or Ollama).

Every caller must cope with `LLMUnavailable`: the assistant keeps working on
deterministic intents when no model is running.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"
THINK = re.compile(r"<think>.*?</think>", re.S)  # in case a model reasons despite being told not to


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMConfig:
    base_url: str = os.environ.get("HARK_LLM_URL", "")
    model: str = os.environ.get("HARK_LLM_MODEL", "")
    timeout: float = 30.0


class LLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self._http = httpx.Client(timeout=self.config.timeout)

    def set_endpoint(self, base_url: str, model: str) -> None:
        self.config.base_url = base_url.rstrip("/")
        self.config.model = model

    def discover(self) -> bool:
        """Use an explicit endpoint, else fall back to a running Ollama."""
        if self.config.base_url:
            return self.available()
        try:
            tags = self._http.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).json()
        except (httpx.HTTPError, ValueError):
            return False
        models = [m["name"] for m in tags.get("models", [])]
        if not models:
            return False
        preferred = next((m for m in models if m.startswith(("qwen", "llama", "gemma"))), models[0])
        self.set_endpoint(OLLAMA_URL, self.config.model or preferred)
        log.info("using Ollama model %s", self.config.model)
        return True

    def available(self) -> bool:
        if not self.config.base_url:
            return False
        try:
            return self._http.get(f"{self.config.base_url}/v1/models", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            return False

    def _payload(self, messages: list[dict], temperature: float, max_tokens: int, stream: bool, json_mode: bool) -> dict:
        payload: dict = {
            "model": self.config.model or "local",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 400,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> str:
        if not self.config.base_url:
            raise LLMUnavailable("no local model configured")
        try:
            resp = self._http.post(
                f"{self.config.base_url}/v1/chat/completions",
                json=self._payload(messages, temperature, max_tokens, False, json_mode),
                timeout=timeout or self.config.timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
            return THINK.sub("", content).strip()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc

    def stream(self, messages: list[dict], temperature: float = 0.4, max_tokens: int = 600) -> Iterator[str]:
        if not self.config.base_url:
            raise LLMUnavailable("no local model configured")
        try:
            with self._http.stream(
                "POST",
                f"{self.config.base_url}/v1/chat/completions",
                json=self._payload(messages, temperature, max_tokens, True, False),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
