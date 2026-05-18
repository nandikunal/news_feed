import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import StreamingResponse
from app.core.security import require_read_access
from app.models.schemas import (
    TodayFeedResponse, SearchResponse, FeedStatsResponse, FeedCategory,
)
from app.services import database as db

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


def _local_midnight_utc(tz_name: str) -> datetime:
    """Return today's midnight in the given IANA timezone as a UTC-aware datetime."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz_name!r}")
    local_now = datetime.now(tz)
    midnight_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(timezone.utc)


def _session_id(request: Request) -> str:
    return request.headers.get("X-Session-ID", "default")


def _since_cutoff(tz: str) -> datetime:
    """Compute the stricter of local midnight and 24 h ago."""
    midnight = _local_midnight_utc(tz)
    cap = datetime.now(timezone.utc) - timedelta(hours=24)
    return max(midnight, cap)


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get today's stories — timezone-aware, topic-filtered, session-aware",
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
        description="Exclude stories already read in this session",
    ),
    _=Depends(require_read_access),
):
    """
    Flutter usage:
      GET /v1/today?page=1&per_page=20&tz=Europe/Berlin&hide_read=true
      GET /v1/today?topics=tech,sports&tz=Europe/Berlin
    """
    session_id = _session_id(request)
    since = _since_cutoff(tz)

    topic_list: Optional[List[str]] = None
    if topics:
        topic_list = [t.strip().lower() for t in topics.split(",") if t.strip()]

    exclude_ids: Optional[List[str]] = None
    if hide_read:
        exclude_ids = await db.get_session_read_ids(session_id)

    meta = await db.get_cache_meta()
    stories = await db.get_stories(
        category=FeedCategory.today,
        page=page,
        per_page=per_page,
        since_published=since,
        topics=topic_list,
        exclude_ids=exclude_ids,
    )
    total = await db.count_stories(
        category=FeedCategory.today,
        since_published=since,
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
    summary="Get deduplicated read/unread/total counts for today",
)
async def get_feed_stats(
    request: Request,
    tz: str = Query(default="UTC"),
    _=Depends(require_read_access),
):
    """
    Called in parallel with stories fetch on app launch.
    Re-called after every POST /v1/stories/{id}/read.
    Sends X-Session-ID header to track per-device read state.
    """
    session_id = _session_id(request)
    since = _since_cutoff(tz)
    stats = await db.get_session_stats(session_id, since_published=since)
    return FeedStatsResponse(
        read=stats["read"],
        unread=stats["unread"],
        total=stats["total"],
        deduplicated_total=stats["total"],
    )


@router.put(
    "/session",
    summary="Persist session state — last viewed story index and optional read marker",
)
async def update_session(
    request: Request,
    tz: str = Query(default="UTC"),
    _=Depends(require_read_access),
):
    """
    Called by the Flutter app to:
      - Record which story index the user last viewed (for resume-on-reopen).
      - Optionally mark a story as read in the same call.

    Request body (JSON, all fields optional):
      {
        "last_story_index": 6,
        "story_id": "abc123"   // if present, also marks this story as read
      }

    Returns current session stats so the app can update its counters
    in a single round-trip.

    Note: last_story_index is informational — the backend acknowledges it
    but story ordering is owned by the client. The value is echoed back
    so the app can confirm receipt.
    """
    session_id = _session_id(request)
    since = _since_cutoff(tz)

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass  # empty body is fine — stats-only update

    story_id: Optional[str] = body.get("story_id")
    last_story_index: Optional[int] = body.get("last_story_index")

    if story_id:
        story = await db.get_story(story_id)
        if story:
            await db.mark_story_read_in_session(session_id, story_id)

    stats = await db.get_session_stats(session_id, since_published=since)
    return {
        "session_id": session_id,
        "last_story_index": last_story_index,
        "read": stats["read"],
        "unread": stats["unread"],
        "total": stats["total"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/updates",
    summary="SSE stream — push new story events as they arrive in the cache",
)
async def get_updates_sse(
    request: Request,
    since: datetime = Query(
        ...,
        description="ISO 8601 timestamp — Flutter sends its last known cached_at value",
    ),
    _=Depends(require_read_access),
):
    """
    Server-Sent Events endpoint.

    Flutter app:
      - Connects on foreground resume
      - Disconnects on background pause
      - Sends: GET /v1/today/updates?since=<last_cached_at_iso>

    Each event:  data: {"total_new": N, "stories": [{id, title, ...}]}
    Keepalive:   : ping  (every 25 s to survive proxy timeouts)
    """
    last_since = since

    async def event_stream():
        nonlocal last_since
        try:
            while True:
                if await request.is_disconnected():
                    break

                new_stories = await db.get_stories_since(
                    last_since, category=FeedCategory.today
                )
                if new_stories:
                    payload = json.dumps({
                        "total_new": len(new_stories),
                        "stories": [
                            {
                                "id": s.id,
                                "title": s.title,
                                "short_content": s.short_content,
                                "image_url": s.image_url,
                                "source": s.source,
                                "topic": s.topic.value,
                                "category": s.category.value,
                                "published_at": s.published_at.isoformat()
                                if s.published_at else None,
                            }
                            for s in new_stories
                        ],
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    })
                    yield f"data: {payload}\n\n"
                    last_since = datetime.now(timezone.utc)
                else:
                    yield ": ping\n\n"

                await asyncio.sleep(25)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search cached stories",
)
async def search_stories(
    q: str = Query(min_length=1, max_length=100),
    _=Depends(require_read_access),
):
    results = await db.search_stories(q, category=FeedCategory.today)
    return SearchResponse(stories=results, query=q, total=len(results))
