from fastapi import APIRouter, Depends, HTTPException
from app.core.security import require_read_access
from app.models.schemas import StoryCard, ActionResponse
from app.services import store

router = APIRouter(prefix="/v1/stories", tags=["Story Actions"])


@router.get(
    "/{story_id}",
    response_model=StoryCard,
    summary="Get full story detail",
)
async def get_story(story_id: str, _=Depends(require_read_access)):
    """Returns the full story card including current read/like/bookmark state."""
    story = store.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.post(
    "/{story_id}/read",
    response_model=ActionResponse,
    summary="Mark story as read",
)
async def mark_read(story_id: str, _=Depends(require_read_access)):
    """Called automatically by the mobile app after 1.5 seconds of viewing."""
    if not store.mark_read(story_id):
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Marked as read")


@router.post(
    "/{story_id}/like",
    response_model=ActionResponse,
    summary="Toggle like on a story",
)
async def like_story(story_id: str, _=Depends(require_read_access)):
    """Toggles like state. Returns message: Liked or Unliked."""
    new_state = store.toggle_like(story_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Liked" if new_state else "Unliked")


@router.post(
    "/{story_id}/bookmark",
    response_model=ActionResponse,
    summary="Toggle bookmark on a story",
)
async def bookmark_story(story_id: str, _=Depends(require_read_access)):
    """Toggles bookmark state. Returns message: Bookmarked or Unbookmarked."""
    new_state = store.toggle_bookmark(story_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Bookmarked" if new_state else "Unbookmarked")
