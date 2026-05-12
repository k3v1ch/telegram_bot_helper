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

from bot import scheduler as scheduler_mod
from bot.db import crud
from bot.db.database import get_session
from bot.handlers.start import check_blocked
from bot.keyboards import (
    CB_CANCEL,
    back_to_chat,
    cancel_inline,
    chat_delete_confirm,
    chat_menu,
    chat_settings,
    chats_list,
    hours_choice,
    prompt_choice,
)
from bot.states import (
    ADD_CHAT_DEST,
    ADD_CHAT_HOURS,
    ADD_CHAT_NAME,
    ADD_CHAT_PROMPT,
    ADD_CHAT_SOURCE,
    ADD_CHAT_TIME,
    EDIT_HOURS,
    EDIT_PROMPT,
    EDIT_SOURCE_DEST,
    EDIT_TIME,
)

logger = logging.getLogger(__name__)

SRC_DEST_RE = re.compile(r"^-?\d+:\d+$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


# ---------- Add chat conversation ----------


@check_blocked
async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📝 Введите название чата:",
            reply_markup=cancel_inline(),
        )
    elif update.message:
        await update.message.reply_text(
            "📝 Введите название чата:",
            reply_markup=cancel_inline(),
        )
    context.user_data["add_chat"] = {}
    return ADD_CHAT_NAME


@check_blocked
async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADD_CHAT_NAME
    name = (update.message.text or "").strip()
    if not name or len(name) > 255:
        await update.message.reply_text(
            "❌ Название должно быть от 1 до 255 символов. Введите ещё раз:",
            reply_markup=cancel_inline(),
        )
        return ADD_CHAT_NAME
    context.user_data["add_chat"]["name"] = name
    await update.message.reply_text(
        "📥 Введите источник в формате chat_id:topic_id\nНапример: -1003332852289:155",
        reply_markup=cancel_inline(),
    )
    return ADD_CHAT_SOURCE


