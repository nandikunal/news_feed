"""
/v1/stories  — per-story interactions (read, like, bookmark)

All write endpoints accept X-Device-Id so that per-device stats
(GET /v1/today/stats) can accurately reflect each user's read state.
"""
from fastapi import APIRouter, Header, HTTPException
from app.core.config import settings
from app.services import store
from app.services import database as db

router = APIRouter(prefix="/v1/stories", tags=["stories"])


def _validate_api_key(x_api_key: str | None) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post(
    "/{story_id}/read",
    summary="Mark a story as read (per-device session + global flag)",
)
async def mark_read(
    story_id: str,
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
):
    """
    Records the story as read for the requesting device.

    - Updates the global `read` flag in the stories table.
    - Inserts a row into `user_sessions` so `GET /v1/today/stats`
      returns accurate per-device read/unread counts.

    The Flutter app sends `X-Device-Id: <UUID>` on every request.
    """
    _validate_api_key(x_api_key)

    # 1. Update global read flag (in-memory store keeps backward compat)
    ok = store.mark_read(story_id, device_id=x_device_id)

    # 2. Also persist the per-device session read in SQLite
    #    so /v1/today/stats counts are correct even after in-memory eviction.
    session_id = x_device_id or "anonymous"
    await db.mark_story_read_in_session(session_id, story_id)

    # 3. Ensure the global DB row is also flagged (covers the case where
    #    the story was never in the in-memory store, e.g. after a restart).
    await db.update_story_state(story_id, read=True)

    if not ok:
        # Story not in in-memory store but session was recorded — still OK
        # (could be a story loaded from a previous session).
        story_in_db = await db.get_story(story_id)
        if not story_in_db:
            raise HTTPException(status_code=404, detail="Story not found")

    return {"ok": True, "story_id": story_id, "session": session_id}


@router.post("/{story_id}/like", summary="Toggle like on a story")
async def like_story(
    story_id: str,
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    liked = store.toggle_like(story_id)
    if liked is None:
        # Try DB fallback
        story = await db.get_story(story_id)
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        new_liked = not story.liked
        await db.update_story_state(story_id, liked=new_liked)
        return {"ok": True, "liked": new_liked}
    # Sync to DB
    await db.update_story_state(story_id, liked=liked)
    return {"ok": True, "liked": liked}


@router.post("/{story_id}/bookmark", summary="Toggle bookmark on a story")
async def bookmark_story(
    story_id: str,
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    bookmarked = store.toggle_bookmark(story_id)
    if bookmarked is None:
        story = await db.get_story(story_id)
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        new_bm = not story.bookmarked
        await db.update_story_state(story_id, bookmarked=new_bm)
        return {"ok": True, "bookmarked": new_bm}
    # Sync to DB so bookmarks survive restarts
    await db.update_story_state(story_id, bookmarked=bookmarked)
    return {"ok": True, "bookmarked": bookmarked}


@router.get("/bookmarked", summary="List bookmarked stories")
async def list_bookmarked(
    x_api_key: str | None = Header(None),
):
    """
    Returns all bookmarked stories, sourced from the persistent DB so
    bookmarks survive app restarts / in-memory evictions.
    """
    _validate_api_key(x_api_key)
    # DB-backed query: covers stories bookmarked across sessions/restarts
    import datetime as _dt
    # Use update_story_state + a direct search query for bookmarked=True
    stories = await db.get_stories(
        per_page=200,  # generous cap for bookmarks view
    )
    bookmarked = [s for s in stories if s.bookmarked]
    bookmarked.sort(
        key=lambda s: s.published_at or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc),
        reverse=True,
    )
    return {"stories": [s.model_dump() for s in bookmarked]}
