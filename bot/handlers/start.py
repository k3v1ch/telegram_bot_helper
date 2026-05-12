import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.db import crud
from bot.db.database import get_session
from bot.keyboards import (
    CB_ADMIN,
    CB_BACK_MAIN,
    CB_CHATS,
    CB_STATS,
    main_menu,
)

logger = logging.getLogger(__name__)

BLOCKED_TEXT = "⛔ Ваш аккаунт заблокирован."
NO_ACCOUNT_ALERT = "⚠️ Сначала подключите аккаунт Telegram"

WELCOME_TEXT = (
    "👋 Добро пожаловать в Digest Bot!\n\n"
    "Я помогаю собирать и анализировать сообщения из Telegram-чатов."
)


def _admin_user_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return int(context.bot_data.get("admin_user_id", 0))


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return user_id == _admin_user_id(context)


async def _has_authorized_session(user_id: int) -> bool:
    async with get_session() as session:
        rows = await crud.get_authorized_sessions(session, user_id=user_id)
    return len(rows) > 0


def check_blocked(func: Callable):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None:
            return
        async with get_session() as session:
            db_user = await crud.get_user(session, user.id)
            if db_user is None:
                if update.message:
                    await update.message.reply_text("Сначала запустите бота: /start")
                elif update.callback_query:
                    await update.callback_query.answer("Сначала /start", show_alert=True)
                return
            if db_user.is_blocked:
                if update.message:
                    await update.message.reply_text(BLOCKED_TEXT)
                elif update.callback_query:
                    await update.callback_query.answer(BLOCKED_TEXT, show_alert=True)
                return
            await crud.update_last_active(session, user.id)
        return await func(update, context, *args, **kwargs)

    return wrapper


def require_session(func: Callable):
    """Block callback if user has no authorized session — show popup alert."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None:
            return
        if not await _has_authorized_session(user.id):
            if update.callback_query:
                await update.callback_query.answer(NO_ACCOUNT_ALERT, show_alert=True)
            elif update.message:
                await update.message.reply_text(NO_ACCOUNT_ALERT)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


async def _send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool) -> None:
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    has_auth = await _has_authorized_session(user_id)
    admin = is_admin(user_id, context)
    markup = main_menu(is_admin=admin, has_authorized_sessions=has_auth)
    text = WELCOME_TEXT if not has_auth else "📋 Главное меню"

    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=markup)
            return
        except Exception:
            pass

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    async with get_session() as session:
        db_user = await crud.get_user(session, user.id)
        if db_user is None:
            db_user = await crud.create_user(
                session, user.id, user.username, user.first_name
            )
            logger.info(f"Created user {user.id} ({user.username})")
        else:
            await crud.update_last_active(session, user.id)

        if db_user.is_blocked:
            await update.message.reply_text(BLOCKED_TEXT)
            return

    await _send_main_menu(update, context, edit=False)


@check_blocked
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_main_menu(update, context, edit=False)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the main menu as a new message (used by cancel handlers)."""
    await _send_main_menu(update, context, edit=False)


@check_blocked
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    await _send_main_menu(update, context, edit=True)


@check_blocked
@require_session
async def open_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Delegate to chats handler
    from bot.handlers.chats import chats_show

    await chats_show(update, context)


@check_blocked
@require_session
async def open_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.handlers.stats import stats_show_inline

    await stats_show_inline(update, context)


@check_blocked
async def open_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    if not is_admin(update.effective_user.id, context):
        if update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
        return
    from bot.handlers.admin import admin_back

    await admin_back(update, context)


def build_handlers() -> tuple:
    """Return the start command, menu command, back-to-main callback,
    and the trio of gated callbacks (chats/stats/admin) registered before generic routers."""
    return (
        CommandHandler("start", start_command),
        CommandHandler("menu", menu_command),
        CallbackQueryHandler(back_to_main, pattern=rf"^{CB_BACK_MAIN}$"),
        [
            CallbackQueryHandler(open_chats, pattern=rf"^{CB_CHATS}$"),
            CallbackQueryHandler(open_stats, pattern=rf"^{CB_STATS}$"),
            CallbackQueryHandler(open_admin, pattern=rf"^{CB_ADMIN}$"),
        ],
    )
