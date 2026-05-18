from fastapi import APIRouter, Depends, HTTPException
from app.core.security import require_read_access
from app.models.schemas import StoryCard, ActionResponse
from app.services import database as db

router = APIRouter(prefix="/v1/stories", tags=["Story Actions"])


@router.get(
    "/{story_id}",
    response_model=StoryCard,
    summary="Get full story detail",
)
async def get_story(story_id: str, _=Depends(require_read_access)):
    story = await db.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.post(
    "/{story_id}/read",
    response_model=ActionResponse,
    summary="Mark story as read",
)
async def mark_read(story_id: str, _=Depends(require_read_access)):
    if not await db.update_story_state(story_id, "read", True):
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Marked as read")


@router.post(
    "/{story_id}/like",
    response_model=ActionResponse,
    summary="Toggle like on a story",
)
async def like_story(story_id: str, _=Depends(require_read_access)):
    new_state = await db.toggle_story_field(story_id, "liked")
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Liked" if new_state else "Unliked")


@router.post(
    "/{story_id}/bookmark",
    response_model=ActionResponse,
    summary="Toggle bookmark on a story",
)
async def bookmark_story(story_id: str, _=Depends(require_read_access)):
    new_state = await db.toggle_story_field(story_id, "bookmarked")
    if new_state is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return ActionResponse(success=True, message="Bookmarked" if new_state else "Unbookmarked")
