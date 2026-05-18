"""Tests for session-based read tracking and new endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services import database as db
from app.core.config import settings
import os

ADMIN_KEY = os.getenv("ADMIN_API_KEY", "test-admin-key")
READ_KEY = os.getenv("API_KEY", "test-read-key")


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_path, monkeypatch):
    """Use a fresh in-memory-equivalent SQLite for each test."""
    test_db = str(tmp_path / "test.db")
    monkeypatch.setattr(settings, "DB_PATH", test_db)
    import app.services.database as _db_mod
    _db_mod._db_path = test_db
    await db.init_db()
    yield
    if os.path.exists(test_db):
        os.remove(test_db)


@pytest.mark.asyncio
async def test_stats_endpoint_empty():
    """Stats should return zeros when no stories exist."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/v1/today/stats",
            headers={"X-API-Key": READ_KEY, "X-Session-ID": "sess-abc"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["read"] == 0
    assert data["total"] == 0
    assert data["unread"] == 0


@pytest.mark.asyncio
async def test_mark_read_increments_session_count():
    """After marking a story read, session stats should reflect it."""
    from app.models.schemas import StoryCard, FeedCategory, TopicLabel
    from datetime import datetime, timezone
    story = StoryCard(
        id="s1", title="Test", short_content="x", link="http://a.de",
        image_url="http://img.de", source="src",
        published_at=datetime.now(timezone.utc),
        category=FeedCategory.today, topic=TopicLabel.general,
    )
    await db.cache_stories([story])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-API-Key": READ_KEY, "X-Session-ID": "sess-xyz"}
        r = await client.post(f"/v1/stories/{story.id}/read", headers=headers)
        assert r.status_code == 200

        stats = await client.get("/v1/today/stats", headers=headers)
        data = stats.json()
        assert data["read"] == 1
        assert data["unread"] == 0


@pytest.mark.asyncio
async def test_hide_read_filters_story():
    """After marking a story read, it should not appear in hide_read=true feed."""
    from app.models.schemas import StoryCard, FeedCategory, TopicLabel
    from datetime import datetime, timezone
    story = StoryCard(
        id="s2", title="Hidden Story", short_content="x", link="http://b.de",
        image_url="http://img.de", source="src",
        published_at=datetime.now(timezone.utc),
        category=FeedCategory.today, topic=TopicLabel.general,
    )
    await db.cache_stories([story])

    session = "sess-hide-test"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-API-Key": READ_KEY, "X-Session-ID": session}
        # Mark as read
        await client.post(f"/v1/stories/{story.id}/read", headers=headers)
        # Fetch feed — story should be excluded
        feed = await client.get(
            "/v1/today?hide_read=true", headers=headers
        )
        ids = [s["id"] for s in feed.json()["stories"]]
        assert story.id not in ids


@pytest.mark.asyncio
async def test_different_sessions_independent():
    """Read state in session A must not affect session B."""
    from app.models.schemas import StoryCard, FeedCategory, TopicLabel
    from datetime import datetime, timezone
    story = StoryCard(
        id="s3", title="Shared Story", short_content="x", link="http://c.de",
        image_url="http://img.de", source="src",
        published_at=datetime.now(timezone.utc),
        category=FeedCategory.today, topic=TopicLabel.general,
    )
    await db.cache_stories([story])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers_a = {"X-API-Key": READ_KEY, "X-Session-ID": "session-A"}
        headers_b = {"X-API-Key": READ_KEY, "X-Session-ID": "session-B"}

        # Session A reads it
        await client.post(f"/v1/stories/{story.id}/read", headers=headers_a)

        # Session A should not see it
        feed_a = await client.get("/v1/today?hide_read=true", headers=headers_a)
        ids_a = [s["id"] for s in feed_a.json()["stories"]]
        assert story.id not in ids_a

        # Session B should still see it
        feed_b = await client.get("/v1/today?hide_read=true", headers=headers_b)
        ids_b = [s["id"] for s in feed_b.json()["stories"]]
        assert story.id in ids_b


@pytest.mark.asyncio
async def test_topic_filter():
    """Topic filter should return only matching stories."""
    from app.models.schemas import StoryCard, FeedCategory, TopicLabel
    from datetime import datetime, timezone
    tech = StoryCard(
        id="t1", title="Tech Story", short_content="x", link="http://t.de",
        image_url="http://img.de", source="src",
        published_at=datetime.now(timezone.utc),
        category=FeedCategory.today, topic=TopicLabel.tech,
    )
    sports = StoryCard(
        id="t2", title="Sports Story", short_content="x", link="http://s.de",
        image_url="http://img.de", source="src",
        published_at=datetime.now(timezone.utc),
        category=FeedCategory.today, topic=TopicLabel.sports,
    )
    await db.cache_stories([tech, sports])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-API-Key": READ_KEY}
        r = await client.get("/v1/today?topics=tech", headers=headers)
        ids = [s["id"] for s in r.json()["stories"]]
        assert "t1" in ids
        assert "t2" not in ids
