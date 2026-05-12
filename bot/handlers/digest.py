import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot import scheduler as scheduler_mod
from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import chat_menu

logger = logging.getLogger(__name__)

PERIODS: dict[str, int] = {
    "digest_run": 24,
    "digest_1h": 1,
    "digest_5h": 5,
    "digest_12h": 12,
    "digest_24h": 24,
    "digest_7d": 168,
}


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
    hours = PERIODS.get(prefix)
    if hours is None:
        return

    user_id = update.effective_user.id
    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
        if chat is None or chat.user_id != user_id:
            await query.edit_message_text("❌ Чат не найден.")
            return

    if scheduler_mod.scheduler is None:
        await query.edit_message_text(
            "⚠️ Scheduler ещё не инициализирован.",
            reply_markup=chat_menu(chat),
        )
        return

    try:
        await query.edit_message_text(f"⏳ Генерирую дайджест за {hours} часов…")
    except Exception:
        pass

    try:
        await scheduler_mod.scheduler.run_digest(chat_id, hours)
    except Exception as e:
        logger.exception("Manual digest run failed")
        await query.edit_message_text(
            f"❌ Ошибка при генерации: {e}",
            reply_markup=chat_menu(chat),
        )
        return

    async with get_session() as session:
        fresh = await crud.get_chat(session, chat_id)
    if fresh is None:
        await query.edit_message_text("✅ Дайджест отправлен.")
        return
    await query.edit_message_text(
        "✅ Дайджест отправлен.",
        reply_markup=chat_menu(fresh),
    )


def build_handlers() -> list:
    pattern = r"^(digest_run|digest_1h|digest_5h|digest_12h|digest_24h|digest_7d):\d+$"
    return [CallbackQueryHandler(digest_callback, pattern=pattern)]
