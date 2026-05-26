from fastapi import APIRouter, Header, HTTPException, Request
from app.core.config import settings
from app.services import store

router = APIRouter(prefix="/v1/stories", tags=["stories"])


def _validate_api_key(x_api_key: str | None) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/{story_id}/read", summary="Mark a story as read")
async def mark_read(
    story_id: str,
    x_api_key: str | None = Header(None),
    x_device_id: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    # Pass device_id so per-device stats work correctly
    ok = store.mark_read(story_id, device_id=x_device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"ok": True, "story_id": story_id}


@router.post("/{story_id}/like", summary="Toggle like on a story")
async def like_story(
    story_id: str,
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    liked = store.toggle_like(story_id)
    if liked is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"ok": True, "liked": liked}


@router.post("/{story_id}/bookmark", summary="Toggle bookmark on a story")
async def bookmark_story(
    story_id: str,
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    bookmarked = store.toggle_bookmark(story_id)
    if bookmarked is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"ok": True, "bookmarked": bookmarked}


@router.get("/bookmarked", summary="List bookmarked stories")
async def list_bookmarked(
    x_api_key: str | None = Header(None),
):
    _validate_api_key(x_api_key)
    stories = [
        s for s in store._stories.values() if s.bookmarked
    ]
    stories.sort(key=lambda s: s.published_at or __import__('datetime').datetime.min, reverse=True)
    return {"stories": [s.model_dump() for s in stories]}
