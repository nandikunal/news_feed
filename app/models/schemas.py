from datetime import datetime
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, HttpUrl, field_validator


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


class StoryCard(BaseModel):
    id: str
    title: str
    short_content: str
    image_url: Optional[str] = None
    link: str
    source: str
    category: FeedCategory
    topic: TopicLabel
    published_at: Optional[datetime] = None
    cached_at: Optional[datetime] = None
    read: bool = False
    liked: bool = False
    bookmarked: bool = False


class FeedPreview(BaseModel):
    url: str
    title: Optional[str] = None
    story_count: int = 0
    sample_stories: List[StoryCard] = []


class FeedCreate(BaseModel):
    url: str
    name: Optional[str] = None
    category: FeedCategory = FeedCategory.today
    topic: TopicLabel = TopicLabel.general

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


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


class ActionResponse(BaseModel):
    success: bool
    message: str = ""


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


class StatsResponse(BaseModel):
    """Deduplicated read/unread/total counts for today's feed (device-scoped)."""
    read: int
    unread: int
    total: int
    deduplicated_total: int


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
