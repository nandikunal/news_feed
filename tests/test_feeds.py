import hashlib
from app.models.schemas import FeedSource, FeedCategory
from app.services import store


def _seed_feed(
    url="https://example.com/feed.xml",
    name="Test Feed",
    category=FeedCategory.today,
):
    fid = hashlib.md5(url.encode()).hexdigest()[:12]
    feed = FeedSource(id=fid, name=name, url=url, category=category)
    store.add_feed(feed)
    return fid


# ── Auth guard ────────────────────────────────────────────────────────────────

def test_list_feeds_no_key(client):
    """GET /v1/feeds without key → 403."""
    r = client.get("/v1/feeds")
    assert r.status_code == 403


def test_list_feeds_read_key_rejected(client, read_headers):
    """GET /v1/feeds with read key → 403 (admin only)."""
    r = client.get("/v1/feeds", headers=read_headers)
    assert r.status_code == 403


def test_add_feed_no_key(client):
    """POST /v1/feeds without key → 403."""
    r = client.post("/v1/feeds", json={"url": "https://example.com/feed.xml"})
    assert r.status_code == 403


def test_delete_feed_no_key(client):
    """DELETE /v1/feeds/{id} without key → 403."""
    r = client.delete("/v1/feeds/someid")
    assert r.status_code == 403


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_feeds_empty(client, admin_headers):
    """Returns empty list when no feeds registered."""
    r = client.get("/v1/feeds", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_feeds_returns_seeded(client, admin_headers):
    """Returns seeded feed in list."""
    _seed_feed()
    r = client.get("/v1/feeds", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "Test Feed"


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_feed_success(client, admin_headers):
    """DELETE /v1/feeds/{id} removes the feed."""
    fid = _seed_feed()
    r = client.delete(f"/v1/feeds/{fid}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["success"] is True
    # verify it's gone
    r2 = client.get("/v1/feeds", headers=admin_headers)
    assert r2.json() == []


def test_delete_feed_not_found(client, admin_headers):
    """DELETE /v1/feeds/{unknown_id} → 404."""
    r = client.delete("/v1/feeds/nonexistent", headers=admin_headers)
    assert r.status_code == 404


# ── Refresh ───────────────────────────────────────────────────────────────────

def test_refresh_feed_not_found(client, admin_headers):
    """POST /v1/feeds/{unknown_id}/refresh → 404."""
    r = client.post("/v1/feeds/nonexistent/refresh", headers=admin_headers)
    assert r.status_code == 404
