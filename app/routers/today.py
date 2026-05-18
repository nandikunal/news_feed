import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import StreamingResponse
from app.core.security import require_read_access
from app.models.schemas import (
    TodayFeedResponse, SearchResponse, UpdatesResponse,
    FeedCategory, FeedStatsResponse,
)
from app.services import database as db

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


def _local_midnight(tz_name: str) -> datetime:
    """Return today's midnight in the given timezone as a UTC-aware datetime."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz_name!r}")
    local_now = datetime.now(tz)
    midnight_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(timezone.utc)


def _get_session_id(request: Request) -> str:
    """Extract X-Session-ID header; fall back to 'default' if absent."""
    return request.headers.get("X-Session-ID", "default")


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get Today stories (paginated, session-aware)",
)
async def get_today_stories(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=5, ge=1, le=20),
    tz: str = Query(default="UTC", description="IANA timezone, e.g. Europe/Berlin"),
    topics: Optional[str] = Query(
        default=None,
        description="Comma-separated topic filter, e.g. tech,sports,health",
    ),
    hide_read: bool = Query(
        default=True,
        description="If true, excludes stories already read in this session",
    ),
    _=Depends(require_read_access),
):
    """
    Returns today's story cards, filtered by:
    - The user's local timezone (only stories from today, 24 h cap)
    - Optional topic list
    - Session read history (hide_read=true skips already-read stories)

    Flutter usage:
      GET /v1/today?page=1&per_page=5&tz=Europe/Berlin&hide_read=true
    """
    session_id = _get_session_id(request)
    since_published = _local_midnight(tz)

    # Hard cap: never older than 24 h regardless of timezone edge cases
    utc_24h_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    if since_published < utc_24h_ago:
        since_published = utc_24h_ago

    # Parse optional topic list
    topic_list: Optional[List[str]] = None
    if topics:
        topic_list = [t.strip().lower() for t in topics.split(",") if t.strip()]

    # Fetch session read IDs to exclude
    exclude_ids: Optional[List[str]] = None
    if hide_read:
        exclude_ids = await db.get_session_read_ids(session_id)

    meta = await db.get_cache_meta()
    stories = await db.get_stories(
        category=FeedCategory.today,
        page=page,
        per_page=per_page,
        since_published=since_published,
        topics=topic_list,
        exclude_ids=exclude_ids,
    )
    total = await db.count_stories(
        category=FeedCategory.today,
        since_published=since_published,
    )
    return TodayFeedResponse(
        stories=stories,
        total=total,
        page=page,
        per_page=per_page,
        last_refresh_at=meta.get("last_refresh_at"),
        cached_at=datetime.now(timezone.utc),
        from_cache=True,
    )


@router.get(
    "/stats",
    response_model=FeedStatsResponse,
    summary="Get read/unread/total counts for this session",
)
async def get_feed_stats(
    request: Request,
    tz: str = Query(default="UTC"),
    _=Depends(require_read_access),
):
    """
    Called on app launch to populate the drawer header counters
    (Read | Unread | Total).  Scoped to today's stories only.
    """
    session_id = _get_session_id(request)
    since_published = _local_midnight(tz)
    utc_24h_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    if since_published < utc_24h_ago:
        since_published = utc_24h_ago

    stats = await db.get_session_stats(session_id, since_published=since_published)
    return FeedStatsResponse(
        read=stats["read"],
        unread=stats["unread"],
        total=stats["total"],
        deduplicated_total=stats["total"],
    )


@router.get(
    "/updates",
    summary="SSE stream — push new story events as they are cached",
)
async def get_updates_sse(
    request: Request,
    since: datetime = Query(
        ...,
        description="ISO 8601 timestamp — app sends its last known cached_at",
    ),
    _=Depends(require_read_access),
):
    """
    Server-Sent Events endpoint.  The Flutter app connects on foreground
    and receives a JSON event each time new stories are detected.

    Event format:  data: {\"total_new\": N, \"stories\": [...]}

    The app disconnects when backgrounded and reconnects on resume.
    A heartbeat comment (': ping') is sent every 25 s to keep the
    connection alive through proxies.
    """
    last_since = since

    async def event_stream():
        nonlocal last_since
        try:
            while True:
                # Abort if client disconnected
                if await request.is_disconnected():
                    break

                new_stories = await db.get_stories_since(
                    last_since, category=FeedCategory.today
                )
                if new_stories:
                    payload = json.dumps({
                        "total_new": len(new_stories),
                        "stories": [
                            {"id": s.id, "title": s.title,
                             "published_at": s.published_at.isoformat() if s.published_at else None}
                            for s in new_stories
                        ],
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    })
                    yield f"data: {payload}\n\n"
                    last_since = datetime.now(timezone.utc)
                else:
                    # Heartbeat to keep connection alive
                    yield ": ping\n\n"

                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search cached stories",
)
async def search_stories(
    q: str = Query(min_length=1, max_length=100, description="Search term"),
    _=Depends(require_read_access),
):
    results = await db.search_stories(q, category=FeedCategory.today)
    return SearchResponse(stories=results, query=q, total=len(results))
