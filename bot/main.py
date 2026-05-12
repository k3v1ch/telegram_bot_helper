import asyncio
import logging

from bot import userbot
from bot.config import Config
from bot.db.database import get_session, init_db
from bot.userbot.manager import UserbotManager

logger = logging.getLogger("bot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


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
    logger.info("Startup complete (bot polling not started yet)")


if __name__ == "__main__":
    asyncio.run(main())
