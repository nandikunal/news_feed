def test_root(client):
    """GET / — confirms routing works."""
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "RSS News API"
    assert "docs" in data
    assert "version" in data


def test_health(client):
    """GET /health — confirms app is up."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
