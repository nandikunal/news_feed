"""
/v1/today  —  location-aware, 24-h capped story feed

Endpoints
---------
GET  /v1/today            Stories for today in the user's timezone (paginated)
GET  /v1/today/stats      Per-device read / unread / deduplicated-total counts
GET  /v1/today/updates    Server-Sent Events — fires when new stories arrive
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

from app.core.config import settings
from app.models.schemas import FeedCategory
from app.services import database as db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/today", tags=["today"])


def _validate_api_key(x_api_key: str | None) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _compute_cutoff(tz_name: str) -> datetime:
    """Return the strictest cutoff: user local midnight OR 24h ago, whichever is newer."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz_name}")
    now_local = datetime.now(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_tz = midnight_local.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = datetime.fromtimestamp(now_utc.timestamp() - 86_400, tz=timezone.utc)
    return max(cutoff_tz, cutoff_24h)


# ---------------------------------------------------------------------------
# GET /v1/today
# ---------------------------------------------------------------------------
@router.get("", summary="Today's stories (location-aware, 24h capped)")
async def today(
    tz: str = Query("UTC", description="IANA timezone, e.g. Europe/Berlin"),
    topic: str | None = Query(
        None, description="Comma-separated topic slugs, e.g. tech,sports"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(default="anonymous"),
):
    _validate_api_key(x_api_key)
    cutoff = _compute_cutoff(tz)

    topics_filter = None
    if topic:
        topics_filter = [t.strip().lower() for t in topic.split(",") if t.strip()]

    stories = await db.get_stories(
        category=FeedCategory.today,
        page=page,
        per_page=per_page,
        since_published=cutoff,
        topics=topics_filter,
    )

    total = await db.count_stories(
        category=FeedCategory.today,
        since_published=cutoff,
        topics=topics_filter,
    )

    # Annotate read flag per device
    if x_device_id and x_device_id != "anonymous":
        read_ids = set(await db.get_session_read_ids(x_device_id))
        for s in stories:
            s.read = s.id in read_ids

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "stories": [s.model_dump() for s in stories],
    }


# ---------------------------------------------------------------------------
# GET /v1/today/stats
# ---------------------------------------------------------------------------
@router.get("/stats", summary="Per-device read/unread/total counts for today")
async def today_stats(
    tz: str = Query("UTC"),
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(default="anonymous"),
):
    """
    Returns read / unread / total counts scoped to the requesting device.
    The Flutter app calls this on launch and after every mark-read action.
    Displayed in the left drawer header and next to the bookmark icon.
    """
    _validate_api_key(x_api_key)
    cutoff = _compute_cutoff(tz)
    session_id = x_device_id or "anonymous"
    stats = await db.get_session_stats(session_id, since_published=cutoff)
    stats["deduplicated_total"] = stats["total"]  # dedup is handled at cache_stories level
    return stats


# ---------------------------------------------------------------------------
# GET /v1/today/updates  —  Server-Sent Events
# ---------------------------------------------------------------------------
async def _sse_generator(
    tz: str,
    x_api_key: str | None,
    request: Request,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings whenever new stories are cached."""
    _validate_api_key(x_api_key)

    POLL_INTERVAL = 30  # seconds between DB polls

    # Snapshot the current latest cached_at timestamp as our watermark
    stories_now = await db.get_stories(
        category=FeedCategory.today,
        page=1,
        per_page=1,
        since_published=_compute_cutoff(tz),
    )
    # Use the most recent cached_at as the SSE watermark
    if stories_now:
        watermark = stories_now[0].cached_at or datetime.now(timezone.utc)
    else:
        watermark = datetime.now(timezone.utc)

    total_at_connect = await db.count_stories(category=FeedCategory.today, since_published=_compute_cutoff(tz))

    # Initial heartbeat — lets client know connection is live
    yield f"data: {json.dumps({'event': 'connected', 'total': total_at_connect})}\n\n"

    while True:
        if await request.is_disconnected():
            break
        await asyncio.sleep(POLL_INTERVAL)
        try:
            new_stories = await db.get_stories_since(watermark, category=FeedCategory.today)
        except Exception as exc:
            log.warning("SSE poll error: %s", exc)
            continue

        if new_stories:
            # Advance watermark so we don't re-emit the same stories
            watermark = max(s.cached_at for s in new_stories if s.cached_at) or watermark
            payload = {
                "event": "new_stories",
                "new_count": len(new_stories),
                "stories": [s.model_dump(mode="json") for s in new_stories],
            }
            yield f"data: {json.dumps(payload, default=str)}\n\n"


@router.get("/updates", summary="SSE stream — fires when new stories are published")
async def today_updates(
    request: Request,
    tz: str = Query("UTC"),
    x_api_key: str | None = Header(None),
):
    """
    Server-Sent Events endpoint. The Flutter app subscribes when foregrounded
    and disconnects on AppLifecycleState.paused.
    New stories emit: {"event": "new_stories", "new_count": N, "stories": [...]}
    Heartbeat on connect: {"event": "connected", "total": N}
    """
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz}")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for chunk in _sse_generator(tz, x_api_key, request):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
