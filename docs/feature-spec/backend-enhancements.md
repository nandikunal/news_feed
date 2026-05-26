# news_feed Backend — Enhancement Spec

## Overview
This branch implements 3 backend features supporting the Kiezlink app UX improvements.

---

## 1. `GET /v1/today` — Timezone-Aware 24h Filtering

**File:** `app/routers/today.py`

**New query parameter:**

| Param | Type | Default | Description |
|---|---|---|---|
| `tz` | `str` | `"UTC"` | IANA timezone string (e.g. `Europe/Berlin`) |

**Logic:**
```python
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

def get_today_stories(tz: str = "UTC"):
    try:
        user_zone = ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz}")
    
    now_local = datetime.now(user_zone)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Hard cap: never older than 24 hours UTC
    utc_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cutoff = max(local_midnight.astimezone(timezone.utc), utc_cutoff)
    
    return [s for s in stories if s.published_at >= cutoff]
```

**Error response:**
```json
{"detail": "Unknown timezone: Foo/Bar"}
```

---

## 2. `GET /v1/today/stats` — Read/Unread/Total Counts

**File:** `app/routers/today.py`

**New endpoint:**
```python
@router.get("/v1/today/stats")
def get_today_stats():
    stories = get_deduplicated_today_stories()
    read_count = sum(1 for s in stories if s.read)
    total = len(stories)
    return {
        "read": read_count,
        "unread": total - read_count,
        "total": total,
        "deduplicated_total": total
    }
```

**Deduplication logic:**
- Deduplicate by `story.id` (not title) to prevent RSS re-posts inflating the count.
- Apply same timezone-aware 24h filter as `/v1/today`.

**Response schema:**
```json
{
  "read": 11,
  "unread": 29,
  "total": 40,
  "deduplicated_total": 40
}
```

**Auth:** Requires `X-API-Key` (public read key).

---

## 3. `GET /v1/today/updates` — Server-Sent Events (SSE)

**File:** `app/routers/today.py`

**New dependency:**
```
sse-starlette>=1.6.1
```
Add to `requirements.txt`.

**Implementation:**
```python
from sse_starlette.sse import EventSourceResponse
import asyncio, json

@router.get("/v1/today/updates")
async def today_updates(request: Request):
    async def event_generator():
        last_ids = set(s.id for s in get_deduplicated_today_stories())
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)
            current_stories = get_deduplicated_today_stories()
            current_ids = set(s.id for s in current_stories)
            new_ids = current_ids - last_ids
            if new_ids:
                new_stories = [s for s in current_stories if s.id in new_ids]
                yield {
                    "event": "new_stories",
                    "data": json.dumps({
                        "new_count": len(new_stories),
                        "stories": [s.dict() for s in new_stories]
                    })
                }
                last_ids = current_ids
    
    return EventSourceResponse(event_generator())
```

**Behaviour:**
- Polls internal story store every 30 seconds.
- Emits `new_stories` event only when new IDs appear.
- Disconnects cleanly when client drops.
- Auth: `X-API-Key` public key required.

---

## 4. `GET /v1/today` — Optional Topic Filter

**File:** `app/routers/today.py`

**New optional query parameter:**

| Param | Type | Default | Description |
|---|---|---|---|
| `topics` | `str` | `None` | Comma-separated topic labels (e.g. `tech,sports,health`) |

```python
def get_today_stories(tz: str = "UTC", topics: Optional[str] = None):
    stories = filter_by_timezone(tz)
    if topics:
        topic_list = [t.strip().lower() for t in topics.split(",")]
        stories = [s for s in stories if s.topic.lower() in topic_list]
    return stories
```

---

## Updated `requirements.txt` additions

```
sse-starlette>=1.6.1
```

For Python < 3.9 environments:
```
backports.zoneinfo; python_version < '3.9'
```

---

## Implementation Order

1. Add `sse-starlette` to `requirements.txt`
2. Add `tz` param + local midnight filter to `GET /v1/today`
3. Add `GET /v1/today/stats` endpoint
4. Add `GET /v1/today/updates` SSE endpoint
5. Add `topics` filter param to `GET /v1/today`
