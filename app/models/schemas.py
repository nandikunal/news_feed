from datetime import datetime
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class FeedCategory(str, Enum):
    today = "today"
    critical = "critical"
    city = "city"
    events = "events"
    ai_brief = "ai_brief"


class TopicLabel(str, Enum):
    politics = "politics"
    tech = "tech"
    finance = "finance"
    sports = "sports"
    health = "health"
    culture = "culture"
    environment = "environment"
    transport = "transport"
    berlin = "berlin"
    germany = "germany"
    general = "general"
    economy = "economy"
    news = "news"
    local = "local"
    entertainment = "entertainment"
    science = "science"
    weather = "weather"


class StoryCard(BaseModel):
    id: str
    title: str
    short_content: str
    link: str
    image_url: Optional[str] = None
    source: str
    source_names: List[str] = []
    published_at: Optional[datetime] = None
    cached_at: Optional[datetime] = None
    topic: TopicLabel = TopicLabel.general
    read: bool = False
    liked: bool = False
    bookmarked: bool = False
    category: FeedCategory = FeedCategory.today

    # ── Task 1: Story Clustering ────────────────────────────────────────
    # IDs of other stories covering the same event from different sources.
    # Empty list = singleton story (no related coverage found).
    related_story_ids: List[str] = Field(default_factory=list)
    # Shared cluster key; None for unclustered stories.
    cluster_id: Optional[str] = None

    # ── Task 2: Source Quality Score ──────────────────────────────────
    # Normalised quality score [0.0, 1.0] computed from fetch success rate,
    # image presence rate, summary length, and publish frequency.
    # None = score not yet computed for this source.
    source_quality_score: Optional[float] = None


# ── Feed management models (used by feeds.py router) ────────────────────────

class FeedSource(BaseModel):
    id: str
    name: str
    url: str
    category: FeedCategory = FeedCategory.today
    active: bool = True
    is_user_selectable: bool = True
    added_at: datetime = Field(default_factory=datetime.utcnow)

    # ── Task 2: quality metrics exposed on admin endpoints ───────────────
    quality_score: Optional[float] = None
    fetch_success_rate: Optional[float] = None
    avg_image_rate: Optional[float] = None
    avg_summary_length: Optional[float] = None
    avg_publish_frequency_per_day: Optional[float] = None


class AddFeedRequest(BaseModel):
    """Request body for POST /v1/feeds — register a new RSS feed."""
    url: str
    name: Optional[str] = None
    category: FeedCategory = FeedCategory.today
    topic: TopicLabel = TopicLabel.general
    is_user_selectable: bool = True

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


class PreviewFeedRequest(BaseModel):
    """Request body for POST /v1/feeds/preview — dry-run without saving."""
    url: str
    limit: int = 5

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


# Legacy alias — kept so any existing code using FeedCreate still works
class FeedCreate(AddFeedRequest):
    pass


class FeedRecord(BaseModel):
    id: str
    url: str
    name: Optional[str] = None
    category: FeedCategory
    topic: TopicLabel
    created_at: datetime
    last_fetched_at: Optional[datetime] = None
    story_count: int = 0
    is_active: bool = True


class FeedPreview(BaseModel):
    url: str
    title: Optional[str] = None
    story_count: int = 0
    sample_stories: List[StoryCard] = []


class SelectSourcesRequest(BaseModel):
    source_ids: List[str]


class ActionResponse(BaseModel):
    success: bool
    message: str = ""


# ── Stats models ───────────────────────────────────────────────────────

class FeedStatsResponse(BaseModel):
    """Read/unread/total counts for today's stories (session-scoped).
    Used by GET /v1/today/stats — shown in the app's left drawer.
    """
    read: int
    unread: int
    total: int
    deduplicated_total: int


# Alias with timestamp — Flutter models may use this name
class StatsResponse(FeedStatsResponse):
    as_of: datetime = Field(default_factory=datetime.utcnow)


class SearchResponse(BaseModel):
    stories: List[StoryCard]
    query: str
    total: int


class UpdatesResponse(BaseModel):
    new_stories: List[StoryCard]
    count: int
    checked_at: datetime


class TodayFeedResponse(BaseModel):
    stories: List[StoryCard]
    total: int
    page: int
    per_page: int
    cached_at: Optional[datetime] = None
    last_refresh_at: Optional[datetime] = None
    from_cache: bool = True
    new_stories_available: bool = False
    # Task 3: expose the mode used to build this deck
    mode: Optional[str] = None


class RefreshJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"


class RefreshJob(BaseModel):
    id: str
    feed_id: Optional[str] = None
    status: RefreshJobStatus
    queued_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[str] = None
    attempts: int = 0


# ── Session models ──────────────────────────────────────────────────

class UserSession(BaseModel):
    """Per-device session state."""
    device_id: str
    read_story_ids: List[str] = []
    last_story_index: int = 0
    selected_topics: List[str] = []
    display_name: str = ""
    location_label: str = ""
    last_seen_at: Optional[str] = None


class SessionUpdateRequest(BaseModel):
    last_story_index: int = 0
    selected_topics: List[str] = []
    display_name: str = ""
    location_label: str = ""


# ── Task 4: Intent-Based Deck Mode ────────────────────────────────────

class DeckMode(str, Enum):
    quick = "quick"       # 8-10 stories — glanceable session
    standard = "standard" # 20 stories    — default
    deep = "deep"         # 40+ stories   — long read / commute mode
