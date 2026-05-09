import asyncio
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import feeds, today, stories, health

DEFAULT_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/rss.xml", "name": "BBC News", "category": "today"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "name": "NY Times", "category": "today"},
    {"url": "https://feeds.skynews.com/feeds/rss/world.xml", "name": "Sky News World", "category": "today"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import store
    from app.services.rss_parser import parse_feed
    from app.models.schemas import FeedSource, FeedCategory

    for f in DEFAULT_FEEDS:
        fid = hashlib.md5(f["url"].encode()).hexdigest()[:12]
        if not store.get_feed(fid):
            store.add_feed(
                FeedSource(
                    id=fid,
                    name=f["name"],
                    url=f["url"],
                    category=FeedCategory(f["category"]),
                )
            )

    try:
        feed_list = store.list_feeds(category=FeedCategory.today)
        results = await asyncio.gather(
            *[parse_feed(fd.url, category=fd.category) for fd in feed_list],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                store.cache_stories(r)
    except Exception:
        pass

    yield


app = FastAPI(
    title="RSS News API",
    description=(
        "Swipe-card RSS backend for a TikTok-style news app.\n\n"
        "Pass `X-API-Key` header on every request.\n\n"
        "- **Read key** (`API_KEY`): Today tab, search, story actions\n"
        "- **Admin key** (`ADMIN_API_KEY`): Feed management\n"
    ),
    version="1.0.0",
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
