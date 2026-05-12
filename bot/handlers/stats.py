import logging
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import stats_back

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


async def build_user_stats_text(user_id: int) -> str:
    async with get_session() as session:
        chats = await crud.get_user_chats(session, user_id)
        sessions = await crud.get_user_sessions(session, user_id)
        total_digests = await crud.count_user_digests(session, user_id)
        last_week = datetime.utcnow() - timedelta(days=7)
        recent_digests = await crud.count_user_digests_since(session, user_id, last_week)
        last_digest = await crud.get_last_user_digest(session, user_id)

    authorized = sum(1 for s in sessions if s.is_authorized)
    active = sum(1 for c in chats if c.is_active)

    if last_digest and last_digest.created_at:
        last_dt = last_digest.created_at
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        last_str = last_dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M МСК")
    else:
        last_str = "—"

    return (
        "📊 Ваша статистика\n\n"
        f"📱 Аккаунтов: {len(sessions)} (авторизованы: {authorized})\n"
        f"💬 Чатов: {len(chats)} (активных: {active})\n"
        f"📋 Дайджестов всего: {total_digests}\n"
        f"📋 За последние 7 дней: {recent_digests}\n"
        f"📅 Последний дайджест: {last_str}"
    )


@check_blocked
async def stats_show_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.callback_query is None:
        return
    await update.callback_query.answer()
    try:
        text = await build_user_stats_text(user.id)
    except Exception:
        logger.exception("stats_show failed")
        await update.callback_query.edit_message_text(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=stats_back(),
        )
        return
    await update.callback_query.edit_message_text(text, reply_markup=stats_back())


def build_handlers() -> list:
    return []
