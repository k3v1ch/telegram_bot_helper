import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot

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
    total_fetched: int | None = None,
    after_stage1: int | None = None,
    after_stage2: int | None = None,
) -> str:
    now = datetime.now(MSK)
    date_str = f"{now.day} {MONTHS_RU[now.month]} {now.year}"

    lines = [
        f"📋 Дайджест • {source_chat_name}",
        f"📅 {date_str} • {start_time} – {end_time} МСК",
        f"💬 Проанализировано сообщений: {message_count}",
    ]

    if total_fetched is not None and after_stage1 is not None and after_stage2 is not None:
        lines.append(f"🔍 Обработано: {total_fetched} → {after_stage1} → {after_stage2} сообщений")

    if yesterday_count is not None:
        diff = message_count - yesterday_count
        if diff > 0:
            arrow = f"▲ +{diff}"
        elif diff < 0:
            arrow = f"▼ {diff}"
        else:
            arrow = "= 0"
        lines.append(f"📊 Вчера: {yesterday_count} → сегодня: {message_count} ({arrow})")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


async def send_digest(
    bot: Bot,
    config: Config,
    digest_text: str,
    message_count: int,
    source_chat_name: str,
    start_time: str,
    end_time: str,
    total_fetched: int | None = None,
    after_stage1: int | None = None,
    after_stage2: int | None = None,
) -> None:
    yesterday_count = get_yesterday_count(config.data_dir)
    header = _build_header(
        source_chat_name, message_count, start_time, end_time, yesterday_count,
        total_fetched, after_stage1, after_stage2,
    )
    full_text = header + digest_text

    chunks = _split_message(full_text)
    for chunk in chunks:
        await bot.send_message(
            chat_id=config.dest_chat_id,
            text=chunk,
            message_thread_id=config.dest_topic_id,
        )

    logger.info(f"Digest sent to destination ({len(chunks)} message(s))")


async def send_empty_notice(bot: Bot, config: Config) -> None:
    await bot.send_message(
        chat_id=config.dest_chat_id,
        text="💤 За последние 24ч в чате ничего важного",
        message_thread_id=config.dest_topic_id,
    )
    logger.info("Empty notice sent")


async def send_error(bot: Bot, config: Config, error: str) -> None:
    await bot.send_message(
        chat_id=config.dest_chat_id,
        text=f"⚠️ Ошибка при формировании дайджеста:\n{error}",
        message_thread_id=config.dest_topic_id,
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
