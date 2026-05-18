import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.security import require_read_access
from app.models.schemas import (
    TodayFeedResponse,
    SearchResponse,
    FeedCategory,
    StatsResponse,
    UserSession,
    SessionUpdateRequest,
)
from app.services import database as db

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


def _get_device_id(x_device_id: str = Header(default="anonymous")) -> str:
    """Extract device ID from X-Device-ID request header."""
    return x_device_id or "anonymous"


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get today's unread stories for this device",
)
async def get_today_stories(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=5, ge=1, le=20, description="Stories per page"),
    tz: str = Query(
        default="UTC",
        description="IANA timezone string from device, e.g. Europe/Berlin",
    ),
    topics: str = Query(
        default="",
        description="Comma-separated topic filter, e.g. tech,sports,health",
    ),
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Returns unread stories for today (device-scoped).

    - Filters stories already read by this device (X-Device-ID header)
    - Respects user's local timezone for 'today' boundary (tz param)
    - Hard cap: never returns stories older than 24h UTC
    - Optional client-side topic filter via ?topics=tech,sports
    """
    topic_list = (
        [t.strip() for t in topics.split(",") if t.strip()] if topics else None
    )

    meta = await db.get_cache_meta()
    stories = await db.get_stories_excluding_read(
        device_id=device_id,
        category=FeedCategory.today,
        page=page,
        per_page=per_page,
        tz=tz,
        topics=topic_list,
    )
    total = await db.count_stories_excluding_read(
        device_id=device_id,
        category=FeedCategory.today,
        tz=tz,
    )
    return TodayFeedResponse(
        stories=stories,
        total=total,
        page=page,
        per_page=per_page,
        last_refresh_at=meta.get("last_refresh_at") if meta else None,
        cached_at=datetime.utcnow(),
        from_cache=True,
        new_stories_available=False,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get read/unread/total counts for today (device-scoped)",
)
async def get_today_stats(
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Returns deduplicated read/unread/total for today's feed.
    Counts are scoped to this device's read history via X-Device-ID.
    Call on app launch and after every /read action to keep the UI in sync.
    """
    stats = await db.get_today_stats(device_id=device_id)
    return StatsResponse(**stats)


@router.get(
    "/updates",
    summary="SSE stream — pushes new story counts as they arrive",
)
async def get_updates_sse(
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Server-Sent Events endpoint. Flutter subscribes on app foreground,
    disconnects when app goes to background (AppLifecycleState.paused).

    Polls every 30s. Emits a JSON event when new unread stories appear:
      data: {"new_count": 3, "total_unread": 27, "checked_at": "2026-05-18T..."}

    Sends a heartbeat comment every 30s when no change, to keep the
    connection alive through proxies and load balancers.
    """

    async def event_stream():
        last_total = await db.count_stories_excluding_read(
            device_id, FeedCategory.today
        )
        while True:
            await asyncio.sleep(30)
            try:
                current_total = await db.count_stories_excluding_read(
                    device_id, FeedCategory.today
                )
                if current_total != last_total:
                    new_count = max(0, current_total - last_total)
                    payload = json.dumps(
                        {
                            "new_count": new_count,
                            "total_unread": current_total,
                            "checked_at": datetime.utcnow().isoformat(),
                        }
                    )
                    yield f"data: {payload}\n\n"
                    last_total = current_total
                else:
                    # Heartbeat — keeps connection alive
                    yield f": heartbeat {datetime.utcnow().isoformat()}\n\n"
            except GeneratorExit:
                break
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search cached today stories",
)
async def search_stories(
    q: str = Query(min_length=1, max_length=100),
    _=Depends(require_read_access),
):
    results = await db.search_stories(q, category=FeedCategory.today)
    return SearchResponse(stories=results, query=q, total=len(results))


@router.get(
    "/session",
    response_model=UserSession,
    summary="Get or create device session",
)
async def get_session(
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Returns the stored session for this device (or creates a blank one).
    Contains last_story_index, selected_topics, display_name, location_label.
    Used on app cold start to restore state.
    """
    session_data = await db.get_or_create_session(device_id)
    return UserSession(**session_data)


@router.put(
    "/session",
    summary="Update device session state",
)
async def update_session(
    body: SessionUpdateRequest,
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Syncs session from device to server.
    Called on every page change (debounced 500ms) and on topic filter change.
    """
    await db.update_session(
        device_id=device_id,
        last_story_index=body.last_story_index,
        selected_topics=body.selected_topics,
        display_name=body.display_name,
        location_label=body.location_label,
    )
    return {"success": True}
