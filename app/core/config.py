from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_ENV: str = "development"
    API_KEY: str = "dev-api-key"
    ADMIN_API_KEY: str = "dev-admin-key"
    INTERNAL_REFRESH_KEY: str = "dev-internal-refresh-key"  # used by cron / scheduler
    CORS_ORIGINS: str = "http://localhost:3000"
    DB_PATH: str = "news_feed.db"           # swap to ":memory:" for tests
    CACHE_TTL_SECONDS: int = 600            # 10 min — ideal polling cadence for news RSS
    DEDUP_TITLE_THRESHOLD: float = 0.72     # SequenceMatcher ratio for title dedup

    # JWT / IAM settings
    JWT_SECRET_KEY: str = "dev-secret-key"  # override in production
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # FCM push settings
    FCM_SERVER_KEY: str = ""  # set in production for push
    FCM_ENDPOINT: str = "https://fcm.googleapis.com/fcm/send"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
