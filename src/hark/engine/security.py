"""Per-launch bearer token shared between the client and the engine over a file
only the current user can read. Keeps other local processes and web pages
from driving the assistant through 127.0.0.1."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from hark.paths import token_file

HEADER = "X-Hark-Token"


def issue_token() -> str:
    token = secrets.token_urlsafe(32)
    token_file().write_text(token, encoding="utf-8")
    return token


def read_token() -> str:
    return token_file().read_text(encoding="utf-8").strip()


class TokenGuard:
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, x_hark_token: str | None = Header(default=None)) -> None:
        if x_hark_token is None or not secrets.compare_digest(x_hark_token, self.token):
            raise HTTPException(status_code=401, detail="missing or invalid engine token")
