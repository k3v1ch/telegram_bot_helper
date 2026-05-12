"""Centralized cancel-return logic for ConversationHandlers.

Each conversation entry point calls :func:`set_cancel_return` to record where
the user came from. The conversation's fallback then uses :func:`cancel_dispatch`
instead of a flat "❌ Отменено" message — the user is silently routed back to
the screen where the action was initiated.

Targets:
    "main_menu"      — main menu (target_id ignored)
    "accounts_list"  — accounts list (target_id ignored)
    "account_detail" — specific account (target_id = session_id)
    "chats_list"     — chats list (target_id ignored)
    "chat_detail"    — specific chat (target_id = chat_id)
    "chat_settings"  — chat settings (target_id = chat_id)
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

CancelTarget = tuple[str, int | None]


def set_cancel_return(
    context: ContextTypes.DEFAULT_TYPE,
    target: str,
    target_id: int | None = None,
) -> None:
    context.user_data["cancel_return"] = (target, target_id)


def _consume_cancel_return(context: ContextTypes.DEFAULT_TYPE) -> CancelTarget:
    return context.user_data.pop("cancel_return", ("main_menu", None))


async def cancel_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Universal cancel handler — silently returns user to their previous screen."""
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass

    # Clean up any flow-specific state we know about.
    for key in (
        "auth",
        "add_chat",
        "edit_chat_id",
        "edit_src_step",
        "edit_src_value",
        "rename_session_id",
        "search_chat_id",
    ):
        context.user_data.pop(key, None)

    target, target_id = _consume_cancel_return(context)
    try:
        await _route(update, context, target, target_id)
    except Exception:
        logger.exception(f"cancel_dispatch failed (target={target}, id={target_id})")
        try:
            from bot.handlers.start import send_main_menu

            await send_main_menu(update, context)
        except Exception:
            logger.exception("Even fallback main-menu send failed")

    return ConversationHandler.END


async def _route(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target: str,
    target_id: int | None,
) -> None:
    if target == "accounts_list":
        from bot.handlers.accounts import send_accounts_screen

        await send_accounts_screen(update, context)
    elif target == "account_detail" and target_id is not None:
        from bot.handlers.accounts import send_account_detail_screen

        await send_account_detail_screen(update, context, target_id)
    elif target == "chats_list":
        from bot.handlers.chats import send_chats_screen

        await send_chats_screen(update, context)
    elif target == "chat_detail" and target_id is not None:
        from bot.handlers.chats import send_chat_detail_screen

        await send_chat_detail_screen(update, context, target_id)
    elif target == "chat_settings" and target_id is not None:
        from bot.handlers.chats import send_chat_settings_screen

        await send_chat_settings_screen(update, context, target_id)
    else:
        from bot.handlers.start import send_main_menu

        await send_main_menu(update, context)
