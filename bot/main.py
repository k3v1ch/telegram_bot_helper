import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from bot import analyzer, scheduler as scheduler_mod, userbot
from bot.config import Config
from bot.db import crud
from bot.db.database import get_session, init_db
from bot.handlers import admin as admin_handlers
from bot.handlers import auth as auth_handlers
from bot.handlers import chats as chats_handlers
from bot.handlers import digest as digest_handlers
from bot.handlers import search as search_handlers
from bot.handlers import start as start_handlers
from bot.handlers import stats as stats_handlers
from bot.scheduler import DigestScheduler, parse_chat_topic
from bot.userbot.alerter import register_alert
from bot.userbot.manager import UserbotManager

logger = logging.getLogger("bot")

USER_ERROR_TEXT = "❌ Произошла ошибка. Попробуйте позже."


def setup_logging() -> None:
    log_dir = Path("/app/logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_dir = None

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = []
    if log_dir is not None:
        try:
            file_handler = RotatingFileHandler(
                log_dir / "digest.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except Exception:
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    for h in handlers:
        root_logger.addHandler(h)


async def _notify_user(update: object) -> None:
    if not isinstance(update, Update):
        return
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(USER_ERROR_TEXT, show_alert=True)
            return
        if update.effective_message is not None:
            await update.effective_message.reply_text(USER_ERROR_TEXT)
    except Exception:
        logger.exception("Failed to notify user about error")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Handler error", exc_info=context.error)

    await _notify_user(update)

    admin_id = int(context.bot_data.get("admin_user_id", 0))
    if not admin_id:
        return
    try:
        msg = f"⚠️ Ошибка в обработчике:\n{context.error!r}"
        await context.bot.send_message(chat_id=admin_id, text=msg[:3500])
    except Exception:
        logger.exception("Failed to notify admin of error")


def _register_handlers(app: Application) -> None:
    from bot.handlers import accounts as accounts_handlers

    start_cmd, menu_cmd, back_cb, gated_callbacks = start_handlers.build_handlers()
    app.add_handler(start_cmd)
    app.add_handler(menu_cmd)
    app.add_handler(back_cb)
    for h in gated_callbacks:
        app.add_handler(h)

    for h in auth_handlers.build_handlers():
        app.add_handler(h)
    for h in accounts_handlers.build_handlers():
        app.add_handler(h)
    for h in chats_handlers.build_handlers():
        app.add_handler(h)
    for h in digest_handlers.build_handlers():
        app.add_handler(h)
    for h in search_handlers.build_handlers():
        app.add_handler(h)
    for h in admin_handlers.build_handlers():
        app.add_handler(h)
    for h in stats_handlers.build_handlers():
        app.add_handler(h)

    app.add_error_handler(_error_handler)


async def _register_alerters(bot) -> None:
    if userbot.manager is None:
        return
    async with get_session() as session:
        chats = await crud.get_all_active_chats(session)
    registered = 0
    for chat in chats:
        if not chat.alerts_enabled or chat.session_id is None:
            continue
        try:
            if not await userbot.manager.is_connected(chat.session_id):
                continue
            client = await userbot.manager.get_client(chat.session_id)
            dest_chat_id, dest_topic_id = parse_chat_topic(chat.dest)
            register_alert(client, chat, bot, dest_chat_id, dest_topic_id)
            registered += 1
        except Exception as e:
            logger.warning(f"Could not register alerter for chat {chat.id}: {e}")
    logger.info(f"Registered {registered} alerters")


async def _migrate_legacy_env(admin_user_id: int) -> None:
    """One-shot migration from the legacy single-user env-driven config."""
    old_phone = os.getenv("TELEGRAM_PHONE")
    old_source = os.getenv("SOURCE")
    old_dest = os.getenv("DEST")
    old_lookback = os.getenv("LOOKBACK_HOURS")
    old_time = os.getenv("DIGEST_TIME")

    if not any([old_phone, old_source, old_dest, old_lookback, old_time]):
        return
    if not (old_source and old_dest):
        return

    async with get_session() as session:
        existing = await crud.get_user_chats(session, admin_user_id)
        if existing:
            return
        user = await crud.get_user(session, admin_user_id)
        if user is None:
            await crud.create_user(session, admin_user_id, None, "admin")
        try:
            lookback = int(old_lookback) if old_lookback else 24
        except ValueError:
            lookback = 24
        await crud.create_chat(
            session,
            user_id=admin_user_id,
            name="Migrated chat",
            source=old_source,
            dest=old_dest,
            session_id=None,
            schedule_time=old_time or "09:00",
            lookback_hours=lookback,
        )

    logger.info("Migrated existing config to DB (session_id is None — re-authorize via /start)")


async def main() -> None:
    setup_logging()
    config = Config.from_env()
    analyzer.init(config.groq_api_key)

    await init_db()
    logger.info("Database initialized")

    await _migrate_legacy_env(config.admin_user_id)

    userbot.manager = UserbotManager(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        db_session_factory=get_session,
    )
    await userbot.manager.start_all()

    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["admin_user_id"] = config.admin_user_id

    scheduler_mod.scheduler = DigestScheduler(
        db_factory=get_session,
        manager=userbot.manager,
        bot=application.bot,
    )
    await scheduler_mod.scheduler.start()

    _register_handlers(application)
    await _register_alerters(application.bot)

    logger.info("Starting Telegram bot polling")
    async with application:
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        keep_alive_task = asyncio.create_task(userbot.manager.keep_alive())
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        finally:
            keep_alive_task.cancel()
            try:
                await keep_alive_task
            except (asyncio.CancelledError, Exception):
                pass
            await application.updater.stop()
            await application.stop()
            if userbot.manager is not None:
                await userbot.manager.stop_all()
            if scheduler_mod.scheduler is not None:
                scheduler_mod.scheduler.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
