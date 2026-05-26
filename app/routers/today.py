"""
/v1/today  —  location-aware, 24-h capped story feed

New in this version
-------------------
* ?tz=  – IANA timezone string; stories filtered to user's local midnight
* ?topic= – comma-separated topic slugs (server-side complement to client filter)
* GET /v1/today/stats  – deduplicated read / unread / total counts
* GET /v1/today/updates – SSE stream; fires when new story IDs arrive
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

# TTL (seconds) for the in-memory cache
CACHE_TTL = 300
_cache: dict = {"ts": 0.0, "data": []}


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


# ───────────────────────────────────────────────────────────────────
# GET /v1/today
# ───────────────────────────────────────────────────────────────────
@router.get("", summary="Today's stories (location-aware, 24h capped)")
async def today(
    tz: str = Query("UTC", description="IANA timezone, e.g. Europe/Berlin"),
    topic: str | None = Query(
        None,
        description="Comma-separated topic slugs to filter, e.g. tech,sports",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)

    cutoff_tz = _local_midnight_utc(tz)
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = datetime.fromtimestamp(now_utc.timestamp() - 86_400, tz=timezone.utc)
    # Strictest cutoff: user local midnight OR 24h ago, whichever is more recent
    cutoff = max(cutoff_tz, cutoff_24h)

    stories = await get_today_stories(published_after=cutoff)

    if topic:
        allowed = {t.strip().lower() for t in topic.split(",") if t.strip()}
        stories = [s for s in stories if (s.get("topic") or "").lower() in allowed]

    # Deduplicate by story id (safety net against duplicate RSS entries)
    seen: set = set()
    deduped = []
    for s in stories:
        sid = s.get("id")
        if sid not in seen:
            seen.add(sid)
            deduped.append(s)

    total = len(deduped)
    start = (page - 1) * per_page
    page_data = deduped[start : start + per_page]

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
):
    _validate_api_key(x_api_key)
    cutoff_tz = _local_midnight_utc(tz)
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = datetime.fromtimestamp(now_utc.timestamp() - 86_400, tz=timezone.utc)
    cutoff = max(cutoff_tz, cutoff_24h)
    stats = await get_story_stats(published_after=cutoff)
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
        tz_ = ZoneInfo(tz)
        now_local = datetime.now(tz_)
        midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_tz = midnight_local.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        cutoff_24h = datetime.fromtimestamp(now_utc.timestamp() - 86_400, tz=timezone.utc)
        return max(cutoff_tz, cutoff_24h)

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
