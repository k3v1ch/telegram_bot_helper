import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from bot import scheduler as scheduler_mod
from bot import userbot
from bot.config import Config
from bot.db.database import get_session, init_db
from bot.handlers import admin as admin_handlers
from bot.handlers import auth as auth_handlers
from bot.handlers import chats as chats_handlers
from bot.handlers import digest as digest_handlers
from bot.handlers import search as search_handlers
from bot.handlers import start as start_handlers
from bot.scheduler import ScheduleManager
from bot.userbot.manager import UserbotManager

logger = logging.getLogger("bot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Handler error", exc_info=context.error)
    admin_id = int(context.bot_data.get("admin_user_id", 0))
    if not admin_id:
        return
    try:
        msg = f"⚠️ Ошибка в обработчике:\n{context.error!r}"
        await context.bot.send_message(chat_id=admin_id, text=msg[:3500])
    except Exception:
        logger.exception("Failed to notify admin of error")


def _register_handlers(app: Application) -> None:
    start_cmd, menu_cmd, main_router = start_handlers.build_handlers()
    app.add_handler(start_cmd)
    app.add_handler(menu_cmd)

    for h in auth_handlers.build_handlers():
        app.add_handler(h)
    for h in chats_handlers.build_handlers():
        app.add_handler(h)
    for h in digest_handlers.build_handlers():
        app.add_handler(h)
    for h in search_handlers.build_handlers():
        app.add_handler(h)
    for h in admin_handlers.build_handlers():
        app.add_handler(h)

    # Reply-keyboard router registered last so ConversationHandler text
    # states (auth/add/edit/search) receive messages first.
    app.add_handler(main_router)

    app.add_error_handler(_error_handler)


async def main() -> None:
    setup_logging()
    config = Config.from_env()

    await init_db()
    logger.info("Database initialized")

    userbot.manager = UserbotManager(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        db_session_factory=get_session,
    )
    await userbot.manager.start_all()

    scheduler_mod.manager = ScheduleManager()
    scheduler_mod.manager.start()
    logger.info("Scheduler started")

    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["admin_user_id"] = config.admin_user_id

    _register_handlers(application)

    logger.info("Starting Telegram bot polling")
    async with application:
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        try:
            stop_event = asyncio.Event()
            await stop_event.wait()
        finally:
            await application.updater.stop()
            await application.stop()
            if userbot.manager is not None:
                await userbot.manager.stop_all()
            if scheduler_mod.manager is not None:
                scheduler_mod.manager.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
