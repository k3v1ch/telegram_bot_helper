import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import Config
from bot.state import BotState

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

CB_RUN_DIGEST = "run_digest"
CB_STATUS = "status"
CB_TOGGLE_ALERTS = "toggle_alerts"
CB_BACK = "back"


def _main_keyboard(state: BotState) -> InlineKeyboardMarkup:
    alerts_label = "⚡ Алерты: ВКЛ" if state.alerts_enabled else "⚡ Алерты: ВЫКЛ"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Запустить дайджест", callback_data=CB_RUN_DIGEST)],
        [
            InlineKeyboardButton("📊 Статус", callback_data=CB_STATUS),
            InlineKeyboardButton(alerts_label, callback_data=CB_TOGGLE_ALERTS),
        ],
    ])


MENU_TEXT = "📋 Управление • Дайджест Bedolaga"


def build_bot_app(config: Config, state: BotState, run_digest_callback) -> Application:
    app = ApplicationBuilder().token(config.bot_token).build()

    def admin_only(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id if update.effective_user else None
            if user_id != config.admin_user_id:
                if update.callback_query:
                    await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
                elif update.message:
                    await update.message.reply_text("⛔ Доступ запрещён")
                return
            return await func(update, context)
        return wrapper

    @admin_only
    async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(MENU_TEXT, reply_markup=_main_keyboard(state))

    @admin_only
    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        if query.data == CB_RUN_DIGEST:
            await query.edit_message_text("⏳ Генерирую дайджест...")
            try:
                count = await run_digest_callback()
                now = datetime.now(MSK).strftime("%H:%M")
                await query.edit_message_text(
                    f"✅ Дайджест отправлен • {count} сообщений • {now} МСК",
                )
            except Exception as e:
                logger.exception("Digest via bot button failed")
                await query.edit_message_text(f"❌ Ошибка: {e}")
            return

        if query.data == CB_STATUS:
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
            await query.edit_message_text("\n".join(lines), reply_markup=keyboard)
            return

        if query.data == CB_TOGGLE_ALERTS:
            state.toggle_alerts()
            await query.edit_message_text(MENU_TEXT, reply_markup=_main_keyboard(state))
            return

        if query.data == CB_BACK:
            await query.edit_message_text(MENU_TEXT, reply_markup=_main_keyboard(state))
            return

    app.add_handler(CommandHandler(["start", "menu"], menu_command))
    app.add_handler(CallbackQueryHandler(callback_handler))

    return app
