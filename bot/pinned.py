import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Bot
from telethon import TelegramClient
from telethon.tl.types import InputMessagesFilterPinned

from bot.atomic_io import atomic_write_json
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
    atomic_write_json(_pinned_path(data_dir), {"date": date, "text": text})


async def check_and_forward_pinned(
    userbot: TelegramClient, bot: Bot, config: Config,
) -> str | None:
    try:
        pinned_msg = None
        async for msg in userbot.iter_messages(
            config.source_chat_id, filter=InputMessagesFilterPinned(), limit=1
        ):
            pinned_msg = msg

        if not pinned_msg or not pinned_msg.text:
            return None

        pinned_text = pinned_msg.text
        pinned_date = pinned_msg.date.astimezone(MSK).strftime("%Y-%m-%d %H:%M")

        old = _load_pinned(config.data_dir)

        if old is not None and old.get("text") == pinned_text:
            return None

        _save_pinned(config.data_dir, pinned_date, pinned_text)
        logger.info("Pinned message changed, forwarding")

        source_entity = await userbot.get_entity(config.source_chat_id)
        chat_name = getattr(source_entity, "title", str(config.source_chat_id))
        msg_time = datetime.now(MSK).strftime("%H:%M")

        await bot.send_message(
            chat_id=config.dest_chat_id,
            text=f"📌 Обновлён закреп • {chat_name} • {msg_time} МСК",
            message_thread_id=config.dest_topic_id,
        )

        await userbot.forward_messages(
            entity=config.dest_chat_id,
            messages=pinned_msg.id,
            from_peer=config.source_chat_id,
        )

        preview = pinned_text[:200]
        if len(pinned_text) > 200:
            preview += "…"
        return preview

    except Exception:
        logger.exception("Failed to check/forward pinned message")
        return None
