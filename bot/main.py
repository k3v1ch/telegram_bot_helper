import argparse
import asyncio
import logging
import sys
from datetime import timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telethon import TelegramClient

from bot.analyzer import analyze_messages
from bot.config import Config
from bot.reader import fetch_messages
from bot.sender import send_digest, send_empty_notice, send_error

MSK = timezone(timedelta(hours=3))

logger = logging.getLogger("bot")


def setup_logging() -> None:
    log_dir = Path("/app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / "digest.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def create_client(config: Config) -> TelegramClient:
    session_dir = Path("/app/sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(config.session_path),
        config.telegram_api_id,
        config.telegram_api_hash,
    )


async def run_digest(client: TelegramClient, config: Config) -> None:
    logger.info("Starting digest generation")

    try:
        messages = await fetch_messages(client, config)

        if not messages:
            await send_empty_notice(client, config)
            return

        source_entity = await client.get_entity(config.source_chat_id)
        source_name = getattr(source_entity, "title", str(config.source_chat_id))

        digest_text = await analyze_messages(messages, config)
        await send_digest(client, config, digest_text, len(messages), source_name)

    except Exception as e:
        logger.exception("Digest generation failed")
        try:
            await send_error(client, config, str(e))
        except Exception:
            logger.exception("Failed to send error notification")


async def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Telegram Digest Bot")
    parser.add_argument("--now", action="store_true", help="Run digest immediately")
    args = parser.parse_args()

    config = Config.from_env()
    client = create_client(config)

    await client.start(phone=config.telegram_phone)
    logger.info("Telethon client connected")

    if args.now:
        await run_digest(client, config)
    else:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_digest,
            CronTrigger(
                hour=config.digest_hour,
                minute=config.digest_minute,
                timezone=MSK,
            ),
            args=[client, config],
        )
        scheduler.start()
        logger.info(f"Scheduler started, digest at {config.digest_time} MSK daily")

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
            logger.info("Scheduler stopped")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
