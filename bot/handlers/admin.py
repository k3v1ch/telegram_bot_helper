import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot import scheduler as scheduler_mod
from bot import userbot
from bot.db import crud
from bot.db.database import get_session
from bot.keyboards import (
    admin_menu,
    admin_user_detail,
    admin_users_list,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 10


def _admin_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return int(context.bot_data.get("admin_user_id", 0))


def admin_only(func: Callable):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None or user.id != _admin_id(context):
            if update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


@admin_only
async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("👑 Админ панель", reply_markup=admin_menu())


@admin_only
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        page = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        page = 0

    async with get_session() as session:
        users = await crud.get_all_users(session)
        users_sorted = sorted(users, key=lambda u: u.user_id)
        total_pages = max(1, (len(users_sorted) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        slice_start = page * PAGE_SIZE
        slice_end = slice_start + PAGE_SIZE
        page_users = users_sorted[slice_start:slice_end]

        entries: list[tuple[int, str, int, bool]] = []
        for u in page_users:
            chats = await crud.get_user_chats(session, u.user_id)
            display = u.username or u.first_name or str(u.user_id)
            entries.append((u.user_id, f"{display} | чатов: {len(chats)}", len(chats), u.is_blocked))

    text = f"👥 Пользователи ({len(users_sorted)}):"
    await update.callback_query.edit_message_text(
        text,
        reply_markup=admin_users_list(entries, page, total_pages),
    )


@admin_only
async def admin_user_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        user_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    async with get_session() as session:
        user = await crud.get_user(session, user_id)
        if user is None:
            await update.callback_query.edit_message_text("❌ Пользователь не найден.")
            return
        chats = await crud.get_user_chats(session, user_id)
        session_str = await crud.get_session_str(session, user_id)

    display = user.username or user.first_name or str(user.user_id)
    status = "🚫 Заблокирован" if user.is_blocked else "✅ Активен"
    authorized = "да" if session_str else "нет"
    text = (
        f"👤 {display}\n"
        f"ID: {user.user_id}\n"
        f"Статус: {status}\n"
        f"Авторизован: {authorized}\n"
        f"Чатов: {len(chats)}"
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=admin_user_detail(user_id, user.is_blocked),
    )


@admin_only
async def admin_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        user_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    async with get_session() as session:
        user = await crud.get_user(session, user_id)
        if user is None:
            await update.callback_query.edit_message_text("❌ Пользователь не найден.")
            return
        new_blocked = not user.is_blocked
        await crud.set_blocked(session, user_id, new_blocked)
        chats = await crud.get_user_chats(session, user_id)

    if new_blocked:
        if userbot.manager is not None:
            try:
                await userbot.manager.stop_client(user_id)
            except Exception:
                logger.exception("stop_client failed during block")
        if scheduler_mod.manager is not None:
            scheduler_mod.manager.remove_user_jobs([c.id for c in chats])

    await admin_user_open(update, context)


@admin_only
async def admin_user_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        user_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    async with get_session() as session:
        chats = await crud.get_user_chats(session, user_id)

    if not chats:
        text = "📋 У пользователя нет чатов."
    else:
        lines = [f"📋 Чаты пользователя {user_id}:"]
        for c in chats:
            marker = "✅" if c.is_active else "⏸"
            lines.append(f"{marker} {c.name} • {c.source} → {c.dest} • {c.schedule_time}")
        text = "\n".join(lines)

    user = None
    async with get_session() as session:
        user = await crud.get_user(session, user_id)
    blocked = user.is_blocked if user else False
    await update.callback_query.edit_message_text(
        text,
        reply_markup=admin_user_detail(user_id, blocked),
    )


@admin_only
async def admin_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        user_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    async with get_session() as session:
        chats = await crud.get_user_chats(session, user_id)
        user = await crud.get_user(session, user_id)

    text = (
        f"📊 Статистика пользователя {user_id}\n"
        f"Чатов всего: {len(chats)}\n"
        f"Активных: {sum(1 for c in chats if c.is_active)}\n"
        f"С алертами: {sum(1 for c in chats if c.alerts_enabled)}"
    )
    blocked = user.is_blocked if user else False
    await update.callback_query.edit_message_text(
        text,
        reply_markup=admin_user_detail(user_id, blocked),
    )


@admin_only
async def admin_user_reconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.callback_query.data is None:
        return
    await update.callback_query.answer()
    try:
        user_id = int(update.callback_query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    ok = False
    if userbot.manager is not None:
        try:
            await userbot.manager.stop_client(user_id)
            ok = await userbot.manager.start_client(user_id)
        except Exception:
            logger.exception("admin reconnect failed")

    text = "✅ Сессия переподключена." if ok else "❌ Не удалось переподключить сессию."
    async with get_session() as session:
        user = await crud.get_user(session, user_id)
    blocked = user.is_blocked if user else False
    await update.callback_query.edit_message_text(
        text,
        reply_markup=admin_user_detail(user_id, blocked),
    )


@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    async with get_session() as session:
        users = await crud.get_all_users(session)
        active_chats = await crud.get_all_active_chats(session)
        all_chats: list = []
        for u in users:
            all_chats.extend(await crud.get_user_chats(session, u.user_id))

    text = (
        "📊 Глобальная статистика\n"
        f"Пользователей: {len(users)}\n"
        f"Заблокированных: {sum(1 for u in users if u.is_blocked)}\n"
        f"Чатов всего: {len(all_chats)}\n"
        f"Активных чатов: {len(active_chats)}"
    )
    await update.callback_query.edit_message_text(text, reply_markup=admin_menu())


@admin_only
async def admin_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔄 Перезапускаю userbot-сессии…")

    if userbot.manager is not None:
        try:
            await userbot.manager.stop_all()
            await userbot.manager.start_all()
        except Exception:
            logger.exception("admin_restart failed")
            await update.callback_query.edit_message_text(
                "❌ Ошибка при перезапуске.",
                reply_markup=admin_menu(),
            )
            return

    await update.callback_query.edit_message_text(
        "✅ Userbot-сессии перезапущены.",
        reply_markup=admin_menu(),
    )


def build_handlers() -> list:
    return [
        CallbackQueryHandler(admin_back, pattern=r"^admin_back$"),
        CallbackQueryHandler(admin_users, pattern=r"^admin_users:\d+$"),
        CallbackQueryHandler(admin_user_open, pattern=r"^admin_user:\d+$"),
        CallbackQueryHandler(admin_block, pattern=r"^admin_block:\d+$"),
        CallbackQueryHandler(admin_user_chats, pattern=r"^admin_user_chats:\d+$"),
        CallbackQueryHandler(admin_user_stats, pattern=r"^admin_user_stats:\d+$"),
        CallbackQueryHandler(admin_user_reconnect, pattern=r"^admin_user_reconnect:\d+$"),
        CallbackQueryHandler(admin_stats, pattern=r"^admin_stats$"),
        CallbackQueryHandler(admin_restart, pattern=r"^admin_restart$"),
    ]
