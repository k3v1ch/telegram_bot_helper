import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot
from telethon import TelegramClient

from bot.alerter import Alerter
from bot.analyzer import analyze_messages
from bot.config import Config
from bot.digest_bot import build_bot_app
from bot.health import make_health_app, run_health_server
from bot.pinned import check_and_forward_pinned
from bot.reader import fetch_messages
from bot.sender import send_digest, send_empty_notice, send_error
from bot.state import BotState
from bot.stats import save_today_count

MSK = timezone(timedelta(hours=3))

logger = logging.getLogger("bot")

userbot_client: TelegramClient | None = None
_digest_lock = asyncio.Lock()


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


def create_userbot(config: Config) -> TelegramClient:
    session_dir = Path("/app/sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(config.session_path),
        config.telegram_api_id,
        config.telegram_api_hash,
    )


async def run_digest(
    userbot: TelegramClient, bot: Bot, config: Config, state: BotState,
    lookback_hours: int | None = None, weekly: bool = False,
) -> int:
    if _digest_lock.locked():
        logger.warning("Digest already in progress, waiting for the running one to finish")

    async with _digest_lock:
        return await _run_digest_locked(userbot, bot, config, state, lookback_hours, weekly)


async def _run_digest_locked(
    userbot: TelegramClient, bot: Bot, config: Config, state: BotState,
    lookback_hours: int | None, weekly: bool,
) -> int:
    hours = lookback_hours if lookback_hours is not None else config.lookback_hours
    label = "weekly" if weekly else "daily"
    logger.info(f"Starting {label} digest generation (lookback={hours}h)")

    try:
        fetch_result = await fetch_messages(userbot, config, lookback_hours=lookback_hours)
        messages = fetch_result.messages
        count = len(messages)

        save_today_count(config.data_dir, count)
        state.record_run(count)

        if not messages:
            await send_empty_notice(bot, config)
            return 0

        source_entity = await userbot.get_entity(config.source_chat_id)
        source_name = getattr(source_entity, "title", str(config.source_chat_id))

        start_time = messages[0]["time"]
        end_time = messages[-1]["time"]

        pinned_preview = await check_and_forward_pinned(userbot, bot, config)

        analysis = await analyze_messages(messages, config, weekly=weekly)

        logger.info(
            f"Pipeline: {fetch_result.total_fetched} fetched → "
            f"{fetch_result.after_stage1} after S1 → "
            f"{analysis.after_stage2} after S2"
        )

        if weekly:
            period = "7d"
        elif hours <= 1:
            period = "1h"
        elif hours <= 5:
            period = "5h"
        elif hours <= 12:
            period = "12h"
        elif hours <= 24:
            period = "24h"
        else:
            period = f"{hours}h"

        await send_digest(
            bot, config, analysis.text, count, source_name, start_time, end_time,
            total_fetched=fetch_result.total_fetched,
            after_stage1=fetch_result.after_stage1,
            after_stage2=analysis.after_stage2,
            pinned_preview=pinned_preview,
            weekly=weekly,
            period=period,
        )

        return count

    except Exception as e:
        logger.exception("Digest generation failed")
        try:
            await send_error(bot, config, str(e))
        except Exception:
            logger.exception("Failed to send error notification")
        raise


async def run_bot(app, stop_event: asyncio.Event) -> None:
    try:
        await app.initialize()
        await app.updater.start_polling(drop_pending_updates=True)
        await app.start()
        logger.info("Telegram bot started, /start and /menu available")
        await stop_event.wait()
    except Exception:
        logger.exception("Bot polling failed")
    finally:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:
            pass


async def run_userbot(userbot: TelegramClient, stop_event: asyncio.Event) -> None:
    try:
        await stop_event.wait()
    except Exception:
        pass
    finally:
        await userbot.disconnect()


async def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Telegram Digest Bot")
    parser.add_argument("--now", action="store_true", help="Run digest immediately")
    args = parser.parse_args()

    config = Config.from_env()
    state = BotState(config.data_dir, config.alerts_enabled_default)

    global userbot_client
    userbot = create_userbot(config)
    userbot_client = userbot

    await userbot.start(phone=config.telegram_phone)
    logger.info("Telethon userbot connected")

    bot = Bot(token=config.bot_token)

    if args.now:
        await run_digest(userbot, bot, config, state)
        await userbot.disconnect()
        return

    scheduler = AsyncIOScheduler()

    async def scheduled_digest():
        try:
            await run_digest(userbot, bot, config, state)
        except Exception:
            pass
        _update_next_run(scheduler, state)

    async def scheduled_weekly():
        try:
            await run_digest(userbot, bot, config, state, lookback_hours=168, weekly=True)
        except Exception:
            pass

    scheduler.add_job(
        scheduled_digest,
        CronTrigger(hour=config.digest_hour, minute=config.digest_minute, timezone=MSK),
        id="digest_job",
        misfire_grace_time=600,
        coalesce=True,
    )

    scheduler.add_job(
        scheduled_weekly,
        CronTrigger(day_of_week=config.weekly_digest_day, hour=5, minute=0, timezone=MSK),
        id="weekly_job",
        misfire_grace_time=1800,
        coalesce=True,
    )

    async def check_pinned():
        try:
            await check_and_forward_pinned(userbot, bot, config)
        except Exception:
            logger.exception("Periodic pinned check failed")

    scheduler.add_job(
        check_pinned,
        IntervalTrigger(minutes=30),
        id="pinned_check",
        misfire_grace_time=300,
        coalesce=True,
    )

    scheduler.start()
    _update_next_run(scheduler, state)
    logger.info(f"Scheduler started, digest at {config.digest_time} MSK daily, weekly on {config.weekly_digest_day}")

    await check_pinned()
    logger.info("Initial pinned message check complete")

    async def digest_callback(lookback_hours: int | None = None, weekly: bool = False) -> int:
        count = await run_digest(userbot, bot, config, state, lookback_hours=lookback_hours, weekly=weekly)
        _update_next_run(scheduler, state)
        return count

    alerter = Alerter(userbot, bot, config, state)
    alerter.register()

    app = build_bot_app(config, state, digest_callback)
    stop_event = asyncio.Event()

    health_app = make_health_app(lambda: userbot_client, state)

    try:
        await asyncio.gather(
            run_bot(app, stop_event),
            run_userbot(userbot, stop_event),
            run_health_server(health_app, config.health_port, stop_event),
        )
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        stop_event.set()
        scheduler.shutdown()
        logger.info("Shutdown complete")


def _update_next_run(scheduler: AsyncIOScheduler, state: BotState) -> None:
    job = scheduler.get_job("digest_job")
    if job and job.next_run_time:
        state.set_next_run(job.next_run_time)


if __name__ == "__main__":
    asyncio.run(main())
