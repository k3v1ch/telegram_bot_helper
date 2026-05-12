import logging
import re

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telethon.errors import SessionPasswordNeededError

from bot import userbot
from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import CB_CANCEL, account_menu, cancel_inline
from bot.states import AUTH_CODE, AUTH_PASSWORD, AUTH_PHONE

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+\d{10,15}$")


async def _send(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)


@check_blocked
async def auth_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    await _send(
        update,
        "📱 Введите номер телефона в формате +79001234567:",
        reply_markup=cancel_inline(),
    )
    return AUTH_PHONE


@check_blocked
async def auth_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return AUTH_PHONE
    phone = (update.message.text or "").strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text(
            "❌ Неверный формат. Введите номер вида +79001234567:",
            reply_markup=cancel_inline(),
        )
        return AUTH_PHONE

    if userbot.manager is None:
        await update.message.reply_text("⚠️ Внутренняя ошибка: менеджер не инициализирован.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    try:
        phone_code_hash = await userbot.manager.authorize_new(user_id, phone)
    except Exception as e:
        logger.exception("authorize_new failed")
        await update.message.reply_text(
            f"❌ Не удалось отправить код: {e}\nПопробуйте позже.",
        )
        return ConversationHandler.END

    context.user_data["auth_phone"] = phone
    context.user_data["auth_phone_code_hash"] = phone_code_hash

    await update.message.reply_text(
        "✅ Код отправлен. Введите код из Telegram:",
        reply_markup=cancel_inline(),
    )
    return AUTH_CODE


@check_blocked
async def auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return AUTH_CODE
    code = (update.message.text or "").strip()
    phone = context.user_data.get("auth_phone")
    phone_code_hash = context.user_data.get("auth_phone_code_hash")
    if not phone or not phone_code_hash:
        await update.message.reply_text("⚠️ Сессия авторизации потеряна. Начните заново.")
        return ConversationHandler.END

    if userbot.manager is None:
        await update.message.reply_text("⚠️ Внутренняя ошибка: менеджер не инициализирован.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    try:
        await userbot.manager.confirm_code(user_id, phone, code, phone_code_hash)
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 Введите пароль двухфакторной аутентификации:",
            reply_markup=cancel_inline(),
        )
        return AUTH_PASSWORD
    except Exception as e:
        logger.exception("confirm_code failed")
        await update.message.reply_text(
            f"❌ Ошибка авторизации: {e}\nПопробуйте начать заново через /start.",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Аккаунт успешно подключён!",
        reply_markup=account_menu(is_authorized=True),
    )
    context.user_data.pop("auth_phone", None)
    context.user_data.pop("auth_phone_code_hash", None)
    return ConversationHandler.END


@check_blocked
async def auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return AUTH_PASSWORD
    password = (update.message.text or "").strip()
    phone = context.user_data.get("auth_phone")
    phone_code_hash = context.user_data.get("auth_phone_code_hash")
    if not phone or not phone_code_hash:
        await update.message.reply_text("⚠️ Сессия авторизации потеряна. Начните заново.")
        return ConversationHandler.END

    if userbot.manager is None:
        await update.message.reply_text("⚠️ Внутренняя ошибка: менеджер не инициализирован.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    try:
        await userbot.manager.confirm_code(
            user_id, phone, "", phone_code_hash, password=password
        )
    except Exception as e:
        logger.exception("confirm_code (password) failed")
        await update.message.reply_text(
            "❌ Неверный пароль. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return AUTH_PASSWORD

    await update.message.reply_text(
        "✅ Аккаунт успешно подключён!",
        reply_markup=account_menu(is_authorized=True),
    )
    context.user_data.pop("auth_phone", None)
    context.user_data.pop("auth_phone_code_hash", None)
    return ConversationHandler.END


async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Авторизация отменена.")
    elif update.message:
        await update.message.reply_text("❌ Авторизация отменена.")
    context.user_data.pop("auth_phone", None)
    context.user_data.pop("auth_phone_code_hash", None)
    return ConversationHandler.END


@check_blocked
async def account_reconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await auth_entry(update, context)


@check_blocked
async def account_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    user_id = update.effective_user.id

    if userbot.manager is not None:
        try:
            await userbot.manager.revoke(user_id)
        except Exception:
            logger.exception("revoke failed")

    await update.callback_query.edit_message_text(
        "❌ Аккаунт отключён.",
        reply_markup=account_menu(is_authorized=False),
    )


def build_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(auth_entry, pattern=r"^account_add$"),
            CallbackQueryHandler(account_reconnect, pattern=r"^account_reconnect$"),
        ],
        states={
            AUTH_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_phone)],
            AUTH_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_code)],
            AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_password)],
        },
        fallbacks=[
            CallbackQueryHandler(auth_cancel, pattern=rf"^{CB_CANCEL}$"),
            CommandHandler("cancel", auth_cancel),
        ],
        name="auth_conversation",
        persistent=False,
    )


def build_handlers() -> list:
    return [
        build_conversation(),
        CallbackQueryHandler(account_revoke, pattern=r"^account_revoke$"),
    ]
