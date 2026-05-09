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
    general = "general"


class StoryCard(BaseModel):
    id: str
    title: str
    short_content: str
    link: str
    image_url: str
    source: str
    published_at: Optional[datetime] = None
    topic: TopicLabel = TopicLabel.general
    read: bool = False
    liked: bool = False
    bookmarked: bool = False
    category: FeedCategory = FeedCategory.today


class FeedSource(BaseModel):
    id: str
    name: str
    url: str
    category: FeedCategory = FeedCategory.today
    active: bool = True
    added_at: datetime = Field(default_factory=datetime.utcnow)


class AddFeedRequest(BaseModel):
    url: str = Field(..., description="Full RSS/Atom feed URL")
    name: Optional[str] = Field(None, description="Display name (auto-detected if omitted)")
    category: FeedCategory = FeedCategory.today


class PreviewFeedRequest(BaseModel):
    url: str = Field(..., description="RSS/Atom feed URL to preview")
    limit: int = Field(default=10, ge=1, le=50)


class ActionResponse(BaseModel):
    success: bool
    message: str


class TodayFeedResponse(BaseModel):
    stories: List[StoryCard]
    total: int
    page: int
    per_page: int


class SearchResponse(BaseModel):
    stories: List[StoryCard]
    query: str
    total: int
