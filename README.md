# RSS News Feed API

FastAPI backend that ingests RSS feeds and serves swipe-ready JSON cards for a TikTok-style news app.

## Project Structure

```
news_feed/
├── app/
│   ├── core/
│   │   ├── config.py        # Settings loaded from .env
│   │   └── security.py      # API key auth (read + admin)
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   ├── routers/
│   │   ├── health.py        # GET / and GET /health
│   │   ├── feeds.py         # Feed management (admin)
│   │   ├── today.py         # Today tab + search
│   │   └── stories.py       # Story actions
│   ├── services/
│   │   ├── rss_parser.py    # Feed fetch + normalize
│   │   ├── image_extractor.py
│   │   ├── topic_classifier.py
│   │   └── store.py         # In-memory store
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_feeds.py
│   ├── test_today.py
│   └── test_stories.py
├── .env.example
├── Dockerfile
├── render.yaml
└── requirements.txt
```

## Run locally

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # Edit .env with your own keys
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive Swagger UI.

## Generate API keys

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the output into `.env` for `API_KEY` and `ADMIN_API_KEY`.

## API Auth

All endpoints (except `/` and `/health`) require the `X-API-Key` header.

| Header | Value | Access |
|---|---|---|
| `X-API-Key` | value of `API_KEY` in `.env` | Read endpoints |
| `X-API-Key` | value of `ADMIN_API_KEY` in `.env` | Admin endpoints |

## Endpoints

### Public
- `GET /` — root
- `GET /health` — health check

### Today Tab (read key)
- `GET /v1/today` — paginated swipe cards
- `GET /v1/today/search?q=` — real-time search

### Story Actions (read key)
- `GET /v1/stories/{id}` — full story detail
- `POST /v1/stories/{id}/read` — mark as read
- `POST /v1/stories/{id}/like` — toggle like
- `POST /v1/stories/{id}/bookmark` — toggle bookmark

### Feed Management (admin key)
- `POST /v1/feeds` — add a new RSS feed
- `DELETE /v1/feeds/{id}` — remove a feed
- `GET /v1/feeds` — list all feeds
- `POST /v1/feeds/preview` — preview feed without saving
- `POST /v1/feeds/{id}/refresh` — force refresh

## Run tests

```bash
pytest -v
```
