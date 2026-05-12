import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str
    admin_user_id: int
    groq_api_key: str
    database_url: str
    telegram_api_id: int
    telegram_api_hash: str

    @classmethod
    def from_env(cls) -> "Config":
        def require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise ValueError(f"Missing required env var: {key}")
            return val

        return cls(
            bot_token=require("BOT_TOKEN"),
            admin_user_id=int(require("ADMIN_USER_ID")),
            groq_api_key=require("GROQ_API_KEY"),
            database_url=require("DATABASE_URL"),
            telegram_api_id=int(require("TELEGRAM_API_ID")),
            telegram_api_hash=require("TELEGRAM_API_HASH"),
        )
