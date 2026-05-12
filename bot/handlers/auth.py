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
from bot.handlers.cancel import cancel_dispatch, set_cancel_return
from bot.handlers.start import check_blocked
from bot.keyboards import (
    CB_ACCOUNT_ADD,
    CB_ACCOUNT_RECONNECT,
    CB_ACCOUNT_RENAME,
    CB_CANCEL,
    cancel_inline,
)
from bot.states import AUTH_CODE, AUTH_LABEL, AUTH_PASSWORD, AUTH_PHONE, EDIT_SESSION_LABEL

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+\d{10,15}$")
LABEL_MAX = 100


async def _send(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            return
        except Exception:
            pass
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)


# --- Add account -----------------------------------------------------------


@check_blocked
async def auth_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    await _send(
        update,
        "📱 Введите название аккаунта (например: Основной, Рабочий):",
        reply_markup=cancel_inline(),
    )
    context.user_data["auth"] = {}
    set_cancel_return(context, "accounts_list")
    return AUTH_LABEL


@check_blocked
async def auth_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return AUTH_LABEL
    label = (update.message.text or "").strip()
    if not label or len(label) > LABEL_MAX:
        await update.message.reply_text(
            f"❌ Название от 1 до {LABEL_MAX} символов. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return AUTH_LABEL
    context.user_data["auth"]["label"] = label
    await update.message.reply_text(
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
    label = context.user_data.get("auth", {}).get("label", "Аккаунт")
    try:
        session_id, phone_code_hash = await userbot.manager.authorize_new(user_id, phone, label)
    except Exception as e:
        logger.exception("authorize_new failed")
        await update.message.reply_text(
            f"❌ Не удалось отправить код: {e}\nПопробуйте позже.",
        )
        return ConversationHandler.END

    auth_state = context.user_data.setdefault("auth", {})
    auth_state["phone"] = phone
    auth_state["phone_code_hash"] = phone_code_hash
    auth_state["session_id"] = session_id

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
    state = context.user_data.get("auth") or {}
    phone = state.get("phone")
    phone_code_hash = state.get("phone_code_hash")
    session_id = state.get("session_id")
    label = state.get("label", "Аккаунт")
    if not phone or not phone_code_hash or session_id is None:
        await update.message.reply_text("⚠️ Сессия авторизации потеряна. Начните заново.")
        return ConversationHandler.END

    if userbot.manager is None:
        await update.message.reply_text("⚠️ Внутренняя ошибка: менеджер не инициализирован.")
        return ConversationHandler.END

    try:
        await userbot.manager.confirm_code(session_id, phone, code, phone_code_hash)
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 Введите пароль двухфакторной аутентификации:",
            reply_markup=cancel_inline(),
        )
        return AUTH_PASSWORD
    except Exception as e:
        logger.exception("confirm_code failed")
        await update.message.reply_text(
            f"❌ Ошибка авторизации: {e}\nПопробуйте начать заново.",
        )
        context.user_data.pop("auth", None)
        try:
            await userbot.manager.cancel_pending(session_id)
        except Exception:
            pass
        return ConversationHandler.END

    await update.message.reply_text(f"✅ Аккаунт «{label}» подключён!")
    context.user_data.pop("auth", None)
    return ConversationHandler.END


@check_blocked
async def auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return AUTH_PASSWORD
    password = (update.message.text or "").strip()
    state = context.user_data.get("auth") or {}
    phone = state.get("phone")
    phone_code_hash = state.get("phone_code_hash")
    session_id = state.get("session_id")
    label = state.get("label", "Аккаунт")
    if not phone or not phone_code_hash or session_id is None:
        await update.message.reply_text("⚠️ Сессия авторизации потеряна. Начните заново.")
        return ConversationHandler.END

    if userbot.manager is None:
        await update.message.reply_text("⚠️ Внутренняя ошибка: менеджер не инициализирован.")
        return ConversationHandler.END

    try:
        await userbot.manager.confirm_code(
            session_id, phone, "", phone_code_hash, password=password
        )
    except Exception:
        logger.exception("confirm_code (password) failed")
        await update.message.reply_text(
            "❌ Неверный пароль. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return AUTH_PASSWORD

    await update.message.reply_text(f"✅ Аккаунт «{label}» подключён!")
    context.user_data.pop("auth", None)
    return ConversationHandler.END


async def _auth_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telethon-specific cleanup before generic cancel_dispatch runs."""
    state = context.user_data.get("auth") or {}
    session_id = state.get("session_id")
    if session_id is not None and userbot.manager is not None:
        try:
            await userbot.manager.cancel_pending(session_id)
        except Exception:
            pass


async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel that first releases the pending Telethon client, then delegates to the
    generic ``cancel_dispatch`` to return the user to the screen where they started."""
    await _auth_cleanup(context)
    return await cancel_dispatch(update, context)


# --- Reconnect existing session --------------------------------------------


@check_blocked
async def account_reconnect_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart auth wizard for an existing session — the new session row replaces the old one."""
    if update.callback_query is None or update.callback_query.data is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    try:
        session_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return ConversationHandler.END

    async with get_session() as session:
        row = await crud.get_session_by_id(session, session_id)
    if row is None:
        await update.callback_query.edit_message_text("❌ Аккаунт не найден.")
        return ConversationHandler.END

    context.user_data["auth"] = {"label": row.label or "Аккаунт"}
    set_cancel_return(context, "account_detail", session_id)
    await update.callback_query.edit_message_text(
        "📱 Введите номер телефона для переподключения:",
        reply_markup=cancel_inline(),
    )
    return AUTH_PHONE


# --- Rename ----------------------------------------------------------------


@check_blocked
async def rename_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None or update.callback_query.data is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    try:
        session_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return ConversationHandler.END
    context.user_data["rename_session_id"] = session_id
    set_cancel_return(context, "account_detail", session_id)
    await update.callback_query.edit_message_text(
        "✏️ Введите новое название аккаунта:",
        reply_markup=cancel_inline(),
    )
    return EDIT_SESSION_LABEL


@check_blocked
async def rename_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return EDIT_SESSION_LABEL
    label = (update.message.text or "").strip()
    if not label or len(label) > LABEL_MAX:
        await update.message.reply_text(
            f"❌ Название от 1 до {LABEL_MAX} символов. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return EDIT_SESSION_LABEL
    session_id = context.user_data.get("rename_session_id")
    if session_id is None:
        return ConversationHandler.END
    async with get_session() as session:
        await crud.update_session_label(session, session_id, label)
    await update.message.reply_text(f"✅ Аккаунт переименован в «{label}».")
    context.user_data.pop("rename_session_id", None)
    return ConversationHandler.END


# rename_cancel removed — uses generic cancel_dispatch from bot.handlers.cancel


# --- Build conversation handlers -------------------------------------------


def build_auth_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(auth_entry, pattern=rf"^{CB_ACCOUNT_ADD}$"),
            CallbackQueryHandler(account_reconnect_entry, pattern=rf"^{CB_ACCOUNT_RECONNECT}:\d+$"),
        ],
        states={
            AUTH_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_label)],
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


def build_rename_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_entry, pattern=rf"^{CB_ACCOUNT_RENAME}:\d+$")],
        states={
            EDIT_SESSION_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_save)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_dispatch, pattern=rf"^{CB_CANCEL}$"),
            CommandHandler("cancel", cancel_dispatch),
        ],
        name="rename_session",
        persistent=False,
    )


def build_handlers() -> list:
    return [
        build_auth_conversation(),
        build_rename_conversation(),
    ]
