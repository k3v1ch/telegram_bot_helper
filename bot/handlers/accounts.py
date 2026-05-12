"""Handlers for the Accounts screen and its sub-flows (list / detail / revoke).

Auth-flow conversations live in ``bot.handlers.auth``; this module only handles
the read-only screens and the destructive revoke action.

Each public screen exposes two flavours:
    - ``*_show``  — callback handler that edits the current message
    - ``send_*_screen`` — sends the screen as a NEW message (used by cancel
      handlers in :mod:`bot.handlers.cancel`).
"""

import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot import userbot
from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import (
    CB_ACCOUNT_OPEN_PREFIX,
    CB_ACCOUNT_REVOKE,
    CB_ACCOUNT_REVOKE_CONFIRM,
    CB_ACCOUNTS,
    account_detail,
    account_revoke_confirm,
    accounts_list,
)

logger = logging.getLogger(__name__)


def _connected_session_ids() -> set[int]:
    if userbot.manager is None:
        return set()
    return set(userbot.manager._clients.keys())


async def _build_accounts_payload(user_id: int):
    async with get_session() as session:
        sessions = await crud.get_user_sessions(session, user_id)
    connected = _connected_session_ids()
    if not sessions:
        text = "👤 У вас пока нет подключённых аккаунтов.\nНажмите ➕ чтобы добавить."
    else:
        text = f"👤 Ваши аккаунты ({len(sessions)})"
    return text, accounts_list(sessions, connected)


async def _build_account_detail_payload(user_id: int, session_id: int):
    async with get_session() as session:
        row = await crud.get_session_by_id(session, session_id)
        if row is None or row.user_id != user_id:
            return None
        chats_count = await crud.count_session_chats(session, session_id)

    connected = session_id in _connected_session_ids()
    status = "🟢 Подключён" if connected else "🔴 Не подключён"
    authorized_at = row.authorized_at.strftime("%d.%m.%Y") if row.authorized_at else "—"

    text = (
        f"📱 {row.phone or '—'}\n"
        f"📝 Название: {row.label or '—'}\n"
        f"{status} • с {authorized_at}\n"
        f"💬 Чатов: {chats_count}"
    )
    return text, account_detail(session_id)


async def _send_new(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    await context.bot.send_message(chat_id=chat.id, text=text, reply_markup=reply_markup)


# --- Public callback handlers (edit current message) ----------------------


@check_blocked
async def accounts_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    text, kb = await _build_accounts_payload(update.effective_user.id)
    try:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    except Exception:
        await _send_new(update, context, text, kb)


@check_blocked
async def account_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        session_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    if update.effective_user is None:
        return
    payload = await _build_account_detail_payload(update.effective_user.id, session_id)
    if payload is None:
        await update.callback_query.edit_message_text("❌ Аккаунт не найден.")
        return
    text, kb = payload
    try:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    except Exception:
        await _send_new(update, context, text, kb)


# --- Send-as-new-message helpers (used by cancel) -------------------------


async def send_accounts_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    text, kb = await _build_accounts_payload(update.effective_user.id)
    await _send_new(update, context, text, kb)


async def send_account_detail_screen(
    update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: int
) -> None:
    if update.effective_user is None:
        return
    payload = await _build_account_detail_payload(update.effective_user.id, session_id)
    if payload is None:
        await _send_new(update, context, "❌ Аккаунт не найден.", None)
        return
    text, kb = payload
    await _send_new(update, context, text, kb)


# --- Revoke ---------------------------------------------------------------


@check_blocked
async def account_revoke_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        session_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    await update.callback_query.edit_message_text(
        "🗑 Удалить этот аккаунт? Привязанные чаты потеряют подключение.",
        reply_markup=account_revoke_confirm(session_id),
    )


@check_blocked
async def account_revoke_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        session_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    async with get_session() as session:
        row = await crud.get_session_by_id(session, session_id)
        if row is None or update.effective_user is None or row.user_id != update.effective_user.id:
            await update.callback_query.edit_message_text("❌ Аккаунт не найден.")
            return

    if userbot.manager is not None:
        try:
            await userbot.manager.revoke(session_id)
        except Exception:
            logger.exception("revoke failed")

    await update.callback_query.edit_message_text("✅ Аккаунт удалён.")


def build_handlers() -> list:
    return [
        CallbackQueryHandler(accounts_show, pattern=rf"^{CB_ACCOUNTS}$"),
        CallbackQueryHandler(account_open, pattern=rf"^{CB_ACCOUNT_OPEN_PREFIX}:\d+$"),
        CallbackQueryHandler(account_revoke_ask, pattern=rf"^{CB_ACCOUNT_REVOKE}:\d+$"),
        CallbackQueryHandler(account_revoke_apply, pattern=rf"^{CB_ACCOUNT_REVOKE_CONFIRM}:\d+$"),
    ]
