from datetime import date as date_type, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Chat,
    DailyStats,
    Digest,
    PinnedMessage,
    User,
    UserSession,
)


# --- Users ---


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    first_name: str | None,
) -> User:
    user = User(user_id=user_id, username=username, first_name=first_name)
    session.add(user)
    await session.flush()
    return user


async def update_last_active(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(User).where(User.user_id == user_id).values(last_active=datetime.utcnow())
    )


async def set_blocked(session: AsyncSession, user_id: int, blocked: bool) -> None:
    await session.execute(
        update(User).where(User.user_id == user_id).values(is_blocked=blocked)
    )


async def get_all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User))
    return list(result.scalars().all())


# --- Sessions ---


async def get_session_str(session: AsyncSession, user_id: int) -> str | None:
    result = await session.execute(
        select(UserSession.session_string).where(UserSession.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_authorized_user_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(
        select(UserSession.user_id).where(UserSession.is_authorized.is_(True))
    )
    return list(result.scalars().all())


async def save_session(
    session: AsyncSession,
    user_id: int,
    phone: str,
    session_string: str,
) -> None:
    stmt = pg_insert(UserSession).values(
        user_id=user_id,
        phone=phone,
        session_string=session_string,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserSession.user_id],
        set_={"phone": phone, "session_string": session_string},
    )
    await session.execute(stmt)


async def set_authorized(session: AsyncSession, user_id: int, authorized: bool) -> None:
    values: dict = {"is_authorized": authorized}
    if authorized:
        values["authorized_at"] = datetime.utcnow()
    await session.execute(
        update(UserSession).where(UserSession.user_id == user_id).values(**values)
    )


# --- Chats ---


async def get_user_chats(session: AsyncSession, user_id: int) -> list[Chat]:
    result = await session.execute(select(Chat).where(Chat.user_id == user_id))
    return list(result.scalars().all())


async def get_chat(session: AsyncSession, chat_id: int) -> Chat | None:
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    return result.scalar_one_or_none()


async def create_chat(
    session: AsyncSession,
    user_id: int,
    name: str,
    source: str,
    dest: str,
    schedule_time: str = "05:00",
    lookback_hours: int = 24,
) -> Chat:
    chat = Chat(
        user_id=user_id,
        name=name,
        source=source,
        dest=dest,
        schedule_time=schedule_time,
        lookback_hours=lookback_hours,
    )
    session.add(chat)
    await session.flush()
    return chat


async def update_chat(session: AsyncSession, chat_id: int, **kwargs) -> None:
    if not kwargs:
        return
    await session.execute(update(Chat).where(Chat.id == chat_id).values(**kwargs))


async def delete_chat(session: AsyncSession, chat_id: int) -> None:
    await session.execute(delete(Chat).where(Chat.id == chat_id))


async def get_all_active_chats(session: AsyncSession) -> list[Chat]:
    result = await session.execute(select(Chat).where(Chat.is_active.is_(True)))
    return list(result.scalars().all())


# --- Digests ---


async def save_digest(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    period: str,
    raw_text: str,
    message_count: int,
    s1_count: int,
    s2_count: int,
) -> Digest:
    digest = Digest(
        chat_id=chat_id,
        user_id=user_id,
        period=period,
        raw_text=raw_text,
        message_count=message_count,
        s1_count=s1_count,
        s2_count=s2_count,
    )
    session.add(digest)
    await session.flush()
    return digest


async def search_digests(
    session: AsyncSession,
    user_id: int,
    keyword: str,
    limit: int = 5,
) -> list[Digest]:
    pattern = f"%{keyword}%"
    result = await session.execute(
        select(Digest)
        .where(Digest.user_id == user_id, Digest.raw_text.ilike(pattern))
        .order_by(Digest.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_last_digest(session: AsyncSession, chat_id: int) -> Digest | None:
    result = await session.execute(
        select(Digest)
        .where(Digest.chat_id == chat_id)
        .order_by(Digest.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_last_user_digest(session: AsyncSession, user_id: int) -> Digest | None:
    result = await session.execute(
        select(Digest)
        .where(Digest.user_id == user_id)
        .order_by(Digest.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_user_digests(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count(Digest.id)).where(Digest.user_id == user_id)
    )
    return result.scalar_one() or 0


async def count_user_digests_since(
    session: AsyncSession, user_id: int, since: datetime
) -> int:
    result = await session.execute(
        select(func.count(Digest.id)).where(
            Digest.user_id == user_id,
            Digest.created_at >= since,
        )
    )
    return result.scalar_one() or 0


# --- Stats ---


async def upsert_daily_stats(
    session: AsyncSession,
    chat_id: int,
    date: date_type,
    message_count: int,
) -> None:
    stmt = pg_insert(DailyStats).values(
        chat_id=chat_id,
        date=date,
        message_count=message_count,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyStats.chat_id, DailyStats.date],
        set_={"message_count": message_count},
    )
    await session.execute(stmt)


async def get_stats_yesterday(session: AsyncSession, chat_id: int) -> int | None:
    yesterday = date_type.today() - timedelta(days=1)
    result = await session.execute(
        select(DailyStats.message_count).where(
            DailyStats.chat_id == chat_id,
            DailyStats.date == yesterday,
        )
    )
    return result.scalar_one_or_none()


# --- Pinned ---


async def get_pinned(session: AsyncSession, chat_id: int) -> PinnedMessage | None:
    result = await session.execute(
        select(PinnedMessage).where(PinnedMessage.chat_id == chat_id)
    )
    return result.scalar_one_or_none()


async def upsert_pinned(session: AsyncSession, chat_id: int, text: str) -> None:
    stmt = pg_insert(PinnedMessage).values(
        chat_id=chat_id,
        text=text,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PinnedMessage.chat_id],
        set_={"text": text, "updated_at": datetime.utcnow()},
    )
    await session.execute(stmt)
