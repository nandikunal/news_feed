"""
Background refresh logic.

Production (Render):  Render cron job calls POST /v1/internal/refresh
Development (local):  APScheduler runs refresh_all_feeds every 10 minutes
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def refresh_all_feeds():
    """Fetch all active feeds and upsert into DB with deduplication."""
    from app.services import database as db
    from app.services.rss_parser import parse_feed

    feeds = await db.list_feeds()
    if not feeds:
        logger.info("No active feeds to refresh.")
        return

    logger.info(f"Refreshing {len(feeds)} feeds...")
    results = await asyncio.gather(
        *[parse_feed(f.url, category=f.category) for f in feeds],
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, list):
            await db.cache_stories(r)
            total += len(r)
        elif isinstance(r, Exception):
            logger.warning(f"Feed parse error: {r}")
    logger.info(f"Refresh complete — {total} raw stories processed.")


def start_apscheduler():
    """Start APScheduler for local/dev environments only."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            refresh_all_feeds,
            "interval",
            minutes=10,
            id="rss_refresh",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("APScheduler started — refreshing every 10 minutes (dev mode).")
        return scheduler
    except ImportError:
        logger.warning("apscheduler not installed — skipping local scheduler.")
        return None