@check_blocked
async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADD_CHAT_SOURCE
    src = (update.message.text or "").strip()
    if not SRC_DEST_RE.match(src):
        await update.message.reply_text(
            "❌ Формат: chat_id:topic_id. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return ADD_CHAT_SOURCE
    context.user_data["add_chat"]["source"] = src
    await update.message.reply_text(
        "📤 Введите назначение в формате chat_id:topic_id:",
        reply_markup=cancel_inline(),
    )
    return ADD_CHAT_DEST


@check_blocked
async def add_dest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADD_CHAT_DEST
    dst = (update.message.text or "").strip()
    if not SRC_DEST_RE.match(dst):
        await update.message.reply_text(
            "❌ Формат: chat_id:topic_id. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return ADD_CHAT_DEST
    context.user_data["add_chat"]["dest"] = dst
    await update.message.reply_text(
        "🕐 Введите время отправки в формате HH:MM (по МСК), например 09:00:",
        reply_markup=cancel_inline(),
    )
    return ADD_CHAT_TIME


@check_blocked
async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADD_CHAT_TIME
    t = (update.message.text or "").strip()
    if not TIME_RE.match(t):
        await update.message.reply_text(
            "❌ Формат HH:MM. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return ADD_CHAT_TIME
    context.user_data["add_chat"]["schedule_time"] = t
    await update.message.reply_text(
        "📏 Выберите период анализа:",
        reply_markup=hours_choice(),
    )
    return ADD_CHAT_HOURS


@check_blocked
async def add_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ADD_CHAT_HOURS
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    if not data.startswith("add_hours:"):
        return ADD_CHAT_HOURS
    try:
        hours = int(data.split(":", 1)[1])
    except ValueError:
        return ADD_CHAT_HOURS
    context.user_data["add_chat"]["lookback_hours"] = hours
    await update.callback_query.edit_message_text(
        "💬 Хотите задать кастомный промпт для AI или использовать стандартный?",
        reply_markup=prompt_choice(),
    )
    return ADD_CHAT_PROMPT


@check_blocked
async def add_prompt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ADD_CHAT_PROMPT
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    if data == "add_prompt:default":
        context.user_data["add_chat"]["custom_prompt"] = None
        return await _finalize_add(update, context)
    if data == "add_prompt:custom":
        await update.callback_query.edit_message_text(
            "📝 Введите свой промпт (текст инструкции для AI):",
            reply_markup=cancel_inline(),
        )
        return ADD_CHAT_PROMPT
    return ADD_CHAT_PROMPT


@check_blocked
async def add_prompt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADD_CHAT_PROMPT
    prompt = (update.message.text or "").strip()
    context.user_data["add_chat"]["custom_prompt"] = prompt or None
    return await _finalize_add(update, context)


async def _finalize_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None:
        return ConversationHandler.END

    data = context.user_data.get("add_chat") or {}
    user_id = update.effective_user.id

    async with get_session() as session:
        chat = await crud.create_chat(
            session,
            user_id=user_id,
            name=data.get("name", "chat"),
            source=data.get("source", ""),
            dest=data.get("dest", ""),
            schedule_time=data.get("schedule_time", "05:00"),
            lookback_hours=data.get("lookback_hours", 24),
        )
        if data.get("custom_prompt"):
            await crud.update_chat(session, chat.id, custom_prompt=data["custom_prompt"])
            chat.custom_prompt = data["custom_prompt"]

    if scheduler_mod.manager is not None:
        try:
            scheduler_mod.manager.add_chat_job(chat)
        except Exception:
            logger.exception("Failed to schedule new chat")

    text = f"✅ Чат добавлен! Первый дайджест в {chat.schedule_time} МСК"
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text)
        except Exception:
            await update.callback_query.message.reply_text(text)
    elif update.message:
        await update.message.reply_text(text)

    context.user_data.pop("add_chat", None)
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text("❌ Добавление отменено.")
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text("❌ Добавление отменено.")
    context.user_data.pop("add_chat", None)
    return ConversationHandler.END


# ---------- Chat list / menu / settings ----------


@check_blocked
async def chats_list_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    async with get_session() as session:
        chats = await crud.get_user_chats(session, update.effective_user.id)
    await update.callback_query.edit_message_text(
        "Ваши чаты:" if chats else "У вас пока нет чатов. Нажмите ➕ чтобы добавить.",
        reply_markup=chats_list(chats),
    )


@check_blocked
async def chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
    if chat is None or chat.user_id != update.effective_user.id:
        await update.callback_query.edit_message_text("❌ Чат не найден.")
        return
    await update.callback_query.edit_message_text(
        _chat_header(chat),
        reply_markup=chat_menu(chat),
    )


def _chat_header(chat) -> str:
    status = "✅ Активен" if chat.is_active else "⏸ На паузе"
    alerts = "ВКЛ" if chat.alerts_enabled else "ВЫКЛ"
    return (
        f"📋 {chat.name}\n"
        f"📥 Источник: {chat.source}\n"
        f"📤 Назначение: {chat.dest}\n"
        f"🕐 Расписание: {chat.schedule_time} МСК\n"
        f"📏 Период: {chat.lookback_hours}ч\n"
        f"⚡ Алерты: {alerts}\n"
        f"Статус: {status}"
    )


@check_blocked
async def chat_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
        if chat is None or chat.user_id != update.effective_user.id:
            await update.callback_query.edit_message_text("❌ Чат не найден.")
            return
        new_state = not chat.is_active
        await crud.update_chat(session, chat_id, is_active=new_state)
        chat.is_active = new_state

    if scheduler_mod.manager is not None:
        if new_state:
            scheduler_mod.manager.resume_chat_job(chat_id)
        else:
            scheduler_mod.manager.pause_chat_job(chat_id)

    await update.callback_query.edit_message_text(
        _chat_header(chat),
        reply_markup=chat_menu(chat),
    )


@check_blocked
async def chat_alerts_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
        if chat is None or chat.user_id != update.effective_user.id:
            await update.callback_query.edit_message_text("❌ Чат не найден.")
            return
        new_state = not chat.alerts_enabled
        await crud.update_chat(session, chat_id, alerts_enabled=new_state)
        chat.alerts_enabled = new_state

    await update.callback_query.edit_message_text(
        _chat_header(chat),
        reply_markup=chat_menu(chat),
    )


@check_blocked
async def chat_settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    await update.callback_query.edit_message_text(
        "⚙️ Настройки чата:",
        reply_markup=chat_settings(chat_id),
    )


@check_blocked
async def chat_delete_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    await update.callback_query.edit_message_text(
        "🗑 Удалить чат? Это действие необратимо.",
        reply_markup=chat_delete_confirm(chat_id),
    )


@check_blocked
async def chat_delete_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    chat_id = int(update.callback_query.data.split(":")[1])
    async with get_session() as session:
        chat = await crud.get_chat(session, chat_id)
        if chat is None or chat.user_id != update.effective_user.id:
            await update.callback_query.edit_message_text("❌ Чат не найден.")
            return
        await crud.delete_chat(session, chat_id)

    if scheduler_mod.manager is not None:
        scheduler_mod.manager.remove_chat_job(chat_id)

    await update.callback_query.edit_message_text("🗑 Чат удалён.")


# ---------- Edit conversations ----------


def _parse_chat_id(data: str) -> int:
    return int(data.split(":")[1])


@check_blocked
async def edit_prompt_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    chat_id = _parse_chat_id(update.callback_query.data)
    context.user_data["edit_chat_id"] = chat_id
    await update.callback_query.edit_message_text(
        "✏️ Введите новый промпт:",
        reply_markup=cancel_inline(),
    )
    return EDIT_PROMPT


@check_blocked
async def edit_prompt_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return EDIT_PROMPT
    chat_id = context.user_data.get("edit_chat_id")
    if chat_id is None:
        return ConversationHandler.END
    prompt = (update.message.text or "").strip()
    async with get_session() as session:
        await crud.update_chat(session, chat_id, custom_prompt=prompt or None)
    await update.message.reply_text("✅ Промпт обновлён.", reply_markup=back_to_chat(chat_id))
    context.user_data.pop("edit_chat_id", None)
    return ConversationHandler.END


@check_blocked
async def edit_time_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    chat_id = _parse_chat_id(update.callback_query.data)
    context.user_data["edit_chat_id"] = chat_id
    await update.callback_query.edit_message_text(
        "🕐 Введите новое время в формате HH:MM:",
        reply_markup=cancel_inline(),
    )
    return EDIT_TIME


@check_blocked
async def edit_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return EDIT_TIME
    chat_id = context.user_data.get("edit_chat_id")
    if chat_id is None:
        return ConversationHandler.END
    t = (update.message.text or "").strip()
    if not TIME_RE.match(t):
        await update.message.reply_text(
            "❌ Формат HH:MM. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return EDIT_TIME
    async with get_session() as session:
        await crud.update_chat(session, chat_id, schedule_time=t)
        chat = await crud.get_chat(session, chat_id)
    if scheduler_mod.manager is not None and chat is not None:
        scheduler_mod.manager.add_chat_job(chat)
    await update.message.reply_text("✅ Расписание обновлено.", reply_markup=back_to_chat(chat_id))
    context.user_data.pop("edit_chat_id", None)
    return ConversationHandler.END


@check_blocked
async def edit_hours_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    chat_id = _parse_chat_id(update.callback_query.data)
    context.user_data["edit_chat_id"] = chat_id
    await update.callback_query.edit_message_text(
        "📏 Введите период в часах (1–168):",
        reply_markup=cancel_inline(),
    )
    return EDIT_HOURS


@check_blocked
async def edit_hours_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return EDIT_HOURS
    chat_id = context.user_data.get("edit_chat_id")
    if chat_id is None:
        return ConversationHandler.END
    raw = (update.message.text or "").strip()
    try:
        hours = int(raw)
    except ValueError:
        await update.message.reply_text(
            "❌ Введите число от 1 до 168:",
            reply_markup=cancel_inline(),
        )
        return EDIT_HOURS
    if not 1 <= hours <= 168:
        await update.message.reply_text(
            "❌ Введите число от 1 до 168:",
            reply_markup=cancel_inline(),
        )
        return EDIT_HOURS
    async with get_session() as session:
        await crud.update_chat(session, chat_id, lookback_hours=hours)
    await update.message.reply_text("✅ Период обновлён.", reply_markup=back_to_chat(chat_id))
    context.user_data.pop("edit_chat_id", None)
    return ConversationHandler.END


@check_blocked
async def edit_src_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    chat_id = _parse_chat_id(update.callback_query.data)
    context.user_data["edit_chat_id"] = chat_id
    context.user_data["edit_src_step"] = "source"
    await update.callback_query.edit_message_text(
        "📥 Введите новый источник в формате chat_id:topic_id:",
        reply_markup=cancel_inline(),
    )
    return EDIT_SOURCE_DEST


@check_blocked
async def edit_src_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return EDIT_SOURCE_DEST
    chat_id = context.user_data.get("edit_chat_id")
    step = context.user_data.get("edit_src_step")
    if chat_id is None or step is None:
        return ConversationHandler.END
    val = (update.message.text or "").strip()
    if not SRC_DEST_RE.match(val):
        await update.message.reply_text(
            "❌ Формат chat_id:topic_id. Попробуйте ещё раз:",
            reply_markup=cancel_inline(),
        )
        return EDIT_SOURCE_DEST
    if step == "source":
        context.user_data["edit_src_value"] = val
        context.user_data["edit_src_step"] = "dest"
        await update.message.reply_text(
            "📤 Теперь введите новое назначение в формате chat_id:topic_id:",
            reply_markup=cancel_inline(),
        )
        return EDIT_SOURCE_DEST
    source_val = context.user_data.get("edit_src_value", "")
    async with get_session() as session:
        await crud.update_chat(session, chat_id, source=source_val, dest=val)
    await update.message.reply_text(
        "✅ Источник и назначение обновлены.",
        reply_markup=back_to_chat(chat_id),
    )
    context.user_data.pop("edit_chat_id", None)
    context.user_data.pop("edit_src_step", None)
    context.user_data.pop("edit_src_value", None)
    return ConversationHandler.END


async def edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text("❌ Отменено.")
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text("❌ Отменено.")
    for k in ("edit_chat_id", "edit_src_step", "edit_src_value"):
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ---------- Handler factory ----------


def build_add_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_entry, pattern=r"^chat_add$")],
        states={
            ADD_CHAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_CHAT_SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_source)],
            ADD_CHAT_DEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dest)],
            ADD_CHAT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
            ADD_CHAT_HOURS: [CallbackQueryHandler(add_hours, pattern=r"^add_hours:\d+$")],
            ADD_CHAT_PROMPT: [
                CallbackQueryHandler(add_prompt_choice, pattern=r"^add_prompt:(default|custom)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_prompt_text),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(add_cancel, pattern=rf"^{CB_CANCEL}$"),
            CommandHandler("cancel", add_cancel),
        ],
        name="add_chat_conversation",
        persistent=False,
    )


