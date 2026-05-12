import logging
from typing import AsyncContextManager, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from bot.db import crud

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


class UserbotManager:
    def __init__(self, api_id: int, api_hash: str, db_session_factory: SessionFactory):
        self.api_id = api_id
        self.api_hash = api_hash
        self.db_session_factory = db_session_factory
        self._clients: dict[int, TelegramClient] = {}
        self._pending: dict[int, TelegramClient] = {}

    async def start_all(self) -> None:
        async with self.db_session_factory() as session:
            user_ids = await crud.get_authorized_user_ids(session)

        started = 0
        for user_id in user_ids:
            try:
                if await self.start_client(user_id):
                    started += 1
            except Exception:
                logger.exception(f"Failed to start userbot for user {user_id}")

        logger.info(f"Started {started} userbots")

    async def start_client(self, user_id: int) -> bool:
        async with self.db_session_factory() as session:
            session_string = await crud.get_session_str(session, user_id)

        if not session_string:
            logger.warning(f"No session string for user {user_id}")
            return False

        client = TelegramClient(
            StringSession(session_string), self.api_id, self.api_hash
        )
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            logger.warning(f"User {user_id} session is not authorized")
            return False

        self._clients[user_id] = client
        logger.info(f"Userbot started for user {user_id}")
        return True

    async def stop_client(self, user_id: int) -> None:
        client = self._clients.pop(user_id, None)
        if client is not None:
            await client.disconnect()
            logger.info(f"Userbot stopped for user {user_id}")

    async def stop_all(self) -> None:
        for user_id, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception:
                logger.exception(f"Failed to disconnect userbot for user {user_id}")
        self._clients.clear()
        logger.info("All userbots stopped")

    async def get_client(self, user_id: int) -> TelegramClient:
        if user_id not in self._clients:
            raise ValueError(f"No active client for {user_id}")
        return self._clients[user_id]

    async def is_connected(self, user_id: int) -> bool:
        client = self._clients.get(user_id)
        return client is not None and client.is_connected()

    async def authorize_new(self, user_id: int, phone: str) -> str:
        client = TelegramClient(StringSession(""), self.api_id, self.api_hash)
        await client.connect()
        result = await client.send_code_request(phone)
        self._pending[user_id] = client
        return result.phone_code_hash

    async def confirm_code(
        self,
        user_id: int,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool:
        client = self._pending.get(user_id)
        if client is None:
            raise ValueError(f"No pending authorization for {user_id}")

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                raise
            await client.sign_in(password=password)

        session_string = client.session.save()

        async with self.db_session_factory() as session:
            await crud.save_session(session, user_id, phone, session_string)
            await crud.set_authorized(session, user_id, True)

        self._pending.pop(user_id, None)
        self._clients[user_id] = client
        logger.info(f"User {user_id} authorized and userbot active")
        return True

    async def revoke(self, user_id: int) -> None:
        await self.stop_client(user_id)
        async with self.db_session_factory() as session:
            await crud.save_session(session, user_id, "", "")
            await crud.set_authorized(session, user_id, False)
        logger.info(f"User {user_id} session revoked")
