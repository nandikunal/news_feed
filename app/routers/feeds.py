import hashlib
import feedparser
import asyncio
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_admin_access
from app.models.schemas import (
    AddFeedRequest,
    FeedSource,
    PreviewFeedRequest,
    StoryCard,
    ActionResponse,
    FeedCategory,
    RefreshJob,
)
from app.services import database as db
from app.services.rss_parser import parse_feed

logger = logging.getLogger(__name__)


MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 10


async def _refresh_feed_bg(feed_id: str, url: str, category: FeedCategory, job_id: str | None = None):
    """Background task: parse a single feed and cache stories and update job status.

    On failure, increments attempts and schedules an exponential backoff retry up to MAX_RETRIES.
    """
    try:
        if job_id:
            await db.update_refresh_job_status(job_id, 'running')
        cards = await parse_feed(url, category=category)
        new_stories = await db.cache_stories(cards)
        logger.info(f"Background refresh for feed {feed_id} processed {len(cards)} stories; {len(new_stories)} new.")
        if job_id:
            await db.update_refresh_job_status(job_id, 'success', result=f"Processed {len(cards)} stories; {len(new_stories)} new")
        # fire push notifications for newly inserted stories
        if new_stories:
            try:
                from app.services import push as push_service
                await push_service.notify_new_stories(new_stories)
            except Exception:
                logger.exception("Failed to send push notifications for new stories")
    except Exception as e:
        logger.exception(f"Background refresh failed for feed {feed_id}: {e}")
        if job_id:
            # increment attempts and decide whether to retry
            attempts = await db.increment_refresh_job_attempts(job_id)
            await db.update_refresh_job_status(job_id, 'failed', result=str(e))
            if attempts < MAX_RETRIES:
                delay = BASE_BACKOFF_SECONDS * (2 ** (attempts - 1))
                logger.info(f"Scheduling retry {attempts} for job {job_id} in {delay}s")

                async def _delayed_retry():
                    await asyncio.sleep(delay)
                    await _refresh_feed_bg(feed_id, url, category, job_id)

                asyncio.create_task(_delayed_retry())


router = APIRouter(prefix="/v1/feeds", tags=["Feed Management"])


@router.get(
    "/refresh-jobs",
    response_model=list[RefreshJob],
    summary="List refresh jobs (admin only)",
)
async def list_refresh_jobs(limit: int = 50, _=Depends(require_admin_access)):
    return await db.list_refresh_jobs(limit)


@router.get(
    "/refresh-jobs/{job_id}",
    response_model=RefreshJob,
    summary="Get a refresh job by id (admin only)",
)
async def get_refresh_job(job_id: str, _=Depends(require_admin_access)):
    job = await db.get_refresh_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post(
    "/refresh-jobs/{job_id}/retry",
    response_model=ActionResponse,
    summary="Retry a failed refresh job (admin only)",
)
async def retry_refresh_job(job_id: str, _=Depends(require_admin_access)):
    job = await db.get_refresh_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job['status'] == 'running':
        raise HTTPException(status_code=400, detail="Job is already running")
    # enqueue retry with same job_id
    await db.update_refresh_job_status(job_id, 'queued')
    # find feed info
    feed = await db.get_feed(job['feed_id']) if job.get('feed_id') else None
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found for this job")
    asyncio.create_task(_refresh_feed_bg(feed.id, feed.url, feed.category, job_id))
    return ActionResponse(success=True, message=f"Retry enqueued for job {job_id}")


@router.post(
    "/preview",
    response_model=list[StoryCard],
    summary="Preview a feed without saving",
)
async def preview_feed(body: PreviewFeedRequest, _=Depends(require_admin_access)):
    """Fetch and normalise an RSS/Atom feed without persisting it."""
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
    """Register an RSS/Atom feed. Enqueue an asynchronous refresh job after saving.

    The route returns immediately with the created feed (201). The actual fetch
    and cache persistence happens in the background to avoid long admin-request latency.
    """
    feed_id = hashlib.md5(body.url.encode()).hexdigest()[:12]
    if await db.get_feed(feed_id):
        raise HTTPException(status_code=409, detail="Feed already registered")
    try:
        f = feedparser.parse(body.url)
        if f.bozo and not f.entries:
            raise ValueError("Feed returned no entries")
        name = body.name or getattr(f.feed, "title", None) or body.url
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid feed: {e}")
    feed = FeedSource(
        id=feed_id,
        name=name,
        url=body.url,
        category=body.category,
        is_user_selectable=body.is_user_selectable,
    )

    created = await db.add_feed(feed)

    # Create a refresh job record and enqueue background refresh task (fire-and-forget)
    try:
        job_id = uuid.uuid4().hex[:12]
        await db.create_refresh_job(job_id, created.id)
        # enqueue background refresh
        asyncio.create_task(_refresh_feed_bg(created.id, created.url, created.category, job_id))
    except Exception as e:
        logger.warning(f"Failed to enqueue background refresh for feed {created.id}: {e}")

    return created


@router.delete(
    "/{feed_id}",
    response_model=ActionResponse,
    summary="Remove a feed by ID",
)
async def delete_feed(feed_id: str, _=Depends(require_admin_access)):
    if not await db.delete_feed(feed_id):
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
    return await db.list_feeds(category)


@router.post(
    "/{feed_id}/refresh",
    response_model=ActionResponse,
    summary="Force refresh a specific feed",
)
async def refresh_feed(feed_id: str, _=Depends(require_admin_access)):
    """Force-fetch a single feed and update the story cache immediately."""
    feed = await db.get_feed(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        cards = await parse_feed(feed.url, category=feed.category)
        await db.cache_stories(cards)
        return ActionResponse(
            success=True,
            message=f"Refreshed {len(cards)} stories from {feed.name}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
