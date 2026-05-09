from datetime import datetime
from typing import Dict, List, Optional
from app.models.schemas import FeedSource, StoryCard, FeedCategory

_feeds: Dict[str, FeedSource] = {}
_stories: Dict[str, StoryCard] = {}
_cache_updated_at: Optional[datetime] = None
CACHE_TTL = 300  # seconds


# ── Feed CRUD ────────────────────────────────────────────────────────────────

def add_feed(feed: FeedSource) -> FeedSource:
    _feeds[feed.id] = feed
    return feed


def get_feed(feed_id: str) -> Optional[FeedSource]:
    return _feeds.get(feed_id)


def list_feeds(category: Optional[FeedCategory] = None) -> List[FeedSource]:
    feeds = [f for f in _feeds.values() if f.active]
    if category:
        feeds = [f for f in feeds if f.category == category]
    return feeds


def delete_feed(feed_id: str) -> bool:
    if feed_id in _feeds:
        del _feeds[feed_id]
        return True
    return False


# ── Story cache ───────────────────────────────────────────────────────────────

def cache_stories(stories: List[StoryCard]):
    global _cache_updated_at
    for s in stories:
        if s.id in _stories:
            s.read = _stories[s.id].read
            s.liked = _stories[s.id].liked
            s.bookmarked = _stories[s.id].bookmarked
        _stories[s.id] = s
    _cache_updated_at = datetime.utcnow()


def get_stories(
    category: Optional[FeedCategory] = None,
    page: int = 1,
    per_page: int = 20,
) -> List[StoryCard]:
    stories = list(_stories.values())
    if category:
        stories = [s for s in stories if s.category == category]
    stories.sort(key=lambda s: s.published_at or datetime.min, reverse=True)
    start = (page - 1) * per_page
    return stories[start:start + per_page]


def count_stories(category: Optional[FeedCategory] = None) -> int:
    if category:
        return sum(1 for s in _stories.values() if s.category == category)
    return len(_stories)


def get_story(story_id: str) -> Optional[StoryCard]:
    return _stories.get(story_id)


def is_cache_stale() -> bool:
    if _cache_updated_at is None:
        return True
    return (datetime.utcnow() - _cache_updated_at).seconds > CACHE_TTL


def search_stories(query: str, category: Optional[FeedCategory] = None) -> List[StoryCard]:
    q = query.lower()
    results = [
        s for s in _stories.values()
        if (not category or s.category == category)
        and (q in s.title.lower() or q in s.short_content.lower() or q in s.source.lower())
    ]
    results.sort(key=lambda s: s.published_at or datetime.min, reverse=True)
    return results


# ── Story state mutations ─────────────────────────────────────────────────────

def mark_read(story_id: str) -> bool:
    if story_id in _stories:
        _stories[story_id].read = True
        return True
    return False


def toggle_like(story_id: str) -> Optional[bool]:
    if story_id not in _stories:
        return None
    _stories[story_id].liked = not _stories[story_id].liked
    return _stories[story_id].liked


def toggle_bookmark(story_id: str) -> Optional[bool]:
    if story_id not in _stories:
        return None
    _stories[story_id].bookmarked = not _stories[story_id].bookmarked
    return _stories[story_id].bookmarked


def seed_story(story: StoryCard):
    """Used in tests to inject a known story."""
    _stories[story.id] = story


def clear_all():
    """Used in tests to reset state between runs."""
    _feeds.clear()
    _stories.clear()
    global _cache_updated_at
    _cache_updated_at = None
