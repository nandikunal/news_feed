import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import store
from app.models.schemas import StoryCard, FeedCategory, TopicLabel

READ_KEY = "dev-api-key"
ADMIN_KEY = "dev-admin-key"


@pytest.fixture(autouse=True)
def reset_store():
    """Wipe in-memory store before every test for full isolation."""
    store.clear_all()
    yield
    store.clear_all()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def read_headers():
    return {"X-API-Key": READ_KEY}


@pytest.fixture
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}


@pytest.fixture
def sample_story():
    s = StoryCard(
        id="abc123",
        title="Test Story Headline",
        short_content="This is a short summary of the test story.",
        link="https://example.com/story/1",
        image_url="https://example.com/image.jpg",
        source="Test Source",
        topic=TopicLabel.tech,
        category=FeedCategory.today,
    )
    store.seed_story(s)
    return s
