import asyncio
from fastapi import APIRouter, Depends, Query
from app.core.security import require_read_access
from app.models.schemas import TodayFeedResponse, SearchResponse, FeedCategory
from app.services import store
from app.services.rss_parser import parse_feed

router = APIRouter(prefix="/v1/today", tags=["Today Tab"])


async def _auto_refresh_if_stale():
    """Refresh all Today feeds when cache TTL expires."""
    if not store.is_cache_stale():
        return
    feeds = store.list_feeds(category=FeedCategory.today)
    if not feeds:
        return
    results = await asyncio.gather(
        *[parse_feed(f.url, category=f.category) for f in feeds],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, list):
            store.cache_stories(r)


@router.get(
    "",
    response_model=TodayFeedResponse,
    summary="Get Today tab stories",
)
async def get_today_stories(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    _=Depends(require_read_access),
):
    """
    Returns paginated swipe-ready story cards for the Today tab.
    Cache auto-refreshes when stale (TTL = 5 min).
    """
    await _auto_refresh_if_stale()
    stories = store.get_stories(category=FeedCategory.today, page=page, per_page=per_page)
    total = store.count_stories(category=FeedCategory.today)
    return TodayFeedResponse(stories=stories, total=total, page=page, per_page=per_page)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search today stories",
)
async def search_stories(
    q: str = Query(min_length=1, max_length=100, description="Search term"),
    _=Depends(require_read_access),
):
    """
    Real-time case-insensitive search across title, short_content, and source.
    """
    results = store.search_stories(q, category=FeedCategory.today)
    return SearchResponse(stories=results, query=q, total=len(results))
