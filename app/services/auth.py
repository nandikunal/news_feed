import aiosqlite
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
import uuid
from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_db_path = settings.DB_PATH


async def _ensure_users_table():
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()


def _hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


async def create_user(email: str, password: str, role: str = "user") -> dict:
    await _ensure_users_table()
    uid = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()
    hashed = _hash_password(password)
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT INTO users (id, email, hashed_password, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, email, hashed, role, now),
        )
        await db.commit()
    return {"id": uid, "email": email, "role": role, "created_at": now}


async def get_user_by_email(email: str) -> dict | None:
    await _ensure_users_table()
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute("SELECT id, email, hashed_password, role, created_at FROM users WHERE email = ?", (email,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "email": row[1], "hashed_password": row[2], "role": row[3], "created_at": row[4]}


async def get_user_by_id(user_id: str) -> dict | None:
    await _ensure_users_table()
    async with aiosqlite.connect(_db_path) as db:
        async with db.execute("SELECT id, email, role, created_at FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "email": row[1], "role": row[2], "created_at": row[3]}


async def authenticate_user(email: str, password: str) -> dict | None:
    user = await get_user_by_email(email)
    if not user:
        return None
    if not _verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # use unix timestamp for exp
    to_encode.update({"exp": int(expire.timestamp())})
    encoded = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm="HS256")
    return encoded


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        return None
