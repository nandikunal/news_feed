from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from app.services import auth as auth_service
from app.models.schemas import ActionResponse
from datetime import timedelta

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", response_model=ActionResponse)
async def register(req: RegisterRequest):
    existing = await auth_service.get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = await auth_service.create_user(req.email, req.password)
    return ActionResponse(success=True, message=f"User {user['email']} created")


@router.post("/login")
async def login(req: LoginRequest):
    user = await auth_service.authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = auth_service.create_access_token({"sub": user["id"], "email": user["email"], "role": user["role"]}, expires_delta=timedelta(minutes=60*24))
    return {"access_token": access_token, "token_type": "bearer"}
