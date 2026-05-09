import hashlib
import re
from datetime import datetime
from typing import List, Optional
from email.utils import parsedate_to_datetime
import feedparser

from app.models.schemas import StoryCard, FeedCategory
from app.services.topic_classifier import classify_topic, get_fallback_image
from app.services.image_extractor import extract_image


def _make_id(link: str) -> str:
    return hashlib.md5(link.encode()).hexdigest()[:16]


def _clean_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()


def _short_content(text: str, max_chars: int = 220) -> str:
    text = _clean_html(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:!?") + "\u2026"


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                pass
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return parsedate_to_datetime(val)
            except Exception:
                pass
    return None


def _feed_name(feed, url: str) -> str:
    title = getattr(feed.feed, "title", None)
    if title:
        return _clean_html(title)
    from urllib.parse import urlparse
    return urlparse(url).netloc.replace("www.", "")


async def parse_feed(
    url: str,
    category: FeedCategory = FeedCategory.today,
    limit: int = 20,
    fetch_article_images: bool = False,
) -> List[StoryCard]:
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not parse feed at {url}: {feed.bozo_exception}")
    source_name = _feed_name(feed, url)
    cards: List[StoryCard] = []
    for entry in feed.entries[:limit]:
        link = getattr(entry, "link", "") or url
        title = _clean_html(getattr(entry, "title", "Untitled"))
        raw = (
            next((c["value"] for c in getattr(entry, "content", [])), None)
            or getattr(entry, "summary", "")
            or ""
        )
        short = _short_content(raw)
        published = _parse_date(entry)
        topic = classify_topic(title, raw)
        image_url = await extract_image(entry, link, fetch_article=fetch_article_images)
        if not image_url:
            image_url = get_fallback_image(topic)
        cards.append(
            StoryCard(
                id=_make_id(link),
                title=title,
                short_content=short,
                link=link,
                image_url=image_url,
                source=source_name,
                published_at=published,
                topic=topic,
                category=category,
            )
        )
    return cards
