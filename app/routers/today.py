"""
/v1/today  —  location-aware, 24-h capped story feed

Endpoints
---------
GET /v1/today               – paginated story feed filtered to user's local day
GET /v1/today/stats         – deduplicated read / unread / total counts (per device)
GET /v1/today/updates       – Server-Sent Events; fires when new stories arrive
PUT /v1/today/session       – persist last-viewed index + topic preferences
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import AsyncGenerator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.store import (
    get_today_stories,
    get_story_stats,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/today", tags=["today"])


def _validate_api_key(x_api_key: str | None) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _local_midnight_utc(tz_name: str) -> datetime:
    """Return today's midnight in `tz_name` expressed as UTC-aware datetime."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz_name}")
    now_local = datetime.now(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(timezone.utc)


def _strict_cutoff(tz_name: str) -> datetime:
    """Stricter of local midnight vs 24 h ago."""
    cutoff_tz = _local_midnight_utc(tz_name)
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = datetime.fromtimestamp(now_utc.timestamp() - 86_400, tz=timezone.utc)
    return max(cutoff_tz, cutoff_24h)


# ───────────────────────────────────────────────────────────────────
# GET /v1/today
# ───────────────────────────────────────────────────────────────────
@router.get("", summary="Today's stories (location-aware, 24 h capped)")
async def today(
    tz: str = Query("UTC", description="IANA timezone, e.g. Europe/Berlin"),
    topic: str | None = Query(
        None,
        description="Comma-separated topic slugs to filter, e.g. tech,sports",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    cutoff = _strict_cutoff(tz)
    stories = await get_today_stories(published_after=cutoff)

    if topic:
        allowed = {t.strip().lower() for t in topic.split(",") if t.strip()}
        stories = [s for s in stories if (s.get("topic") or "").lower() in allowed]

    # Per-device read flag: if the requesting device has read this story,
    # mark it so the client can skip it.
    if x_device_id:
        from app.services.store import get_story
        for s in stories:
            story_obj = get_story(s["id"])
            if story_obj and x_device_id in getattr(story_obj, "read_by", set()):
                s["read"] = True

    total = len(stories)
    start = (page - 1) * per_page
    page_data = stories[start: start + per_page]

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "stories": page_data,
    }


# ───────────────────────────────────────────────────────────────────
# GET /v1/today/stats
# ───────────────────────────────────────────────────────────────────
@router.get("/stats", summary="Read / unread / deduplicated-total counts for today")
async def today_stats(
    tz: str = Query("UTC"),
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(None),
):
    """Return per-device read/unread/total for today's deduplicated stories.

    The X-Device-ID header scopes the 'read' count to the requesting device,
    so each user sees their own progress rather than a global aggregate.
    """
    _validate_api_key(x_api_key)
    cutoff = _strict_cutoff(tz)
    stats = await get_story_stats(published_after=cutoff, device_id=x_device_id)
    return stats


# ───────────────────────────────────────────────────────────────────
# GET /v1/today/updates  —  Server-Sent Events
# ───────────────────────────────────────────────────────────────────
async def _sse_generator(
    tz: str, x_api_key: str | None
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings whenever new stories arrive."""
    _validate_api_key(x_api_key)

    POLL_INTERVAL = 30  # seconds

    def _cutoff() -> datetime:
        return _strict_cutoff(tz)

    stories = await get_today_stories(published_after=_cutoff())
    known_ids: set = {s.get("id") for s in stories}

    # Initial heartbeat so the client knows the connection is live
    yield f"data: {json.dumps({'event': 'connected', 'total': len(known_ids)})}\n\n"

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            fresh = await get_today_stories(published_after=_cutoff())
        except Exception as exc:  # pragma: no cover
            log.warning("SSE poll error: %s", exc)
            continue

        fresh_ids = {s.get("id") for s in fresh}
        new_ids = fresh_ids - known_ids
        if new_ids:
            new_stories = [s for s in fresh if s.get("id") in new_ids]
            payload = {
                "event": "new_stories",
                "new_count": len(new_stories),
                "stories": new_stories,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            known_ids = fresh_ids


@router.get("/updates", summary="SSE stream — fires when new stories arrive")
async def today_updates(
    request: Request,
    tz: str = Query("UTC"),
    x_api_key: str | None = Header(None),
):
    """Server-Sent Events endpoint.

    The Flutter app subscribes while in the foreground and disconnects on
    AppLifecycleState.paused.  When new RSS items are ingested the stream
    emits a `new_stories` event so the app can show the refresh banner.
    """
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz}")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for chunk in _sse_generator(tz, x_api_key):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ───────────────────────────────────────────────────────────────────
# PUT /v1/today/session
# ───────────────────────────────────────────────────────────────────
@router.put("/session", summary="Persist last-viewed index and topic preferences")
async def today_session(
    request: Request,
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(None),
):
    """Lightweight session sync called by the Flutter app on every swipe.

    Body (JSON, all optional):
        last_story_index  int
        selected_topics   list[str]
        display_name      str
        location_label    str
    """
    _validate_api_key(x_api_key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Currently a no-op store — extend as needed for cross-device sync.
    log.debug(
        "Session sync device=%s index=%s topics=%s",
        x_device_id,
        body.get("last_story_index"),
        body.get("selected_topics"),
    )
    return {"ok": True}
