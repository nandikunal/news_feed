from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.security import require_read_access
from app.models.schemas import StoryCard, ActionResponse
from app.services import database as db

router = APIRouter(prefix="/v1/stories", tags=["Story Actions"])


def _get_device_id(x_device_id: str = Header(default="anonymous")) -> str:
    return x_device_id or "anonymous"


@router.get("/{story_id}", response_model=StoryCard)
async def get_story(
    story_id: str,
    _=Depends(require_read_access),
):
    story = await db.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.post("/{story_id}/read", response_model=ActionResponse)
async def mark_read(
    story_id: str,
    device_id: str = Depends(_get_device_id),
    _=Depends(require_read_access),
):
    """
    Marks a story as read for this specific device.
    Scoped via X-Device-ID header so each device has its own read history.
    After this call, GET /v1/today will no longer return this story for the device.
    Also updates the global read flag for backward compatibility.

    Fix: was calling db.mark_story_read_for_device which does not exist.
    Correct function is db.mark_story_read_in_session (idempotent, returns None).
    Guard against 404 by checking story existence separately.
    """
    story = await db.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    # mark_story_read_in_session is idempotent and returns None
    await db.mark_story_read_in_session(device_id, story_id)
    return ActionResponse(success=True, message="Marked as read")


@router.post("/{story_id}/like", response_model=ActionResponse)
async def like_story(
    story_id: str,
    _=Depends(require_read_access),
):
    new_state = await db.toggle_story_field(story_id, "liked")
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(
        success=True, message="Liked" if new_state else "Unliked"
    )


@router.post("/{story_id}/bookmark", response_model=ActionResponse)
async def bookmark_story(
    story_id: str,
    _=Depends(require_read_access),
):
    new_state = await db.toggle_story_field(story_id, "bookmarked")
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(
        success=True, message="Bookmarked" if new_state else "Unbookmarked"
    )
