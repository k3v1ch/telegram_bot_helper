import logging
import re
import time
from datetime import timedelta, timezone
from typing import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.tl.types import MessageService

from bot.db.models import Chat

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

IP_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.(?:\d{1,3}|xxx|\*)")

IP_KEYWORDS = [
    "выведен", "добавили", "добавлен", "убрали", "убран",
    "заблокирован", "разблокирован", "в бс", "из бс",
    "белый список", "перестал", "не работает", "упал",
]

HIGH_PRIORITY_PHRASES = [
    "выведен из бс", "добавлен в бс", "упал",
    "лег намертво", "критично", "срочно",
]

DEBOUNCE_SECONDS = 600

_debounce_state: dict[int, dict[str, float]] = {}


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


def _check_alert(chat_id: int, text: str, sender: str) -> bool:
    text_lower = text.lower()

    for phrase in HIGH_PRIORITY_PHRASES:
        if phrase in text_lower:
            if not _is_debounced(chat_id, sender, phrase):
                return True

    if IP_PATTERN.search(text):
        for kw in IP_KEYWORDS:
            if kw in text_lower:
                if not _is_debounced(chat_id, sender, kw):
                    return True

    return False


def register_alert(
    client: TelegramClient,
    chat: Chat,
    bot_send_func: Callable[[str], Awaitable[None]],
) -> None:
    source_chat_id, source_topic_id = _parse_source(chat.source)

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

        if not _check_alert(chat.id, msg.text, sender_name):
            return

        msg_time = msg.date.astimezone(MSK).strftime("%H:%M")
        alert_text = (
            f"⚡ Алерт • {chat.name} • {msg_time} МСК\n"
            f"👤 {sender_name}: {msg.text}"
        )

        try:
            await bot_send_func(alert_text)
            logger.info(f"Alert sent for chat {chat.id}: {sender_name} at {msg_time}")
        except Exception:
            logger.exception(f"Failed to send alert for chat {chat.id}")

    logger.info(f"Alerter registered for chat {chat.id} ({chat.name})")
