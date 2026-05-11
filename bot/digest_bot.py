import logging
import re
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
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import Config
from bot.digest_store import cleanup_old_digests, search_digests
from bot.sender import sanitize_error
from bot.state import BotState

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

CB_BACK = "back"
SEARCH_WAITING = 1
MAX_TG_MSG = 4000
MAX_KEYWORD_LEN = 100
MAX_DIGEST_HOURS = 168

PERIOD_RE = re.compile(r"^(\d+)([hdчд])?$", re.IGNORECASE)


def parse_period(s: str) -> int | None:
    m = PERIOD_RE.match(s.strip().lower())
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2) or "h"
    if num < 1:
        return None
    if unit in ("h", "ч"):
        return num if num <= MAX_DIGEST_HOURS else None
    if unit in ("d", "д"):
        hours = num * 24
        return hours if hours <= MAX_DIGEST_HOURS else None
    return None

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
        ["📅 За неделю", "🔎 Поиск"],
        ["📊 Статус", "⚡ Алерты"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def _split_for_telegram(text: str) -> list[str]:
    if len(text) <= MAX_TG_MSG:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_TG_MSG:
            chunks.append(text)
            break
        split_pos = text.rfind("\n", 0, MAX_TG_MSG)
        if split_pos == -1:
            split_pos = MAX_TG_MSG
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


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
            await update.message.reply_text(f"❌ Ошибка: {sanitize_error(e)}")

    async def weekly_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        await update.message.reply_text("⏳ Генерирую еженедельный дайджест за 7 дней...")

        try:
            count = await run_digest_callback(lookback_hours=168, weekly=True)
            now = datetime.now(MSK).strftime("%H:%M")
            await update.message.reply_text(f"✅ Еженедельный дайджест отправлен • {count} сообщений • {now} МСК")
        except Exception as e:
            logger.exception("Weekly digest button failed")
            await update.message.reply_text(f"❌ Ошибка: {sanitize_error(e)}")

    async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        await update.message.reply_text("🔎 Введите слово для поиска по дайджестам:")
        return SEARCH_WAITING

    async def search_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.effective_user.id != config.admin_user_id:
            return ConversationHandler.END

        keyword = update.message.text.strip()
        if not keyword:
            await update.message.reply_text("❌ Пустой запрос", reply_markup=REPLY_KEYBOARD)
            return ConversationHandler.END

        if len(keyword) > MAX_KEYWORD_LEN:
            keyword = keyword[:MAX_KEYWORD_LEN]

        try:
            results = search_digests(config.data_dir, keyword)
        except Exception as e:
            logger.exception("Search failed")
            await update.message.reply_text(f"❌ Ошибка поиска: {sanitize_error(e)}")
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("← Назад", callback_data=CB_BACK)],
        ])

        if not results:
            await update.message.reply_text(
                f"❌ Ничего не найдено по запросу «{keyword}»",
                reply_markup=keyboard,
            )
            return ConversationHandler.END

        lines = [f'🔎 Результаты по запросу: «{keyword}»\n']
        for r in results:
            lines.append(f"📅 {r['date_formatted']} ({r['period']}):")
            for line in r["lines"]:
                lines.append(f"  {line}")
            lines.append("")

        full_text = "\n".join(lines)
        chunks = _split_for_telegram(full_text)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            await update.message.reply_text(
                chunk,
                reply_markup=keyboard if is_last else None,
            )
        return ConversationHandler.END

    async def search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text("📋 Управление • Дайджест Bedolaga", reply_markup=REPLY_KEYBOARD)
        return ConversationHandler.END

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return
        text = (
            "📋 Команды бота\n\n"
            "/start или /menu — открыть меню\n"
            "/help — справка\n"
            "/cancel — выйти из поиска\n"
            "/digest <period> — дайджест за период (6h, 1d, 48 и т.п.)\n"
            "/cleanup [days] — удалить дайджесты старше N дней (по умолчанию 90)\n\n"
            "Кнопки:\n"
            "⏱ — дайджест за период (1/5/12/24 ч)\n"
            "📅 За неделю — еженедельный дайджест\n"
            "🔎 Поиск — поиск по архиву\n"
            "📊 Статус — состояние системы\n"
            "⚡ Алерты — переключение алертов"
        )
        await update.message.reply_text(text, reply_markup=REPLY_KEYBOARD)

    async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        if not context.args:
            await update.message.reply_text(
                "Использование: /digest <период>\n"
                "Примеры: /digest 6h, /digest 1d, /digest 48\n"
                f"Диапазон: 1ч–{MAX_DIGEST_HOURS}ч (7 дней)"
            )
            return

        hours = parse_period(context.args[0])
        if hours is None:
            await update.message.reply_text(
                f"❌ Неверный формат. Примеры: 6h, 1d, 48. Максимум — {MAX_DIGEST_HOURS}ч."
            )
            return

        weekly = hours >= MAX_DIGEST_HOURS
        await update.message.reply_text(f"⏳ Генерирую дайджест за последние {hours}ч...")
        try:
            count = await run_digest_callback(lookback_hours=hours, weekly=weekly)
            now = datetime.now(MSK).strftime("%H:%M")
            await update.message.reply_text(f"✅ Дайджест отправлен • {count} сообщений • {now} МСК")
        except Exception as e:
            logger.exception("Custom digest command failed")
            await update.message.reply_text(f"❌ Ошибка: {sanitize_error(e)}")

    async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id != config.admin_user_id:
            await update.message.reply_text("⛔ Доступ запрещён", reply_markup=ReplyKeyboardRemove())
            return

        days = 90
        if context.args:
            try:
                days = int(context.args[0])
                if days < 1:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Укажите число дней (например: /cleanup 30)")
                return

        try:
            removed = cleanup_old_digests(config.data_dir, days=days)
            await update.message.reply_text(
                f"🧹 Удалено старых дайджестов (>{days} дней): {removed}"
            )
        except Exception as e:
            logger.exception("Cleanup command failed")
            await update.message.reply_text(f"❌ Ошибка очистки: {sanitize_error(e)}")

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

    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex("^🔎 Поиск$"), search_start)],
        states={
            SEARCH_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query)],
        },
        fallbacks=[CommandHandler("cancel", search_cancel)],
    )

    app.add_handler(CommandHandler(["start", "menu"], start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("cleanup", cleanup_command))
    app.add_handler(search_conv)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^⏱"), period_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📅 За неделю$"), weekly_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📊 Статус$"), status_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^⚡ Алерты$"), alerts_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    return app
