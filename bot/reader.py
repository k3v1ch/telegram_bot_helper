import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.types import MessageService

from bot.config import Config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


async def fetch_messages(client: TelegramClient, config: Config) -> list[dict]:
    cutoff = datetime.now(MSK) - timedelta(hours=config.lookback_hours)
    messages = []

    entity = await client.get_entity(config.source_chat_id)

    async for msg in client.iter_messages(
        entity,
        reply_to=config.source_topic_id,
        offset_date=datetime.now(tz=timezone.utc),
    ):
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

    messages.reverse()
    logger.info(f"Fetched {len(messages)} messages from source chat")
    return messages
