import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import AsyncContextManager, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bot import analyzer
from bot.db import crud
from bot.db.models import Chat
from bot.sender import send_digest, send_empty_notice, send_error
from bot.userbot.manager import UserbotManager
from bot.userbot.reader import fetch_messages, fetch_pinned_message

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


def parse_chat_topic(value: str) -> tuple[int, int]:
    chat_str, topic_str = value.split(":", 1)
    return int(chat_str), int(topic_str)


def _period_label(lookback_hours: int) -> str:
    if lookback_hours == 168:
        return "7d"
    return f"{lookback_hours}h"


class DigestScheduler:
    def __init__(self, db_factory: SessionFactory, manager: UserbotManager, bot: Bot):
        self.db_factory = db_factory
        self.manager = manager
        self.bot = bot
        self._scheduler = AsyncIOScheduler(timezone=MSK)

    async def start(self) -> None:
        async with self.db_factory() as session:
            chats = await crud.get_all_active_chats(session)

        for chat in chats:
            try:
                self.add_chat_job(chat)
            except Exception:
                logger.exception(f"Failed to schedule chat {chat.id}")

        if not self._scheduler.running:
            self._scheduler.start()
        logger.info(
            f"Scheduler started with {len(self._scheduler.get_jobs())} jobs"
        )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def add_chat_job(self, chat: Chat) -> None:
        try:
            hour_str, minute_str = chat.schedule_time.split(":", 1)
            hour, minute = int(hour_str), int(minute_str)
        except (ValueError, AttributeError):
            logger.warning(f"Invalid schedule_time '{chat.schedule_time}' for chat {chat.id}")
            return

        self._scheduler.add_job(
            self.run_digest,
            CronTrigger(hour=hour, minute=minute, timezone=MSK),
            id=f"daily_{chat.id}",
            args=(chat.id, chat.lookback_hours),
            misfire_grace_time=600,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.run_digest,
            CronTrigger(day_of_week="mon", hour=hour, minute=minute, timezone=MSK),
            id=f"weekly_{chat.id}",
            args=(chat.id, 168),
            misfire_grace_time=1800,
            coalesce=True,
            replace_existing=True,
        )
        if not chat.is_active:
            self.pause_chat_jobs(chat.id)
        logger.info(f"Scheduled chat {chat.id} ({chat.name}) at {chat.schedule_time} MSK")

    def remove_chat_jobs(self, chat_id: int) -> None:
        for prefix in ("daily", "weekly"):
            try:
                self._scheduler.remove_job(f"{prefix}_{chat_id}")
            except Exception:
                pass
        logger.info(f"Removed jobs for chat {chat_id}")

    def reschedule_chat(self, chat: Chat) -> None:
        self.remove_chat_jobs(chat.id)
        self.add_chat_job(chat)

    def pause_chat_jobs(self, chat_id: int) -> None:
        for prefix in ("daily", "weekly"):
            try:
                self._scheduler.pause_job(f"{prefix}_{chat_id}")
            except Exception:
                pass

    def resume_chat_jobs(self, chat_id: int) -> None:
        for prefix in ("daily", "weekly"):
            try:
                self._scheduler.resume_job(f"{prefix}_{chat_id}")
            except Exception:
                pass

    def remove_user_jobs(self, chat_ids: list[int]) -> None:
        for chat_id in chat_ids:
            self.remove_chat_jobs(chat_id)

    async def run_digest(self, chat_id: int, lookback_hours: int) -> None:
        async with self.db_factory() as session:
            chat = await crud.get_chat(session, chat_id)
            if chat is None:
                logger.warning(f"run_digest: chat {chat_id} not found")
                return
            if not chat.is_active:
                logger.info(f"run_digest: chat {chat_id} inactive, skipping")
                return
            user = await crud.get_user(session, chat.user_id)
            if user is None or user.is_blocked:
                logger.info(f"run_digest: user {chat.user_id} missing or blocked, skipping")
                return
            prev_pinned_row = await crud.get_pinned(session, chat.id)
            previous_pinned = prev_pinned_row.text if prev_pinned_row else None

        if not await self.manager.is_connected(chat.user_id):
            logger.warning(f"run_digest: user {chat.user_id} userbot not connected")
            return

        try:
            client = await self.manager.get_client(chat.user_id)
        except ValueError:
            logger.warning(f"run_digest: no client for user {chat.user_id}")
            return

        try:
            source_chat_id, source_topic_id = parse_chat_topic(chat.source)
            dest_chat_id, dest_topic_id = parse_chat_topic(chat.dest)
        except (ValueError, AttributeError) as e:
            logger.exception(f"run_digest: malformed source/dest for chat {chat_id}: {e}")
            return

        weekly = lookback_hours >= 168
        period_label = _period_label(lookback_hours)

        try:
            messages, pinned_changed, pinned_text = await fetch_messages(
                client,
                source_chat_id=source_chat_id,
                source_topic_id=source_topic_id,
                lookback_hours=lookback_hours,
                previous_pinned=previous_pinned,
            )
        except Exception as e:
            logger.exception(f"run_digest: fetch failed for chat {chat_id}")
            await send_error(self.bot, dest_chat_id, dest_topic_id, chat.name, str(e))
            return

        if pinned_changed:
            await self._handle_pinned(
                client, chat, dest_chat_id, dest_topic_id, source_chat_id, pinned_text
            )

        total = len(messages)
        s1_count = total

        if not messages:
            await send_empty_notice(self.bot, dest_chat_id, dest_topic_id, chat.name, period_label)
            await self._record_stats(chat, total)
            return

        try:
            digest_text, s2_count = await analyzer.analyze(
                messages,
                custom_prompt=chat.custom_prompt,
                weekly=weekly,
            )
        except Exception as e:
            logger.exception(f"run_digest: analyzer failed for chat {chat_id}")
            await send_error(self.bot, dest_chat_id, dest_topic_id, chat.name, str(e))
            return

        async with self.db_factory() as session:
            yesterday_count = await crud.get_stats_yesterday(session, chat.id)

        start_time = messages[0]["time"]
        end_time = messages[-1]["time"]

        try:
            await send_digest(
                bot=self.bot,
                dest_chat_id=dest_chat_id,
                dest_topic_id=dest_topic_id,
                chat_name=chat.name,
                digest_text=digest_text,
                total_count=total,
                s1_count=s1_count,
                s2_count=s2_count,
                yesterday_count=yesterday_count,
                period=period_label,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception:
            logger.exception(f"run_digest: send failed for chat {chat_id}")
            return

        async with self.db_factory() as session:
            await crud.save_digest(
                session,
                chat_id=chat.id,
                user_id=chat.user_id,
                period=period_label,
                raw_text=digest_text,
                message_count=total,
                s1_count=s1_count,
                s2_count=s2_count,
            )
            await crud.upsert_daily_stats(
                session,
                chat_id=chat.id,
                date=date_type.today(),
                message_count=total,
            )
        logger.info(
            f"run_digest: chat {chat.id} done — period={period_label} "
            f"total={total} s2={s2_count}"
        )

    async def _record_stats(self, chat: Chat, count: int) -> None:
        async with self.db_factory() as session:
            await crud.upsert_daily_stats(
                session, chat_id=chat.id, date=date_type.today(), message_count=count
            )

    async def _handle_pinned(
        self,
        client,
        chat: Chat,
        dest_chat_id: int,
        dest_topic_id: int,
        source_chat_id: int,
        pinned_text: str | None,
    ) -> None:
        try:
            await self.bot.send_message(
                chat_id=dest_chat_id,
                text=f"📌 Закреп обновлён • {chat.name}",
                message_thread_id=dest_topic_id or None,
            )
        except Exception:
            logger.exception(f"Failed to send pinned header for chat {chat.id}")

        try:
            pinned_msg = await fetch_pinned_message(client, source_chat_id)
            if pinned_msg is not None:
                try:
                    await client.forward_messages(dest_chat_id, pinned_msg)
                except Exception:
                    logger.exception(
                        f"Forward pinned failed for chat {chat.id}, falling back to text"
                    )
                    if pinned_text:
                        await self.bot.send_message(
                            chat_id=dest_chat_id,
                            text=f"📌 {pinned_text}",
                            message_thread_id=dest_topic_id or None,
                        )
        except Exception:
            logger.exception(f"Failed to forward pinned for chat {chat.id}")

        if pinned_text is not None:
            async with self.db_factory() as session:
                await crud.upsert_pinned(session, chat.id, pinned_text)


scheduler: DigestScheduler | None = None
