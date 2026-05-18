import asyncio
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from app.core.security import require_read_access
from app.models.schemas import (
    TodayFeedResponse, SearchResponse, UpdatesResponse,
    StatsResponse, FeedCategory, TopicLabel
)
from app.services import database as db

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get Today stories (paginated, timezone-aware, topic-filtered)",
)
async def get_today_stories(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=5, ge=1, le=20),
    tz: str = Query(default="UTC", description="IANA timezone string, e.g. Europe/Berlin"),
    topics: str = Query(
        default="",
        description="Comma-separated topic filter, e.g. tech,sports,health. Empty = all topics.",
    ),
    _=Depends(require_read_access),
):
    """
    Returns stories for **today** in the user's local timezone.
    Stories older than 24 h (UTC hard-cap) are never returned regardless of timezone.

    Flutter usage:
      - Launch:      GET /v1/today?page=1&per_page=5&tz=Europe/Berlin
      - Scroll end:  GET /v1/today?page=2&per_page=10&tz=Europe/Berlin
      - With filter: GET /v1/today?topics=tech,sports&tz=Europe/Berlin
      - App resume:  GET /v1/today/updates?since=<last_cached_at>
    """
    # Resolve timezone
    try:
        user_tz = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: '{tz}'")

    # Compute local midnight cutoff in UTC
    now_local = datetime.now(user_tz)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    local_midnight_utc = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)

    # Hard UTC cap: never older than 24h
    utc_cap = datetime.utcnow() - timedelta(hours=24)
    cutoff = max(local_midnight_utc, utc_cap)

    # Parse topic filter
    topic_filter: list[TopicLabel] | None = None
    if topics.strip():
        raw_topics = [t.strip().lower() for t in topics.split(",") if t.strip()]
        valid = []
        for t in raw_topics:
            try:
                valid.append(TopicLabel(t))
            except ValueError:
                pass  # silently ignore unknown topic labels
        if valid:
            topic_filter = valid

    meta = await db.get_cache_meta()
    stories = await db.get_stories_for_today(
        category=FeedCategory.today,
        since=cutoff,
        page=page,
        per_page=per_page,
        topics=topic_filter,
    )
    total = await db.count_stories_for_today(
        category=FeedCategory.today,
        since=cutoff,
        topics=topic_filter,
    )
    return TodayFeedResponse(
        stories=stories,
        total=total,
        page=page,
        per_page=per_page,
        last_refresh_at=meta.get("last_refresh_at"),
        cached_at=datetime.utcnow(),
        from_cache=True,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get deduplicated read/unread/total counts for today",
)
async def get_today_stats(
    tz: str = Query(default="UTC", description="IANA timezone string"),
    _=Depends(require_read_access),
):
    """
    Returns read / unread / total counts based on deduplicated story IDs for today.
    Flutter calls this on app launch (parallel to the stories fetch) and after
    every POST /v1/stories/{id}/read action to keep the drawer counter current.
    """
    try:
        user_tz = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: '{tz}'")

    now_local = datetime.now(user_tz)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    local_midnight_utc = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    utc_cap = datetime.utcnow() - timedelta(hours=24)
    cutoff = max(local_midnight_utc, utc_cap)

    read_count = await db.count_stories_for_today(
        category=FeedCategory.today, since=cutoff, read_filter=True
    )
    total = await db.count_stories_for_today(
        category=FeedCategory.today, since=cutoff
    )
    unread_count = total - read_count

    return StatsResponse(
        read=read_count,
        unread=unread_count,
        total=total,
        deduplicated_total=total,  # dedup is enforced at cache_stories write time
        as_of=datetime.utcnow(),
    )


@router.get(
    "/updates",
    summary="SSE stream — pushes new story events as they arrive in the cache",
)
async def get_updates_sse(
    since: datetime = Query(
        ...,
        description="ISO 8601 timestamp — app sends its last known cached_at value",
    ),
    _=Depends(require_read_access),
):
    """
    Server-Sent Events endpoint.
    The Flutter app subscribes on foreground resume and disconnects on background pause.
    Each event payload: {"total_new": N, "stories": [...StoryCard]}

    Flutter SSE connection pattern:
      final request = http.Request('GET', Uri.parse(url));
      final streamedResponse = await client.send(request);
      streamedResponse.stream.transform(utf8.decoder).listen((chunk) { ... });
    """
    async def event_stream():
        last_check = since
        # Send initial heartbeat so the client knows the connection is live
        yield "event: ping\ndata: {}\n\n"
        try:
            while True:
                await asyncio.sleep(30)  # poll DB every 30 s
                new_stories = await db.get_stories_since(
                    last_check, category=FeedCategory.today
                )
                if new_stories:
                    payload = {
                        "total_new": len(new_stories),
                        "stories": [
                            {
                                "id": s.id,
                                "title": s.title,
                                "short_content": s.short_content,
                                "link": s.link,
                                "image_url": s.image_url,
                                "source": s.source,
                                "topic": s.topic.value,
                                "category": s.category.value,
                                "published_at": s.published_at.isoformat() if s.published_at else None,
                            }
                            for s in new_stories
                        ],
                    }
                    yield f"event: new_stories\ndata: {json.dumps(payload)}\n\n"
                    last_check = datetime.utcnow()
                else:
                    # Keepalive comment every 30 s to prevent proxy timeouts
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
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
