from datetime import datetime, timezone
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
            # Preserve interaction state across refreshes
            s.read = _stories[s.id].read
            s.liked = _stories[s.id].liked
            s.bookmarked = _stories[s.id].bookmarked
            s.read_by = _stories[s.id].read_by
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


# ── Today-scoped helpers (used by /v1/today router) ───────────────────────────

async def get_today_stories(published_after: datetime) -> List[dict]:
    """Return deduplicated stories published after `published_after` as dicts.

    The cutoff is already computed by the today router (local midnight vs 24h,
    whichever is stricter). Stories are sorted newest-first.
    """
    # Normalise cutoff to UTC-aware
    if published_after.tzinfo is None:
        published_after = published_after.replace(tzinfo=timezone.utc)

    seen: set = set()
    result: List[dict] = []
    stories = sorted(
        _stories.values(),
        key=lambda s: s.published_at or datetime.min,
        reverse=True,
    )
    for s in stories:
        pub = s.published_at
        if pub is None:
            continue
        # Make pub UTC-aware for comparison
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub < published_after:
            continue
        if s.id in seen:
            continue
        seen.add(s.id)
        result.append({
            "id": s.id,
            "title": s.title,
            "short_content": s.short_content,
            "image_url": s.image_url,
            "source": s.source,
            "link": s.link,
            "published_at": s.published_at.isoformat() if s.published_at else None,
            "category": s.category.value if s.category else "today",
            "topic": s.topic.value if s.topic else "general",
            "read": s.read,
            "liked": s.liked,
            "bookmarked": s.bookmarked,
        })
    return result


async def get_story_stats(
    published_after: datetime,
    device_id: Optional[str] = None,
) -> dict:
    """Return read/unread/total counts for today's deduplicated stories.

    If `device_id` is supplied, `read` count reflects stories read by
    that specific device (via the `read_by` set).  Falls back to the
    global `story.read` flag when no device_id is given.
    """
    if published_after.tzinfo is None:
        published_after = published_after.replace(tzinfo=timezone.utc)

    seen: set = set()
    total = 0
    read_count = 0

    stories = sorted(
        _stories.values(),
        key=lambda s: s.published_at or datetime.min,
        reverse=True,
    )
    for s in stories:
        pub = s.published_at
        if pub is None:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub < published_after:
            continue
        if s.id in seen:
            continue
        seen.add(s.id)
        total += 1
        if device_id:
            if device_id in getattr(s, "read_by", set()):
                read_count += 1
        else:
            if s.read:
                read_count += 1

    return {
        "read": read_count,
        "unread": total - read_count,
        "total": total,
        "deduplicated_total": total,
    }


# ── Story state mutations ─────────────────────────────────────────────────────

def mark_read(story_id: str, device_id: Optional[str] = None) -> bool:
    """Mark a story as read.  Optionally record the reading device."""
    if story_id in _stories:
        _stories[story_id].read = True
        if device_id:
            _stories[story_id].read_by.add(device_id)
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
