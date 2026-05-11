import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from bot.config import Config

logger = logging.getLogger(__name__)


def start_digest_bot(config: Config, run_digest_callback) -> None:
    app = ApplicationBuilder().token(config.bot_token).build()

    async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if config.admin_id and update.effective_user.id != config.admin_id:
            return

        await update.message.reply_text("⏳ Генерирую дайджест...")
        try:
            await run_digest_callback()
            await update.message.reply_text("✅ Дайджест отправлен")
        except Exception as e:
            logger.exception("Digest via bot command failed")
            await update.message.reply_text(f"❌ Ошибка: {e}")

    app.add_handler(CommandHandler("digest", digest_command))

    asyncio.ensure_future(_run_polling(app))
    logger.info("Telegram bot started, /digest command available")


async def _run_polling(app) -> None:
    try:
        await app.initialize()
        await app.updater.start_polling(drop_pending_updates=True)
        await app.start()
    except Exception:
        logger.exception("Bot polling failed")
