import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from bot.config import Config
from bot.stats import get_yesterday_count

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
MAX_MSG_LENGTH = 4000

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _build_header(
    source_chat_name: str,
    message_count: int,
    start_time: str,
    end_time: str,
    yesterday_count: int | None,
) -> str:
    now = datetime.now(MSK)
    date_str = f"{now.day} {MONTHS_RU[now.month]} {now.year}"

    lines = [
        f"📋 Дайджест • {source_chat_name}",
        f"📅 {date_str} • {start_time} – {end_time} МСК",
        f"💬 Проанализировано сообщений: {message_count}",
    ]

    if yesterday_count is not None:
        diff = message_count - yesterday_count
        if diff > 0:
            arrow = f"▲ +{diff}"
        elif diff < 0:
            arrow = f"▼ {diff}"
        else:
            arrow = "= 0"
        lines.append(f"📊 Вчера: {yesterday_count} сообщений → сегодня: {message_count} ({arrow})")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


async def send_digest(
    client: TelegramClient,
    config: Config,
    digest_text: str,
    message_count: int,
    source_chat_name: str,
    start_time: str,
    end_time: str,
) -> None:
    yesterday_count = get_yesterday_count(config.data_dir)
    header = _build_header(source_chat_name, message_count, start_time, end_time, yesterday_count)
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
