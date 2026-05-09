# ── Get story ─────────────────────────────────────────────────────────────────

def test_get_story_not_found(client, read_headers):
    """GET /v1/stories/{unknown} → 404."""
    r = client.get("/v1/stories/doesnotexist", headers=read_headers)
    assert r.status_code == 404


def test_get_story_found(client, read_headers, sample_story):
    """GET /v1/stories/{id} returns the full story card."""
    r = client.get(f"/v1/stories/{sample_story.id}", headers=read_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == sample_story.id
    assert data["title"] == sample_story.title


# ── Read ──────────────────────────────────────────────────────────────────────

def test_mark_read(client, read_headers, sample_story):
    """POST /v1/stories/{id}/read marks story as read and persists state."""
    r = client.post(f"/v1/stories/{sample_story.id}/read", headers=read_headers)
    assert r.status_code == 200
    assert r.json()["success"] is True
    detail = client.get(f"/v1/stories/{sample_story.id}", headers=read_headers)
    assert detail.json()["read"] is True


def test_mark_read_not_found(client, read_headers):
    r = client.post("/v1/stories/ghost/read", headers=read_headers)
    assert r.status_code == 404


# ── Like ──────────────────────────────────────────────────────────────────────

def test_like_toggle(client, read_headers, sample_story):
    """Like toggles: false → true → false."""
    r1 = client.post(f"/v1/stories/{sample_story.id}/like", headers=read_headers)
    assert r1.status_code == 200
    assert r1.json()["message"] == "Liked"

    r2 = client.post(f"/v1/stories/{sample_story.id}/like", headers=read_headers)
    assert r2.status_code == 200
    assert r2.json()["message"] == "Unliked"


def test_like_state_persists(client, read_headers, sample_story):
    """Like state visible via GET after toggle."""
    client.post(f"/v1/stories/{sample_story.id}/like", headers=read_headers)
    detail = client.get(f"/v1/stories/{sample_story.id}", headers=read_headers)
    assert detail.json()["liked"] is True


def test_like_not_found(client, read_headers):
    r = client.post("/v1/stories/ghost/like", headers=read_headers)
    assert r.status_code == 404


# ── Bookmark ──────────────────────────────────────────────────────────────────

def test_bookmark_toggle(client, read_headers, sample_story):
    """Bookmark toggles: false → true → false."""
    r1 = client.post(f"/v1/stories/{sample_story.id}/bookmark", headers=read_headers)
    assert r1.status_code == 200
    assert r1.json()["message"] == "Bookmarked"

    r2 = client.post(f"/v1/stories/{sample_story.id}/bookmark", headers=read_headers)
    assert r2.status_code == 200
    assert r2.json()["message"] == "Unbookmarked"


def test_bookmark_state_persists(client, read_headers, sample_story):
    """Bookmark state visible via GET after toggle."""
    client.post(f"/v1/stories/{sample_story.id}/bookmark", headers=read_headers)
    detail = client.get(f"/v1/stories/{sample_story.id}", headers=read_headers)
    assert detail.json()["bookmarked"] is True


def test_bookmark_not_found(client, read_headers):
    r = client.post("/v1/stories/ghost/bookmark", headers=read_headers)
    assert r.status_code == 404


# ── Auth guards ───────────────────────────────────────────────────────────────

def test_story_endpoints_no_key(client, sample_story):
    """All story endpoints return 403 without X-API-Key."""
    endpoints = [
        (client.get,  f"/v1/stories/{sample_story.id}"),
        (client.post, f"/v1/stories/{sample_story.id}/read"),
        (client.post, f"/v1/stories/{sample_story.id}/like"),
        (client.post, f"/v1/stories/{sample_story.id}/bookmark"),
    ]
    for method, path in endpoints:
        r = method(path)
        assert r.status_code == 403, f"Expected 403 on {path}, got {r.status_code}"
