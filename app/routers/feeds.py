import hashlib
import feedparser
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_admin_access
from app.models.schemas import (
    AddFeedRequest,
    FeedSource,
    PreviewFeedRequest,
    StoryCard,
    ActionResponse,
    FeedCategory,
)
from app.services import store
from app.services.rss_parser import parse_feed

router = APIRouter(prefix="/v1/feeds", tags=["Feed Management"])


@router.post(
    "/preview",
    response_model=list[StoryCard],
    summary="Preview a feed without saving",
)
async def preview_feed(body: PreviewFeedRequest, _=Depends(require_admin_access)):
    """
    Fetch and normalise an RSS/Atom feed without persisting it.
    Useful for validating a feed URL before registering it.
    """
    try:
        return await parse_feed(body.url, limit=body.limit)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "",
    response_model=FeedSource,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new RSS feed",
)
async def add_feed(body: AddFeedRequest, _=Depends(require_admin_access)):
    """
    Register an RSS/Atom feed URL. The feed is automatically fetched
    on the next /v1/today request when the cache is stale (TTL 5 min).
    """
    feed_id = hashlib.md5(body.url.encode()).hexdigest()[:12]
    if store.get_feed(feed_id):
        raise HTTPException(status_code=409, detail="Feed already registered")
    try:
        f = feedparser.parse(body.url)
        if f.bozo and not f.entries:
            raise ValueError("Feed returned no entries")
        name = body.name or getattr(f.feed, "title", None) or body.url
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid feed: {e}")
    feed = FeedSource(id=feed_id, name=name, url=body.url, category=body.category)
    return store.add_feed(feed)


@router.delete(
    "/{feed_id}",
    response_model=ActionResponse,
    summary="Remove a feed by ID",
)
async def delete_feed(feed_id: str, _=Depends(require_admin_access)):
    """
    Remove a registered feed by its ID.
    Cached stories from this feed remain until TTL expires.
    """
    if not store.delete_feed(feed_id):
        raise HTTPException(status_code=404, detail="Feed not found")
    return ActionResponse(success=True, message=f"Feed {feed_id} deleted")


@router.get(
    "",
    response_model=list[FeedSource],
    summary="List all registered feeds",
)
async def list_feeds(
    category: FeedCategory = None,
    _=Depends(require_admin_access),
):
    """List all active feeds, optionally filtered by category."""
    return store.list_feeds(category)


@router.post(
    "/{feed_id}/refresh",
    response_model=ActionResponse,
    summary="Force refresh a specific feed",
)
async def refresh_feed(feed_id: str, _=Depends(require_admin_access)):
    """Force-fetch a feed and update the story cache immediately."""
    feed = store.get_feed(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        cards = await parse_feed(feed.url, category=feed.category)
        store.cache_stories(cards)
        return ActionResponse(
            success=True,
            message=f"Refreshed {len(cards)} stories from {feed.name}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
