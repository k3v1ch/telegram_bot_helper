import asyncio
import logging
from typing import AsyncContextManager, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from bot.db import crud

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]

KEEP_ALIVE_INTERVAL_SEC = 300


class UserbotManager:
    """Manages multiple Telethon clients keyed by ``session_id`` (one per row in user_sessions)."""

    def __init__(self, api_id: int, api_hash: str, db_session_factory: SessionFactory):
        self.api_id = api_id
        self.api_hash = api_hash
        self.db_session_factory = db_session_factory
        self._clients: dict[int, TelegramClient] = {}
        self._pending: dict[int, TelegramClient] = {}  # keyed by session_id

    # --- Lifecycle ----------------------------------------------------

    async def start_all(self) -> None:
        async with self.db_session_factory() as db:
            sessions = await crud.get_authorized_sessions(db)

        started = 0
        for s in sessions:
            try:
                if await self.start_client(s.id):
                    started += 1
            except Exception:
                logger.exception(f"Failed to start userbot for session {s.id}")

        logger.info(f"Started {started}/{len(sessions)} userbots")

    async def start_client(self, session_id: int) -> bool:
        async with self.db_session_factory() as db:
            row = await crud.get_session_by_id(db, session_id)
        if row is None or not row.session_string:
            logger.warning(f"No session string for session {session_id}")
            return False

        client = TelegramClient(
            StringSession(row.session_string), self.api_id, self.api_hash
        )
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            logger.warning(f"Session {session_id} is not authorized")
            return False

        self._clients[session_id] = client
        logger.info(f"Userbot started for session {session_id} (user {row.user_id})")
        return True

    async def stop_client(self, session_id: int) -> None:
        client = self._clients.pop(session_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                logger.exception(f"Disconnect error for session {session_id}")
            logger.info(f"Userbot stopped for session {session_id}")

    async def stop_user(self, user_id: int) -> None:
        async with self.db_session_factory() as db:
            sessions = await crud.get_user_sessions(db, user_id)
        for s in sessions:
            await self.stop_client(s.id)

    async def stop_all(self) -> None:
        for session_id in list(self._clients.keys()):
            await self.stop_client(session_id)
        logger.info("All userbots stopped")

    # --- Access -------------------------------------------------------

    async def get_client(self, session_id: int) -> TelegramClient:
        if session_id not in self._clients:
            raise ValueError(f"No active client for session {session_id}")
        return self._clients[session_id]

    async def is_connected(self, session_id: int) -> bool:
        client = self._clients.get(session_id)
        return client is not None and client.is_connected()

    # --- Authorization (multi-account) --------------------------------

    async def authorize_new(self, user_id: int, phone: str, label: str) -> tuple[int, str]:
        """Begin auth for a NEW session row. Returns (session_id, phone_code_hash)."""
        client = TelegramClient(StringSession(""), self.api_id, self.api_hash)
        await client.connect()
        result = await client.send_code_request(phone)

        async with self.db_session_factory() as db:
            row = await crud.create_session(db, user_id=user_id, phone=phone, label=label)
            session_id = row.id

        self._pending[session_id] = client
        return session_id, result.phone_code_hash

    async def confirm_code(
        self,
        session_id: int,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool:
        client = self._pending.get(session_id)
        if client is None:
            raise ValueError(f"No pending authorization for session {session_id}")

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                raise
            await client.sign_in(password=password)

        session_string = client.session.save()

        async with self.db_session_factory() as db:
            await crud.update_session_credentials(
                db, session_id=session_id, session_string=session_string, authorized=True
            )

        self._pending.pop(session_id, None)
        self._clients[session_id] = client
        logger.info(f"Session {session_id} authorized and active")
        return True

    async def cancel_pending(self, session_id: int) -> None:
        client = self._pending.pop(session_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        async with self.db_session_factory() as db:
            row = await crud.get_session_by_id(db, session_id)
            if row is not None and not row.is_authorized:
                await crud.delete_session(db, session_id)

    async def revoke(self, session_id: int) -> None:
        await self.stop_client(session_id)
        async with self.db_session_factory() as db:
            await crud.delete_session(db, session_id)
        logger.info(f"Session {session_id} revoked and deleted")

    # --- Keep-alive ---------------------------------------------------

    async def keep_alive(self) -> None:
        while True:
            try:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL_SEC)
            except asyncio.CancelledError:
                raise
            for session_id, client in list(self._clients.items()):
                if client.is_connected():
                    continue
                logger.warning(f"keep_alive: session {session_id} disconnected, reconnecting")
                try:
                    await self.stop_client(session_id)
                    ok = await self.start_client(session_id)
                    if ok:
                        logger.info(f"keep_alive: session {session_id} reconnected")
                    else:
                        logger.warning(f"keep_alive: session {session_id} reconnect failed")
                except Exception:
                    logger.exception(f"keep_alive: reconnect raised for session {session_id}")
