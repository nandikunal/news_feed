"""
Public endpoints for the Flutter onboarding screen.
Users browse the curated source list and pick 2-5 feeds.
No admin key required — standard API_KEY is sufficient.
"""
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.core.security import require_read_access
from app.models.schemas import FeedSource, SelectSourcesRequest, ActionResponse
from app.services import database as db
from app.services.rss_parser import parse_feed

router = APIRouter(prefix="/v1/sources", tags=["Source Selection"])


@router.get(
    "",
    response_model=List[FeedSource],
    summary="List user-selectable RSS sources (onboarding screen)",
)
async def list_selectable_sources(_=Depends(require_read_access)):
    """
    Called by the Flutter onboarding screen to populate the source picker.
    Returns only feeds marked is_user_selectable=True.
    """
    return await db.list_feeds(user_selectable_only=True)


@router.post(
    "/select",
    response_model=ActionResponse,
    summary="Submit user's chosen feed IDs after onboarding",
)
async def select_sources(
    body: SelectSourcesRequest,
    _=Depends(require_read_access),
):
    """
    Called once after the user finishes the onboarding source picker.

    Flow:
      1. Validate all feed IDs exist.
      2. Immediately fetch only the selected feeds (fast — 2-5 feeds).
      3. Store stories in DB cache.
      4. Flutter can call GET /v1/today?page=1&per_page=5 right after.

    Note: In a multi-user setup, persist (user_id -> feed_ids) in a
    user_preferences table and filter get_stories() by feed source.
    The DB schema is ready for this extension.
    """
    feeds = []
    for fid in body.feed_ids:
        feed = await db.get_feed(fid)
        if not feed:
            raise HTTPException(status_code=404, detail=f"Feed '{fid}' not found")
        feeds.append(feed)

    # Fetch only selected feeds immediately so the user's first load is fast
    results = await asyncio.gather(
        *[parse_feed(f.url, category=f.category) for f in feeds],
        return_exceptions=True,
    )
    stored = 0
    for r in results:
        if isinstance(r, list):
            await db.cache_stories(r)
            stored += len(r)

    return ActionResponse(
        success=True,
        message=f"Loaded {len(feeds)} sources with {stored} stories. Call /v1/today to start reading.",
    )
