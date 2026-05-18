from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class FeedCategory(str, Enum):
    today = "today"
    critical = "critical"
    city = "city"
    events = "events"
    ai_brief = "ai_brief"


class TopicLabel(str, Enum):
    politics = "politics"
    health = "health"
    tech = "tech"
    finance = "finance"
    sports = "sports"
    transport = "transport"
    weather = "weather"
    local = "local"
    entertainment = "entertainment"
    science = "science"
    culture = "culture"
    environment = "environment"
    berlin = "berlin"
    germany = "germany"
    general = "general"
    economy = "economy"
    news = "news"


class StoryCard(BaseModel):
    id: str
    title: str
    short_content: str
    link: str
    image_url: Optional[str] = None
    source: str
    source_names: List[str] = []
    published_at: Optional[datetime] = None
    topic: TopicLabel = TopicLabel.general
    read: bool = False
    liked: bool = False
    bookmarked: bool = False
    category: FeedCategory = FeedCategory.today


# ── Feed management models (used by feeds.py router) ─────────────────────────

class FeedSource(BaseModel):
    id: str
    name: str
    url: str
    category: FeedCategory = FeedCategory.today
    active: bool = True
    is_user_selectable: bool = True
    added_at: datetime = Field(default_factory=datetime.utcnow)


class AddFeedRequest(BaseModel):
    url: str = Field(..., description="Full RSS/Atom feed URL")
    name: Optional[str] = Field(None, description="Display name (auto-detected if omitted)")
    category: FeedCategory = FeedCategory.today
    is_user_selectable: bool = True


class PreviewFeedRequest(BaseModel):
    url: str = Field(..., description="RSS/Atom feed URL to preview")
    limit: int = Field(default=10, ge=1, le=50)


class SelectSourcesRequest(BaseModel):
    """Sent by Flutter app during onboarding — user picks 2–5 feeds."""
    feed_ids: List[str] = Field(..., min_length=2, max_length=5)


class ActionResponse(BaseModel):
    success: bool
    message: str = ""


# ── Stats models ──────────────────────────────────────────────────────────────

class FeedStatsResponse(BaseModel):
    """Read/unread/total counts for today's stories (session-scoped).
    Used by GET /v1/today/stats — shown in the app's left drawer.
    """
    read: int
    unread: int
    total: int
    deduplicated_total: int


# Alias with timestamp — Flutter models use this name
class StatsResponse(FeedStatsResponse):
    as_of: datetime = Field(default_factory=datetime.utcnow)


# ── Response models ───────────────────────────────────────────────────────────

class TodayFeedResponse(BaseModel):
    stories: List[StoryCard]
    total: int
    page: int
    per_page: int
    cached_at: Optional[datetime] = None
    last_refresh_at: Optional[datetime] = None
    from_cache: bool = True


class UpdatesResponse(BaseModel):
    """Returns only stories added to cache after `since` timestamp."""
    stories: List[StoryCard]
    total_new: int
    since: datetime
    checked_at: datetime


class SearchResponse(BaseModel):
    stories: List[StoryCard]
    query: str
    total: int
