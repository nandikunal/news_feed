import httpx
from typing import List, Dict
from app.core.config import settings
from app.services import database as db
import logging

logger = logging.getLogger(__name__)

FCM_ENDPOINT = settings.FCM_ENDPOINT
FCM_KEY = settings.FCM_SERVER_KEY


async def create_device_token(user_id: str, token: str, platform: str = "android") -> None:
    async with httpx.AsyncClient() as client:
        # store in DB
        async with db._ensure_db_connection():
            pass
    # use DB helper
    await db.create_device_token(user_id, token, platform)


async def delete_device_token(user_id: str, token: str) -> None:
    await db.delete_device_token(user_id, token)


async def list_tokens_for_user(user_id: str) -> List[Dict]:
    return await db.list_device_tokens(user_id)


async def send_push_to_tokens(tokens: List[str], title: str, body: str, data: Dict | None = None) -> Dict:
    if not FCM_KEY:
        logger.warning("FCM key not configured — skipping push send")
        return {"skipped": True}
    payload = {
        "registration_ids": tokens,
        "notification": {"title": title, "body": body},
    }
    if data:
        payload["data"] = data
    headers = {"Authorization": f"key={FCM_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        r = await client.post(FCM_ENDPOINT, json=payload, headers=headers, timeout=10)
        logger.info(f"FCM response: {r.status_code} {r.text}")
        return {"status_code": r.status_code, "text": r.text}


async def notify_new_stories(new_stories: List[Dict]):
    # gather tokens across all users
    tokens = await db.list_all_device_tokens()
    if not tokens:
        return
    reg_ids = [t['token'] for t in tokens]
    title = "New stories available"
    body = f"{len(new_stories)} new stories — open Kiezlink to read."
    await send_push_to_tokens(reg_ids, title, body, data={"type": "new_stories"})
