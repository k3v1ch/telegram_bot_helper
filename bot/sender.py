import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
MAX_MSG_LENGTH = 4000

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _arrow(diff: int) -> str:
    if diff > 0:
        return f"▲ +{diff}"
    if diff < 0:
        return f"▼ {diff}"
    return "= 0"


def _is_weekly(period: str) -> bool:
    return period in {"7d", "168h"} or period.endswith("d")


def _build_header(
    chat_name: str,
    total_count: int,
    s1_count: int,
    s2_count: int,
    yesterday_count: int | None,
    period: str,
    start_time: str | None,
    end_time: str | None,
) -> str:
    now = datetime.now(MSK)
    weekly = _is_weekly(period)

    if weekly:
        week_ago = now - timedelta(days=7)
        date_line = (
            f"📅 {week_ago.day} {MONTHS_RU[week_ago.month]} – "
            f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        )
        title = f"📋 Еженедельный дайджест • {chat_name}"
    else:
        date_str = f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        if start_time and end_time:
            date_line = f"📅 {date_str} • {start_time} – {end_time} МСК"
        else:
            date_line = f"📅 {date_str}"
        title = f"📋 Дайджест • {chat_name}"

    lines = [
        title,
        date_line,
        f"💬 Проанализировано сообщений: {total_count}",
    ]

    if not weekly and yesterday_count is not None:
        lines.append(
            f"📊 Вчера: {yesterday_count} → сегодня: {total_count} ({_arrow(total_count - yesterday_count)})"
        )

    lines.append(f"🔍 Обработано: {total_count} → {s1_count} → {s2_count}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


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


async def send_digest(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int,
    chat_name: str,
    digest_text: str,
    total_count: int,
    s1_count: int,
    s2_count: int,
    yesterday_count: int | None,
    period: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> None:
    header = _build_header(
        chat_name=chat_name,
        total_count=total_count,
        s1_count=s1_count,
        s2_count=s2_count,
        yesterday_count=yesterday_count,
        period=period,
        start_time=start_time,
        end_time=end_time,
    )
    full = header + digest_text
    thread_id = dest_topic_id or None
    for chunk in _split_message(full):
        await bot.send_message(
            chat_id=dest_chat_id,
            text=chunk,
            message_thread_id=thread_id,
        )
    logger.info(f"Digest sent to {dest_chat_id} (chat={chat_name}, period={period})")


async def send_empty_notice(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int,
    chat_name: str,
    period: str,
) -> None:
    text = f"💤 За период {period} в чате «{chat_name}» ничего важного"
    await bot.send_message(
        chat_id=dest_chat_id,
        text=text,
        message_thread_id=dest_topic_id or None,
    )


def sanitize_error(error: str, max_len: int = 300) -> str:
    safe = str(error).replace("\n", " ").replace("\r", " ").strip()
    if len(safe) > max_len:
        safe = safe[:max_len] + "…"
    return safe


async def send_error(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int,
    chat_name: str,
    error: str,
) -> None:
    safe = sanitize_error(error)
    await bot.send_message(
        chat_id=dest_chat_id,
        text=f"⚠️ Ошибка при формировании дайджеста «{chat_name}»:\n{safe}",
        message_thread_id=dest_topic_id or None,
    )
    logger.error(f"Error notification sent for {chat_name}: {safe}")
