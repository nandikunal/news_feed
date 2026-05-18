from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.security import require_read_access
from app.models.schemas import StoryCard, ActionResponse
from app.services import database as db

router = APIRouter(prefix="/v1/stories", tags=["Story Actions"])


def _get_session_id(request: Request) -> str:
    """Extract X-Session-ID header; fall back to 'default' if absent."""
    return request.headers.get("X-Session-ID", "default")


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
    summary="Mark story as read (session-scoped)",
)
async def mark_read(
    story_id: str,
    request: Request,
    _=Depends(require_read_access),
):
    """
    Records a read event for the current session.
    - Updates the global read flag on the story row (for analytics).
    - Stores (session_id, story_id) in session_reads so this story
      is excluded from future GET /v1/today calls for this session.
    """
    if not await db.get_story(story_id):
        raise HTTPException(status_code=404, detail="Story not found")
    session_id = _get_session_id(request)
    await db.mark_story_read_for_session(session_id, story_id)
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
