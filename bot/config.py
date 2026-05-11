import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    source_chat_id: int
    source_topic_id: int
    dest_chat_id: int
    dest_topic_id: int
    groq_api_key: str
    digest_time: str
    lookback_hours: int
    session_name: str
    bot_token: str | None
    admin_id: int | None
    alerts_enabled: bool

    @classmethod
    def from_env(cls) -> "Config":
        def require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise ValueError(f"Missing required env var: {key}")
            return val

        def parse_chat_topic(val: str, var_name: str) -> tuple[int, int]:
            if ":" not in val:
                raise ValueError(f"{var_name} must be in format chat_id:topic_id (e.g. -1003332852289:155)")
            chat_str, topic_str = val.split(":", 1)
            return int(chat_str), int(topic_str)

        source_chat_id, source_topic_id = parse_chat_topic(require("SOURCE"), "SOURCE")
        dest_chat_id, dest_topic_id = parse_chat_topic(require("DEST"), "DEST")

        return cls(
            telegram_api_id=int(require("TELEGRAM_API_ID")),
            telegram_api_hash=require("TELEGRAM_API_HASH"),
            telegram_phone=require("TELEGRAM_PHONE"),
            source_chat_id=source_chat_id,
            source_topic_id=source_topic_id,
            dest_chat_id=dest_chat_id,
            dest_topic_id=dest_topic_id,
            groq_api_key=require("GROQ_API_KEY"),
            digest_time=os.getenv("DIGEST_TIME", "09:00"),
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "24")),
            session_name=os.getenv("SESSION_NAME", "userbot"),
            bot_token=os.getenv("BOT_TOKEN"),
            admin_id=int(admin) if (admin := os.getenv("ADMIN_ID")) else None,
            alerts_enabled=os.getenv("ALERTS_ENABLED", "false").lower() == "true",
        )

    @property
    def data_dir(self) -> Path:
        return Path("/app/data")

    @property
    def session_path(self) -> Path:
        return Path("/app/sessions") / self.session_name

    @property
    def digest_hour(self) -> int:
        return int(self.digest_time.split(":")[0])

    @property
    def digest_minute(self) -> int:
        return int(self.digest_time.split(":")[1])
