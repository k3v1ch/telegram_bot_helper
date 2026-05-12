import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import CB_CANCEL, back_to_chat, cancel_inline
from bot.states import SEARCH_QUERY

logger = logging.getLogger(__name__)

MAX_RESULTS = 5
MAX_LINES_PER_DIGEST = 2


@check_blocked
async def search_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None or update.callback_query.data is None:
        return ConversationHandler.END
    await update.callback_query.answer()

    try:
        chat_id = int(update.callback_query.data.split(":", 1)[1])
    except ValueError:
        return ConversationHandler.END

    context.user_data["search_chat_id"] = chat_id
    await update.callback_query.edit_message_text(
        "🔎 Введите слово для поиска:",
        reply_markup=cancel_inline(),
    )
    return SEARCH_QUERY


@check_blocked
async def search_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return SEARCH_QUERY
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text(
            "❌ Введите непустое слово:",
            reply_markup=cancel_inline(),
        )
        return SEARCH_QUERY

    chat_id = context.user_data.get("search_chat_id")
    user_id = update.effective_user.id

    async with get_session() as session:
        digests = await crud.search_digests(session, user_id, query, limit=MAX_RESULTS)

    if chat_id is not None:
        digests = [d for d in digests if d.chat_id == chat_id]

    if not digests:
        await update.message.reply_text(
            f"❌ По запросу «{query}» ничего не найдено.",
            reply_markup=back_to_chat(chat_id) if chat_id else None,
        )
        context.user_data.pop("search_chat_id", None)
        return ConversationHandler.END

    lines = [f"🔎 Найдено {len(digests)} дайджест(ов) по «{query}»:\n"]
    for d in digests:
        when = d.created_at.strftime("%d.%m.%Y %H:%M") if d.created_at else "?"
        lines.append(f"📅 {when} • {d.period}")
        matches = _matching_lines(d.raw_text, query, MAX_LINES_PER_DIGEST)
        for m in matches:
            lines.append(f"  · {m}")
        lines.append("")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=back_to_chat(chat_id) if chat_id else None,
    )
    context.user_data.pop("search_chat_id", None)
    return ConversationHandler.END


def _matching_lines(text: str, query: str, limit: int) -> list[str]:
    q = query.lower()
    out: list[str] = []
    for line in text.split("\n"):
        if q in line.lower():
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) > 200:
                stripped = stripped[:200] + "…"
            out.append(stripped)
            if len(out) >= limit:
                break
    return out


async def search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text("❌ Поиск отменён.")
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text("❌ Поиск отменён.")
    context.user_data.pop("search_chat_id", None)
    return ConversationHandler.END


def build_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(search_entry, pattern=r"^search:\d+$")],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_run)],
        },
        fallbacks=[
            CallbackQueryHandler(search_cancel, pattern=rf"^{CB_CANCEL}$"),
            CommandHandler("cancel", search_cancel),
        ],
        name="search_conversation",
        persistent=False,
    )


def build_handlers() -> list:
    return [build_conversation()]
