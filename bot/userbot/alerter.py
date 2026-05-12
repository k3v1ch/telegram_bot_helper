import logging
import re
import time
from datetime import timedelta, timezone

from telegram import Bot
from telethon import TelegramClient, events
from telethon.tl.types import MessageService

from bot.config import Config
from bot.state import BotState

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


class Alerter:
    def __init__(self, userbot: TelegramClient, bot: Bot, config: Config, state: BotState):
        self.userbot = userbot
        self.bot = bot
        self.config = config
        self.state = state
        self._debounce: dict[str, float] = {}
        self._chat_name: str | None = None

    async def _get_chat_name(self) -> str:
        if self._chat_name is None:
            try:
                entity = await self.userbot.get_entity(self.config.source_chat_id)
                self._chat_name = getattr(entity, "title", str(self.config.source_chat_id))
            except Exception:
                logger.exception("Failed to resolve source chat name")
                self._chat_name = str(self.config.source_chat_id)
        return self._chat_name

    def _is_debounced(self, sender: str, keyword: str) -> bool:
        key = f"{sender}:{keyword}"
        now = time.monotonic()
        if key in self._debounce and now - self._debounce[key] < DEBOUNCE_SECONDS:
            return True
        self._debounce[key] = now
        return False

    def _check_alert(self, text: str, sender: str) -> bool:
        text_lower = text.lower()

        for phrase in HIGH_PRIORITY_PHRASES:
            if phrase in text_lower:
                if not self._is_debounced(sender, phrase):
                    return True

        if IP_PATTERN.search(text):
            for kw in IP_KEYWORDS:
                if kw in text_lower:
                    if not self._is_debounced(sender, kw):
                        return True

        return False

    async def _send_alert(self, sender_name: str, text: str, msg_time: str, chat_name: str) -> None:
        alert = (
            f"⚡ Алерт • {chat_name} • {msg_time} МСК\n"
            f"👤 {sender_name}: {text}"
        )
        try:
            await self.bot.send_message(
                chat_id=self.config.dest_chat_id,
                text=alert,
                message_thread_id=self.config.dest_topic_id,
            )
            logger.info(f"Alert sent: {sender_name} at {msg_time}")
        except Exception:
            logger.exception("Failed to send alert")

    def register(self) -> None:
        @self.userbot.on(events.NewMessage(chats=self.config.source_chat_id))
        async def handler(event):
            if not self.state.alerts_enabled:
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

            if topic_id != self.config.source_topic_id:
                return

            sender = await msg.get_sender()
            sender_name = sender.first_name or sender.username or "Unknown" if sender else "Unknown"

            if not self._check_alert(msg.text, sender_name):
                return

            msg_time = msg.date.astimezone(MSK).strftime("%H:%M")
            chat_name = await self._get_chat_name()

            await self._send_alert(sender_name, msg.text, msg_time, chat_name)

        logger.info("Alerter registered for real-time monitoring")
