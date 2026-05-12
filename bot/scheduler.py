import logging
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.db.models import Chat

logger = logging.getLogger(__name__)

JobCallback = Callable[[int], Awaitable[None]]


class ScheduleManager:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._callback: JobCallback | None = None

    def set_callback(self, callback: JobCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def _run_job(self, chat_id: int) -> None:
        if self._callback is None:
            logger.warning(f"No callback set, skipping job for chat {chat_id}")
            return
        try:
            await self._callback(chat_id)
        except Exception:
            logger.exception(f"Scheduled job failed for chat {chat_id}")

    def add_chat_job(self, chat: Chat) -> None:
        try:
            hour_str, minute_str = chat.schedule_time.split(":", 1)
            hour, minute = int(hour_str), int(minute_str)
        except (ValueError, AttributeError):
            logger.warning(f"Invalid schedule_time '{chat.schedule_time}' for chat {chat.id}")
            return

        self._scheduler.add_job(
            self._run_job,
            CronTrigger(hour=hour, minute=minute),
            id=f"chat:{chat.id}",
            args=(chat.id,),
            misfire_grace_time=600,
            coalesce=True,
            replace_existing=True,
        )
        if not chat.is_active:
            self.pause_chat_job(chat.id)
        logger.info(f"Scheduled chat {chat.id} at {chat.schedule_time}")

    def remove_chat_job(self, chat_id: int) -> None:
        try:
            self._scheduler.remove_job(f"chat:{chat_id}")
            logger.info(f"Removed schedule for chat {chat_id}")
        except Exception:
            pass

    def pause_chat_job(self, chat_id: int) -> None:
        try:
            self._scheduler.pause_job(f"chat:{chat_id}")
        except Exception:
            pass

    def resume_chat_job(self, chat_id: int) -> None:
        try:
            self._scheduler.resume_job(f"chat:{chat_id}")
        except Exception:
            pass

    def remove_user_jobs(self, chat_ids: list[int]) -> None:
        for chat_id in chat_ids:
            self.remove_chat_job(chat_id)


manager: ScheduleManager | None = None
