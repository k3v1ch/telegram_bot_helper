import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from bot.config import Config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
MAX_MSG_LENGTH = 4000


async def send_digest(
    client: TelegramClient,
    config: Config,
    digest_text: str,
    message_count: int,
    source_chat_name: str,
) -> None:
    now = datetime.now(MSK)
    date_str = now.strftime("%d.%m.%Y")
    header = f"📋 Дайджест [{source_chat_name}] за {date_str} ({message_count} сообщений)\n\n"
    full_text = header + digest_text

    entity = await client.get_entity(config.dest_chat_id)
    chunks = _split_message(full_text)

    for chunk in chunks:
        await client.send_message(
            entity,
            chunk,
            reply_to=config.dest_topic_id,
        )

    logger.info(f"Digest sent to destination ({len(chunks)} message(s))")


async def send_empty_notice(client: TelegramClient, config: Config) -> None:
    entity = await client.get_entity(config.dest_chat_id)
    await client.send_message(
        entity,
        "💤 За последние 24ч в чате ничего важного",
        reply_to=config.dest_topic_id,
    )
    logger.info("Empty notice sent")


async def send_error(client: TelegramClient, config: Config, error: str) -> None:
    entity = await client.get_entity(config.dest_chat_id)
    await client.send_message(
        entity,
        f"⚠️ Ошибка при формировании дайджеста:\n{error}",
        reply_to=config.dest_topic_id,
    )
    logger.error(f"Error notification sent: {error}")


def _split_message(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LENGTH:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MSG_LENGTH:
            chunks.append(text)
            break

        split_pos = text.rfind("\n", 0, MAX_MSG_LENGTH)
        if split_pos == -1:
            split_pos = MAX_MSG_LENGTH

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")

    return chunks
