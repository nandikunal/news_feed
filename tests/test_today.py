from app.models.schemas import StoryCard, FeedCategory, TopicLabel
from app.services import store


def _seed_n_stories(n: int):
    for i in range(n):
        s = StoryCard(
            id=f"story{i:04d}",
            title=f"Story number {i}",
            short_content=f"Short content for story {i}.",
            link=f"https://example.com/story/{i}",
            image_url="https://example.com/img.jpg",
            source="Test Source",
            topic=TopicLabel.general,
            category=FeedCategory.today,
        )
        store.seed_story(s)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_today_no_key(client):
    """GET /v1/today without API key → 403."""
    r = client.get("/v1/today")
    assert r.status_code == 403


def test_today_wrong_key(client):
    """GET /v1/today with wrong key → 403."""
    r = client.get("/v1/today", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 403


# ── Today feed ────────────────────────────────────────────────────────────────

def test_today_returns_stories(client, read_headers, sample_story):
    """GET /v1/today with valid key returns story cards."""
    r = client.get("/v1/today", headers=read_headers)
    assert r.status_code == 200
    data = r.json()
    assert "stories" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert data["total"] >= 1


def test_today_story_shape(client, read_headers, sample_story):
    """Each story card contains all required mobile-app fields."""
    r = client.get("/v1/today", headers=read_headers)
    story = r.json()["stories"][0]
    for field in ("id", "title", "short_content", "link", "image_url",
                  "source", "read", "liked", "bookmarked", "topic", "category"):
        assert field in story, f"Missing required field: {field}"


def test_today_pagination_page1(client, read_headers):
    """First page returns correct slice."""
    _seed_n_stories(25)
    r = client.get("/v1/today?page=1&per_page=10", headers=read_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["stories"]) == 10
    assert data["total"] == 25
    assert data["page"] == 1


def test_today_pagination_page2(client, read_headers):
    """Second page returns next slice."""
    _seed_n_stories(25)
    r = client.get("/v1/today?page=2&per_page=10", headers=read_headers)
    assert r.status_code == 200
    assert len(r.json()["stories"]) == 10


def test_today_pagination_last_page(client, read_headers):
    """Last partial page returns remainder."""
    _seed_n_stories(25)
    r = client.get("/v1/today?page=3&per_page=10", headers=read_headers)
    assert r.status_code == 200
    assert len(r.json()["stories"]) == 5


# ── Search ────────────────────────────────────────────────────────────────────

def test_search_no_key(client):
    """GET /v1/today/search without key → 403."""
    r = client.get("/v1/today/search?q=test")
    assert r.status_code == 403


def test_search_finds_by_title(client, read_headers, sample_story):
    """Search matches on title."""
    r = client.get("/v1/today/search?q=Test+Story", headers=read_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["query"] == "Test Story"


def test_search_finds_by_source(client, read_headers, sample_story):
    """Search matches on source name."""
    r = client.get("/v1/today/search?q=Test+Source", headers=read_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_search_no_match(client, read_headers, sample_story):
    """Search returns 0 results for unknown term."""
    r = client.get("/v1/today/search?q=zzznomatch999", headers=read_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_search_empty_query_rejected(client, read_headers):
    """Empty q param → 422 validation error."""
    r = client.get("/v1/today/search?q=", headers=read_headers)
    assert r.status_code == 422
