import asyncio
import logging
from typing import Callable

from aiohttp import web
from telethon import TelegramClient

from bot.state import BotState

logger = logging.getLogger(__name__)


def make_health_app(get_userbot: Callable[[], TelegramClient | None], state: BotState) -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        userbot = get_userbot()
        connected = userbot is not None and userbot.is_connected()
        status_code = 200 if connected else 503
        body = {
            "status": "ok" if connected else "degraded",
            "userbot_connected": connected,
            "last_run": state.last_run,
            "last_count": state.last_count,
            "next_run": state.next_run,
            "alerts_enabled": state.alerts_enabled,
        }
        return web.json_response(body, status=status_code)

    async def ping(_request: web.Request) -> web.Response:
        return web.Response(text="pong")

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)
    return app


async def run_health_server(app: web.Application, port: int, stop_event: asyncio.Event) -> None:
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Health server listening on :{port} (/health, /ping)")
        await stop_event.wait()
    except Exception:
        logger.exception("Health server failed")
    finally:
        try:
            await runner.cleanup()
        except Exception:
            pass
