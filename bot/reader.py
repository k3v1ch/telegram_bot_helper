import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.types import MessageService

from bot.config import Config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


async def fetch_messages(client: TelegramClient, config: Config, lookback_hours: int | None = None) -> list[dict]:
    hours = lookback_hours if lookback_hours is not None else config.lookback_hours
    cutoff = datetime.now(MSK) - timedelta(hours=hours)
    messages = []

    entity = await client.get_entity(config.source_chat_id)

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
        if not msg.text:
            continue

        sender = await msg.get_sender()
        if sender:
            name = sender.first_name or sender.username or "Unknown"
        else:
            name = "Unknown"

        messages.append({
            "time": msg_time.strftime("%H:%M"),
            "sender": name,
            "text": msg.text,
        })

    logger.info(f"Total messages scanned from topic: {total_fetched}")
    messages.reverse()
    logger.info(f"Messages after filtering: {len(messages)}")
    if messages:
        logger.info(f"Time range: {messages[0]['time']} — {messages[-1]['time']} MSK")
    return messages
