import logging
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot import userbot
from bot.analyzer import analyze_messages
from bot.config import Config
from bot.db import crud
from bot.db.database import get_session
from bot.db.models import Chat
from bot.handlers.start import check_blocked
from bot.keyboards import chat_menu
from bot.userbot.reader import fetch_messages

logger = logging.getLogger(__name__)

MAX_MSG_LENGTH = 4000
MSK = timezone(timedelta(hours=3))

PERIODS = {
    "digest_run": (24, False, "24h"),
    "digest_1h": (1, False, "1h"),
    "digest_5h": (5, False, "5h"),
    "digest_12h": (12, False, "12h"),
    "digest_24h": (24, False, "24h"),
    "digest_7d": (168, True, "7d"),
}


def _parse_target(value: str) -> tuple[int, int]:
    chat_str, topic_str = value.split(":", 1)
    return int(chat_str), int(topic_str)


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


def _build_header(chat: Chat, message_count: int, weekly: bool) -> str:
    now = datetime.now(MSK)
    date_str = now.strftime("%d.%m.%Y %H:%M")
    title = "📋 Еженедельный дайджест" if weekly else "📋 Дайджест"
    return (
        f"{title} • {chat.name}\n"
        f"📅 {date_str} МСК\n"
        f"💬 Сообщений: {message_count}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )


@check_blocked
async def digest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()

    try:
        prefix, chat_id_str = query.data.split(":", 1)
        chat_id = int(chat_id_str)
    except ValueError:
        return
    spec = PERIODS.get(prefix)
    if spec is None:
        return
    hours, weekly, period_label = spec

    user_id = update.effective_user.id

    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
        if chat is None or chat.user_id != user_id:
            await query.edit_message_text("❌ Чат не найден.")
            return

    if userbot.manager is None or not await userbot.manager.is_connected(user_id):
        await query.edit_message_text(
            "❌ Userbot не подключён. Сначала подключите аккаунт через 📱 Аккаунт.",
            reply_markup=chat_menu(chat),
        )
        return

    try:
        await query.edit_message_text(f"⏳ Генерирую дайджест за {hours} часов…")
    except Exception:
        pass

    try:
        client = await userbot.manager.get_client(user_id)
        source_chat_id, source_topic_id = _parse_target(chat.source)
        dest_chat_id, dest_topic_id = _parse_target(chat.dest)

        messages = await fetch_messages(
            client,
            source_chat_id=source_chat_id,
            source_topic_id=source_topic_id,
            lookback_hours=hours,
        )

        if not messages:
            await context.bot.send_message(
                chat_id=dest_chat_id,
                message_thread_id=dest_topic_id or None,
                text=f"💤 За последние {hours}ч в чате {chat.name} ничего важного",
            )
        else:
            config: Config = context.bot_data["config"]
            analysis = await analyze_messages(messages, config, weekly=weekly)
            header = _build_header(chat, len(messages), weekly)
            full = header + analysis.text
            for chunk in _split_message(full):
                await context.bot.send_message(
                    chat_id=dest_chat_id,
                    message_thread_id=dest_topic_id or None,
                    text=chunk,
                )
            async with get_session() as session:
                await crud.save_digest(
                    session,
                    chat_id=chat.id,
                    user_id=user_id,
                    period=period_label,
                    raw_text=analysis.text,
                    message_count=len(messages),
                    s1_count=len(messages),
                    s2_count=analysis.after_stage2,
                )
    except Exception as e:
        logger.exception("Digest pipeline failed")
        await query.edit_message_text(
            f"❌ Ошибка при генерации дайджеста: {e}",
            reply_markup=chat_menu(chat),
        )
        return

    async with get_session() as session:
        fresh = await crud.get_chat(session, chat_id)
    if fresh is None:
        await query.edit_message_text("✅ Дайджест отправлен.")
        return
    await query.edit_message_text(
        f"✅ Дайджест отправлен.\n\n{_summary(fresh)}",
        reply_markup=chat_menu(fresh),
    )


def _summary(chat: Chat) -> str:
    status = "✅ Активен" if chat.is_active else "⏸ На паузе"
    alerts = "ВКЛ" if chat.alerts_enabled else "ВЫКЛ"
    return (
        f"📋 {chat.name}\n"
        f"🕐 Расписание: {chat.schedule_time} МСК\n"
        f"⚡ Алерты: {alerts}\n"
        f"Статус: {status}"
    )


def build_handlers() -> list:
    pattern = r"^(digest_run|digest_1h|digest_5h|digest_12h|digest_24h|digest_7d):\d+$"
    return [CallbackQueryHandler(digest_callback, pattern=pattern)]
