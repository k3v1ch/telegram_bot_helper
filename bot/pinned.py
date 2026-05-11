import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import InputMessagesFilterPinned

from bot.config import Config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


def _pinned_path(data_dir: Path) -> Path:
    return data_dir / "pinned.json"


def _load_pinned(data_dir: Path) -> dict | None:
    path = _pinned_path(data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load pinned.json")
        return None


def _save_pinned(data_dir: Path, date: str, text: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        _pinned_path(data_dir).write_text(
            json.dumps({"date": date, "text": text}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to save pinned.json")


async def check_pinned_update(client: TelegramClient, config: Config) -> str | None:
    try:
        pinned_msg = None
        async for msg in client.iter_messages(
            config.source_chat_id, filter=InputMessagesFilterPinned(), limit=1
        ):
            pinned_msg = msg

        if not pinned_msg or not pinned_msg.text:
            return None

        pinned_text = pinned_msg.text
        pinned_date = pinned_msg.date.astimezone(MSK).strftime("%Y-%m-%d %H:%M")

        old = _load_pinned(config.data_dir)
        _save_pinned(config.data_dir, pinned_date, pinned_text)

        if old is None or old.get("text") != pinned_text:
            preview = pinned_text[:200]
            if len(pinned_text) > 200:
                preview += "…"
            logger.info("Pinned message changed")
            return preview

        return None
    except Exception:
        logger.exception("Failed to check pinned message")
        return None
