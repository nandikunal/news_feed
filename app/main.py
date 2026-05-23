import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import feeds, today, stories, health, internal, sources

logger = logging.getLogger(__name__)

# ── Curated default source list (seeded on first startup) ────────────────────
# CC-licensed feeds are safe for AI summarisation + commercial use.
# Standard feeds (BBC, NYT etc.) are display-only (RSS reader model).
DEFAULT_FEEDS = [
    # CC BY 3.0 — AI summary safe
    {"url": "https://globalvoices.org/feed/", "name": "Global Voices", "category": "today", "selectable": True},
    {"url": "https://feeds.feedburner.com/TechCrunch/", "name": "TechCrunch", "category": "today", "selectable": True},
    {"url": "https://www.scientificamerican.com/feed/rss/", "name": "Scientific American", "category": "today", "selectable": True},
    {"url": "https://www.nature.com/nature/articles?type=article.rss", "name": "Nature", "category": "today", "selectable": True},
    {"url": "https://www.sciencealert.com/rss", "name": "Science Alert", "category": "today", "selectable": True},
    {"url": "https://www.sciencemag.org/rss/news_current.xml", "name": "Science Magazine", "category": "today", "selectable": True},
    {"url": "https://www.npr.org/rss/rss.php?id=1001", "name": "NPR News", "category": "today", "selectable": True},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "name": "Al Jazeera", "category": "today", "selectable": True},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "name": "NYT Technology", "category": "today", "selectable": True},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "name": "NYT Science", "category": "today", "selectable": True},
    # Standard news sources (not CC-licensed, display-only)
    {"url": "http://feeds.bbci.co.uk/news/rss.xml", "name": "BBC News", "category": "today", "selectable": False},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "name": "NYT Home Page", "category": "today", "selectable": False},
    {"url": "https://www.theguardian.com/world/rss", "name": "The Guardian World", "category": "today", "selectable": False},
    {"url": "https://www.wired.com/feed/rss", "name": "Wired", "category": "today", "selectable": False},
    {"url": "https://www.cnet.com/rss/news/", "name": "CNET News", "category": "today", "selectable": False},
    {"url": "https://www.scientificamerican.com/rss/health/", "name": "Scientific American Health", "category": "today", "selectable": False},
    {"url": "https://www.sciencemag.org/rss/health_current.xml", "name": "Science Magazine Health", "category": "today", "selectable": False},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "name": "NYT Health", "category": "today", "selectable": False},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import database as db
    from app.models.schemas import FeedSource, FeedCategory

    # 1. Initialise DB tables + indexes
    await db.init_db()

    # 2. Clean up old feeds and stories on every start
    await db.clear_all()

    # 3. Seed default feeds (idempotent)
    # Skip seeding during pytest runs to keep test isolation (tests use in-memory store).
    import os
    if not os.getenv("PYTEST_CURRENT_TEST"):
        for f in DEFAULT_FEEDS:
            fid = hashlib.md5(f["url"].encode()).hexdigest()[:12]
            if not await db.get_feed(fid):
                await db.add_feed(FeedSource(
                    id=fid,
                    name=f["name"],
                    url=f["url"],
                    category=FeedCategory(f["category"]),
                    is_user_selectable=f.get("selectable", True),
                ))

    # 4. Non-blocking initial cache warm
    asyncio.create_task(_initial_warm())

    # 5. APScheduler only in dev — production uses Render cron -> /v1/internal/refresh
    _scheduler = None
    if settings.APP_ENV != "production":
        from app.services.scheduler import start_apscheduler
        _scheduler = start_apscheduler()

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)


async def _initial_warm():
    """Fire-and-forget: warms the DB cache after startup without blocking."""
    try:
        from app.services.scheduler import refresh_all_feeds
        await refresh_all_feeds()
    except Exception as exc:
        logger.warning(f"Initial cache warm failed: {exc}")


app = FastAPI(
    title="RSS News API",
    description=(
        "Swipe-card RSS backend for a TikTok-style news app.\n\n"
        "Pass `X-API-Key` header on every request.\n\n"
        "- **Read key** (`API_KEY`): Today tab, search, story actions, source list\n"
        "- **Admin key** (`ADMIN_API_KEY`): Feed management\n"
        "- **Internal key** (`INTERNAL_REFRESH_KEY`): Cron-triggered refresh\n"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(today.router)
app.include_router(stories.router)
app.include_router(feeds.router)
app.include_router(sources.router)
app.include_router(internal.router)
app.include_router(__import__('app.routers.push', fromlist=['router']).router)
app.include_router(__import__('app.routers.auth', fromlist=['router']).router)