def build_edit_conversations() -> list[ConversationHandler]:
    fallbacks = [
        CallbackQueryHandler(edit_cancel, pattern=rf"^{CB_CANCEL}$"),
        CommandHandler("cancel", edit_cancel),
    ]
    return [
        ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_prompt_entry, pattern=r"^chat_edit_prompt:\d+$")],
            states={EDIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_prompt_save)]},
            fallbacks=fallbacks,
            name="edit_prompt",
            persistent=False,
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_time_entry, pattern=r"^chat_edit_time:\d+$")],
            states={EDIT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_time_save)]},
            fallbacks=fallbacks,
            name="edit_time",
            persistent=False,
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_hours_entry, pattern=r"^chat_edit_hours:\d+$")],
            states={EDIT_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_hours_save)]},
            fallbacks=fallbacks,
            name="edit_hours",
            persistent=False,
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_src_entry, pattern=r"^chat_edit_src:\d+$")],
            states={EDIT_SOURCE_DEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_src_save)]},
            fallbacks=fallbacks,
            name="edit_src",
            persistent=False,
        ),
    ]


def build_handlers() -> list:
    return [
        build_add_conversation(),
        *build_edit_conversations(),
        CallbackQueryHandler(chats_list_cb, pattern=r"^chats_list$"),
        CallbackQueryHandler(chat_open, pattern=r"^chat:\d+$"),
        CallbackQueryHandler(chat_toggle, pattern=r"^chat_toggle:\d+$"),
        CallbackQueryHandler(chat_alerts_toggle, pattern=r"^chat_alerts:\d+$"),
        CallbackQueryHandler(chat_settings_cb, pattern=r"^chat_settings:\d+$"),
        CallbackQueryHandler(chat_delete_ask, pattern=r"^chat_delete:\d+$"),
        CallbackQueryHandler(chat_delete_apply, pattern=r"^chat_delete_confirm:\d+$"),
    ]
