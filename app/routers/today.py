from datetime import datetime
from fastapi import APIRouter, Depends, Query
from app.core.security import require_read_access
from app.models.schemas import (
    TodayFeedResponse, SearchResponse, UpdatesResponse, FeedCategory
)
from app.services import database as db

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get Today stories (paginated, from DB cache)",
)
async def get_today_stories(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=5, ge=1, le=20),  # default=5 for fast first load
    _=Depends(require_read_access),
):
    """
    Always served from DB — never fetches live RSS at request time.
    Cache is refreshed by Render cron job every 15 min (prod)
    or APScheduler every 10 min (dev).

    Flutter usage:
      - Launch:      GET /v1/today?page=1&per_page=5
      - Scroll end:  GET /v1/today?page=2&per_page=10
      - App resume:  GET /v1/today/updates?since=<last_cached_at>
    """
    meta = await db.get_cache_meta()
    stories = await db.get_stories(
        category=FeedCategory.today,
        page=page,
        per_page=per_page,
    )
    total = await db.count_stories(category=FeedCategory.today)
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
    "/updates",
    response_model=UpdatesResponse,
    summary="Poll for new stories since a timestamp",
)
async def get_updates(
    since: datetime = Query(
        ...,
        description="ISO 8601 timestamp — app sends its last known cached_at value",
    ),
    _=Depends(require_read_access),
):
    """
    Incremental polling endpoint.
    Flutter calls this when the app resumes from background.
    Returns only stories added to the cache after `since`.
    Keeps the payload minimal — avoids re-downloading the full feed.
    """
    new_stories = await db.get_stories_since(since, category=FeedCategory.today)
    return UpdatesResponse(
        stories=new_stories,
        total_new=len(new_stories),
        since=since,
        checked_at=datetime.utcnow(),
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
