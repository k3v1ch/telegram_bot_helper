import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.types import MessageService

from bot.config import Config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

EMOJI_ONLY = re.compile(
    r"^[\U0001f000-\U0001ffff\U00002600-\U000027bf\U0000fe00-\U0000feff"
    r"\U0001fa00-\U0001faff\U00002702-\U000027b0\U0000200d\U000020e3"
    r"\U0000fe0f\U00003030\U0000303d\U00002049\U00002139"
    r"\s]+$"
)


@dataclass
class FetchResult:
    messages: list[dict]
    total_fetched: int
    after_stage1: int


async def fetch_messages(client: TelegramClient, config: Config, lookback_hours: int | None = None) -> FetchResult:
    hours = lookback_hours if lookback_hours is not None else config.lookback_hours
    cutoff = datetime.now(MSK) - timedelta(hours=hours)

    entity = await client.get_entity(config.source_chat_id)

    raw = []
    total_fetched = 0
    async for msg in client.iter_messages(
        entity,
        reply_to=config.source_topic_id,
        offset_date=datetime.now(tz=timezone.utc),
    ):
        total_fetched += 1
        msg_time = msg.date.astimezone(MSK)
        if msg_time < cutoff:
            break

        if isinstance(msg, MessageService):
            continue
        if getattr(msg, "action", None) is not None:
            continue
        if getattr(msg, "voice", None) is not None:
            continue
        if getattr(msg, "sticker", None) is not None and not msg.text:
            continue
        if (getattr(msg, "gif", None) is not None or getattr(msg, "animation", None) is not None) and not msg.text:
            continue
        if getattr(msg, "forward", None) is not None and not msg.text:
            continue
        if not msg.text:
            continue
        if EMOJI_ONLY.match(msg.text):
            continue

        sender = await msg.get_sender()
        name = sender.first_name or sender.username or "Unknown" if sender else "Unknown"

        raw.append({
            "time": msg_time.strftime("%H:%M"),
            "sender": name,
            "text": msg.text,
        })

    raw.reverse()
    after_stage1 = len(raw)
    removed = total_fetched - after_stage1

    logger.info(f"Stage 1: scanned {total_fetched}, kept {after_stage1}, removed {removed}")
    if raw:
        logger.info(f"Time range: {raw[0]['time']} — {raw[-1]['time']} MSK")

    return FetchResult(messages=raw, total_fetched=total_fetched, after_stage1=after_stage1)
