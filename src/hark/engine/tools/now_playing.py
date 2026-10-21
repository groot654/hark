"""What's playing, from Windows' system media controls (Spotify, browsers, Media Player)."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def _read() -> dict | None:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    manager = await Manager.request_async()
    session = manager.get_current_session()
    if session is None:
        return None
    props = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    timeline = session.get_timeline_properties()
    return {
        "title": props.title or "",
        "artist": props.artist or "",
        "album": props.album_title or "",
        "app": session.source_app_user_model_id,
        "playing": int(playback.playback_status) == 4,
        "position_s": timeline.position.total_seconds() if timeline else None,
        "duration_s": timeline.end_time.total_seconds() if timeline else None,
    }


def current() -> dict | None:
    try:
        info = asyncio.run(_read())
    except Exception:
        log.exception("media session unavailable")
        return None
    return info if info and info["title"] else None
