import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bot.db import crud
from bot.db.database import get_session
from bot.keyboards import (
    MAIN_ACCOUNT,
    MAIN_ADMIN,
    MAIN_MY_CHATS,
    MAIN_STATS,
    account_menu,
    admin_menu,
    chats_list,
    main_menu,
)

logger = logging.getLogger(__name__)

BLOCKED_TEXT = "⛔ Ваш аккаунт заблокирован."

WELCOME_TEXT = (
    "👋 Добро пожаловать в Digest Bot!\n\n"
    "Я помогаю собирать и анализировать сообщения из ваших Telegram-чатов "
    "и присылать удобные сводки.\n\n"
    "Чтобы начать, подключите свой аккаунт Telegram через меню 📱 Аккаунт."
)


def _admin_user_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return int(context.bot_data.get("admin_user_id", 0))


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return user_id == _admin_user_id(context)


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

    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=main_menu(is_admin=is_admin(user.id, context)),
    )


@check_blocked
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    await update.message.reply_text(
        "Главное меню:",
        reply_markup=main_menu(is_admin=is_admin(update.effective_user.id, context)),
    )


@check_blocked
async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if text == MAIN_MY_CHATS:
        async with get_session() as session:
            chats = await crud.get_user_chats(session, user_id)
        if not chats:
            await update.message.reply_text(
                "У вас пока нет чатов. Нажмите ➕ чтобы добавить.",
                reply_markup=chats_list([]),
            )
        else:
            await update.message.reply_text("Ваши чаты:", reply_markup=chats_list(chats))
        return

    if text == MAIN_ACCOUNT:
        async with get_session() as session:
            session_str = await crud.get_session_str(session, user_id)
        authorized = bool(session_str)
        title = "📱 Ваш аккаунт подключён" if authorized else "📱 Аккаунт не подключён"
        await update.message.reply_text(title, reply_markup=account_menu(authorized))
        return

    if text == MAIN_STATS:
        from bot.handlers.stats import stats_show

        await stats_show(update, context)
        return

    if text == MAIN_ADMIN and is_admin(user_id, context):
        await update.message.reply_text("👑 Админ панель", reply_markup=admin_menu())
        return


def build_handlers() -> list:
    return [
        CommandHandler("start", start_command),
        CommandHandler("menu", menu_command),
        MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router),
    ]
