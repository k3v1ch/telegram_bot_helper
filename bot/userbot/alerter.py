import logging
import re
import time
from datetime import timedelta, timezone

from telegram import Bot
from telethon import TelegramClient, events
from telethon.tl.types import MessageService

from bot.db.models import Chat

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

IP_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.(?:\d{1,3}|xxx|\*)")

DEFAULT_KEYWORDS = [
    "выведен из бс",
    "добавлен в бс",
    "упал",
    "лег намертво",
    "критично",
    "срочно",
]

DEBOUNCE_SECONDS = 600

_debounce_state: dict[int, dict[str, float]] = {}


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_KEYWORDS)
    items = [kw.strip().lower() for kw in raw.split(",")]
    items = [kw for kw in items if kw]
    return items or list(DEFAULT_KEYWORDS)


def _parse_source(source: str) -> tuple[int, int]:
    chat_str, topic_str = source.split(":", 1)
    return int(chat_str), int(topic_str)


def _is_debounced(chat_id: int, sender: str, keyword: str) -> bool:
    debounce = _debounce_state.setdefault(chat_id, {})
    key = f"{sender}:{keyword}"
    now = time.monotonic()
    if key in debounce and now - debounce[key] < DEBOUNCE_SECONDS:
        return True
    debounce[key] = now
    return False


def _check_alert(chat_id: int, text: str, sender: str, keywords: list[str]) -> str | None:
    text_lower = text.lower()
    for kw in keywords:
        if kw in text_lower and not _is_debounced(chat_id, sender, kw):
            return kw
    if IP_PATTERN.search(text):
        for kw in keywords:
            if kw in text_lower and not _is_debounced(chat_id, sender, f"ip+{kw}"):
                return f"IP+{kw}"
    return None


def register_alert(
    client: TelegramClient,
    chat: Chat,
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int | None,
) -> None:
    source_chat_id, source_topic_id = _parse_source(chat.source)
    thread_id = dest_topic_id or None
    keywords = parse_keywords(chat.alert_keywords)

    @client.on(events.NewMessage(chats=source_chat_id))
    async def handler(event):
        if not chat.alerts_enabled:
            return

        msg = event.message
        if isinstance(msg, MessageService) or not msg.text:
            return

        if msg.reply_to and msg.reply_to.reply_to_top_id:
            topic_id = msg.reply_to.reply_to_top_id
        elif msg.reply_to:
            topic_id = msg.reply_to.reply_to_msg_id
        else:
            return

        if topic_id != source_topic_id:
            return

        sender = await msg.get_sender()
        sender_name = sender.first_name or sender.username or "Unknown" if sender else "Unknown"

        matched = _check_alert(chat.id, msg.text, sender_name, keywords)
        if matched is None:
            return

        msg_time = msg.date.astimezone(MSK).strftime("%H:%M")
        alert_text = (
            f"⚡ Алерт • {chat.name} • {msg_time} МСК\n"
            f"🔑 {matched}\n"
            f"👤 {sender_name}: {msg.text}"
        )

        try:
            await bot.send_message(
                chat_id=dest_chat_id,
                text=alert_text,
                message_thread_id=thread_id,
            )
            logger.info(f"Alert sent for chat {chat.id}: {sender_name} ({matched}) at {msg_time}")
        except Exception:
            logger.exception(f"Failed to send alert for chat {chat.id}")

    logger.info(
        f"Alerter registered for chat {chat.id} ({chat.name}) with {len(keywords)} keyword(s)"
    )
