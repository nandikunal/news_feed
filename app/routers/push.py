from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import require_user
from app.services import push as push_service
from app.models.schemas import ActionResponse

router = APIRouter(prefix="/v1/push", tags=["Push"])


class RegisterTokenRequest(BaseModel):
    token: str
    platform: str = "android"


@router.post("/register", response_model=ActionResponse)
async def register_token(req: RegisterTokenRequest, user=Depends(require_user)):
    await push_service.create_device_token(user["id"], req.token, req.platform)
    return ActionResponse(success=True, message="Device token registered")


class UnregisterTokenRequest(BaseModel):
    token: str


@router.post("/unregister", response_model=ActionResponse)
async def unregister_token(req: UnregisterTokenRequest, user=Depends(require_user)):
    await push_service.delete_device_token(user["id"], req.token)
    return ActionResponse(success=True, message="Device token removed")
