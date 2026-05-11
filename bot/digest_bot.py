import logging
from datetime import datetime, timedelta, timezone

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import Config
from bot.state import BotState

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

CB_BACK = "back"

PERIOD_BUTTONS = {
    "⏱ 1 час": 1,
    "⏱ 5 часов": 5,
    "⏱ 12 часов": 12,
    "⏱ 24 часа": 24,
}

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["⏱ 1 час", "⏱ 5 часов"],
        ["⏱ 12 часов", "⏱ 24 часа"],
        ["📊 Статус", "⚡ Алерты"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def build_bot_app(config: Config, state: BotState, run_digest_callback) -> Application:
    app = ApplicationBuilder().token(config.bot_token).build()

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return
        await update.message.reply_text(
            "📋 Управление • Дайджест Bedolaga",
            reply_markup=REPLY_KEYBOARD,
        )

    async def period_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        hours = PERIOD_BUTTONS[update.message.text]
        label = update.message.text
        await update.message.reply_text(f"⏳ Генерирую дайджест за последние {hours} ч...")

        try:
            count = await run_digest_callback(lookback_hours=hours)
            now = datetime.now(MSK).strftime("%H:%M")
            await update.message.reply_text(f"✅ Дайджест отправлен • {count} сообщений • {now} МСК")
        except Exception as e:
            logger.exception(f"Digest via '{label}' button failed")
            await update.message.reply_text(f"❌ Ошибка: {e}")

    async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        lines = ["📊 Статус\n"]
        lines.append(f"🕐 Последний запуск: {state.last_run or 'нет'} МСК")
        lines.append(f"💬 Сообщений в последнем дайджесте: {state.last_count}")
        lines.append(f"⏭ Следующий по расписанию: {state.next_run or 'нет'} МСК")
        lines.append(f"⚡ Алерты: {'ВКЛ' if state.alerts_enabled else 'ВЫКЛ'}")

        try:
            from bot.main import userbot_client
            connected = userbot_client is not None and userbot_client.is_connected()
            lines.append(f"📡 Userbot: {'подключён' if connected else 'ошибка'}")
        except Exception:
            lines.append("📡 Userbot: неизвестно")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("← Назад", callback_data=CB_BACK)],
        ])
        await update.message.reply_text("\n".join(lines), reply_markup=keyboard)

    async def alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        new_state = state.toggle_alerts()
        label = "ВКЛ" if new_state else "ВЫКЛ"
        await update.message.reply_text(f"⚡ Алерты: {label}")

    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if update.effective_user.id != config.admin_user_id:
            await query.answer("⛔ Доступ запрещён", show_alert=True)
            return

        await query.answer()
        if query.data == CB_BACK:
            await query.edit_message_text("📋 Управление • Дайджест Bedolaga")

    app.add_handler(CommandHandler(["start", "menu"], start_command))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^⏱"), period_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📊 Статус$"), status_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^⚡ Алерты$"), alerts_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    return app
