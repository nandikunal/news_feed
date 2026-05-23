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

## Quickstart (Auth + Push)
- POST /v1/auth/register {email,password} → 200 (user created)
- POST /v1/auth/login {email,password} → {access_token, token_type}
- Use Authorization: Bearer <token> for user-scoped actions and X-API-Key for read/admin access.
- After login, POST /v1/push/register {token,platform} with Bearer to register device for push.

## Key endpoints (minimal usage)
- GET /v1/today?per_page=20&page=1  (requires X-API-Key)
- GET /v1/today/search?q=term  (requires X-API-Key)
- GET /v1/stories/{id}  (returns per-user state when Bearer present)
- POST /v1/stories/{id}/read|/like|/bookmark  (toggle actions, X-API-Key or Bearer)
- POST /v1/feeds  (admin: add feed; enqueues background refresh)
- POST /v1/feeds/{feed_id}/refresh (admin: force refresh)
- POST /v1/push/register and /v1/push/unregister (user device token management)

## Architecture (brief)
- FastAPI app (app/main.py) with routers: today, stories, feeds, auth, push, internal.
- Persistence: aiosqlite-backed DB (app/services/database.py) + in-memory store for tests.
- Background refresh: scheduler and refresh jobs (refresh_jobs table) with retry/backoff.
- IAM: JWT-based auth (app/services/auth.py) + X-API-Key gates for read/admin/internal.
- Push: FCM legacy HTTP integration (app/services/push.py) triggered after new stories inserted.

## Sequence flow (add feed → refresh → notify)
1. Admin POST /v1/feeds (adds feed) → server creates feed row + refresh_job row.
2. Background worker picks job → fetches feed → cache_stories inserts new stories.
3. cache_stories returns new_stories list → push.notify_new_stories sends notifications to registered device tokens.
4. Refresh job status updated (success/failed). Retries scheduled with exponential backoff.

## Regenerate OpenAPI used by /docs
- A generator is included: `python3 scripts/generate_openapi.py` writes `docs/openapi.json` from the running FastAPI app schema.
