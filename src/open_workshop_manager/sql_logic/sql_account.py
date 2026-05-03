from __future__ import annotations

import datetime
from typing import TypedDict

import bcrypt
from fastapi import Request
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.mysql import DOUBLE
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from open_workshop_manager import access_client
from open_workshop_manager import settings as config
from open_workshop_manager import standarts

async_engine: AsyncEngine = create_async_engine(
    config.mysql_url("catalog"),
    pool_pre_ping=True,
)
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


STANDART_STR_TIME = "%d.%m.%Y/%H:%M:%S"


class Account(Base):  # Аккаунты юзеров
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    yandex_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    username: Mapped[str] = mapped_column(String(128))
    last_username_reset: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    about: Mapped[str] = mapped_column(String(512), default="")  # Ограничение 512 символов
    # если содержит "local" - обращаться к этому же серверу по id юзера, в ином случае содержит прямую ссылку, если пуст, то аватара нет
    avatar_url: Mapped[str] = mapped_column(
        String(512), default=""
    )  # если "local", так же содержит после себя .расширение_файла, т.е. "local.png", "local.webp"
    grade: Mapped[str] = mapped_column(String(128), default="")

    comments: Mapped[int] = mapped_column(Integer, default=0)
    author_mods: Mapped[int] = mapped_column(Integer, default=0)

    registration_date: Mapped[datetime.datetime] = mapped_column(DateTime)

    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_password_reset: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    reputation: Mapped[float] = mapped_column(DOUBLE, default=0.0)

    # Права пользователей
    admin: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # только админ может менять грейды у всех юзеров, а так же назначать новых админов и назначать права юзерам, дает доступ ко всем правам

    write_comments: Mapped[bool] = mapped_column(Boolean, default=True)  # писать и редактировать
    set_reactions: Mapped[bool] = mapped_column(Boolean, default=True)

    create_reactions: Mapped[bool] = mapped_column(Boolean, default=False)

    mute_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # временное ограничение на все права социальными действиями на сервисе, активен если время тут больше текущего
    mute_users: Mapped[bool] = mapped_column(Boolean, default=False)  # право на мут пользователей

    publish_mods: Mapped[bool] = mapped_column(Boolean, default=True)
    change_authorship_mods: Mapped[bool] = mapped_column(Boolean, default=False)
    change_self_mods: Mapped[bool] = mapped_column(Boolean, default=True)
    change_mods: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_self_mods: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_mods: Mapped[bool] = mapped_column(Boolean, default=False)

    publish_modpacks: Mapped[bool] = mapped_column(Boolean, default=True)
    change_authorship_modpacks: Mapped[bool] = mapped_column(Boolean, default=False)
    change_self_modpacks: Mapped[bool] = mapped_column(Boolean, default=True)
    change_modpacks: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_self_modpacks: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_modpacks: Mapped[bool] = mapped_column(Boolean, default=False)

    create_forums: Mapped[bool] = mapped_column(Boolean, default=True)
    change_authorship_forums: Mapped[bool] = mapped_column(Boolean, default=False)
    change_self_forums: Mapped[bool] = mapped_column(Boolean, default=True)
    change_forums: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_self_forums: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_forums: Mapped[bool] = mapped_column(Boolean, default=False)

    change_username: Mapped[bool] = mapped_column(Boolean, default=True)
    change_about: Mapped[bool] = mapped_column(Boolean, default=True)
    change_avatar: Mapped[bool] = mapped_column(Boolean, default=True)

    vote_for_reputation: Mapped[bool] = mapped_column(Boolean, default=True)


blocked_account_creation = Table(
    "blocked_account_creation",
    Base.metadata,
    Column("yandex_id", Integer),
    Column("google_id", String(512)),
    Column("forget", DateTime),
)


class Session(Base):  # Теги для модов
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(512), nullable=True)

    broken: Mapped[str | None] = mapped_column(
        String(124), nullable=True
    )  # Сессия закрыта по причине - `logout`, `too many sessions`

    login_method: Mapped[str | None] = mapped_column(String(124), nullable=True)

    last_request_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    start_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    end_date_access: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    end_date_refresh: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


Index(
    "ix_sessions_access_refresh_broken",
    Session.access_token,
    Session.refresh_token,
    Session.broken,
    mysql_length={"access_token": 72, "refresh_token": 72, "broken": 16},
)


black_list = Table(
    "black_list",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("accounts.id")),
    Column("blocked_id", Integer, ForeignKey("accounts.id")),
    Column("when", DateTime),
)

mod_and_author = Table(
    "mods_and_authors",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("accounts.id")),
    Column(
        "owner", Boolean
    ),  # только овнеры могут удалять свои моды, передавать овнерство другим, приглашать других на правах члена (не может удалить мод и не может приглашать новых членов)
    Column("mod_id", Integer),
)

Index(
    "ix_mods_and_authors_user_mod",
    mod_and_author.c.user_id,
    mod_and_author.c.mod_id,
)
Index(
    "ix_mods_and_authors_mod_user",
    mod_and_author.c.mod_id,
    mod_and_author.c.user_id,
)

modpack_and_author = Table(
    "modpacks_and_authors",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("accounts.id")),
    Column("owner", Boolean),
    Column("modpack_id", Integer),
)

Index(
    "ix_modpacks_and_authors_user_modpack",
    modpack_and_author.c.user_id,
    modpack_and_author.c.modpack_id,
)
Index(
    "ix_modpacks_and_authors_modpack_user",
    modpack_and_author.c.modpack_id,
    modpack_and_author.c.user_id,
)


class ReputationVote(Base):
    __tablename__ = "reputation_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voter_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )


Index(
    "ux_reputation_votes_voter_target",
    ReputationVote.voter_id,
    ReputationVote.target_type,
    ReputationVote.target_id,
    unique=True,
)


class ReputationVoteHistory(Base):
    __tablename__ = "reputation_vote_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voter_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_name: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_value: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    reputation_delta: Mapped[float] = mapped_column(DOUBLE, nullable=False)
    mod_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)


Index(
    "ix_reputation_vote_history_voter_created",
    ReputationVoteHistory.voter_id,
    ReputationVoteHistory.created_at,
)
Index(
    "ux_reputation_vote_history_voter_target",
    ReputationVoteHistory.voter_id,
    ReputationVoteHistory.target_type,
    ReputationVoteHistory.target_id,
    unique=True,
)


class Forum(Base):  # Форумы, личные сообщения и все что угодно
    __tablename__ = "forums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str | None] = mapped_column(String(124), nullable=True)
    description: Mapped[str | None] = mapped_column(String(4096), nullable=True)  # Ограничение 4096 символов

    to_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # game / mod / private_messages
    to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reputation: Mapped[int | None] = mapped_column(Integer, nullable=True)

    creation_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    update_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_comment_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class Comment(Base):  # Теги для модов
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    text: Mapped[str | None] = mapped_column(String(8192), nullable=True)

    forum_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    creation_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    update_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    reputation: Mapped[int | None] = mapped_column(Integer, nullable=True)


comments_reactions = Table(
    "unity_comments_reactions",
    Base.metadata,
    Column("comment_id", Integer, ForeignKey("comments.id")),
    Column("user_id", Integer, ForeignKey("accounts.id")),
    Column("reaction_id", Integer, ForeignKey("reactions.id")),
    Column("when", DateTime),
)


class Reaction(Base):  # Жанры для игр
    __tablename__ = "reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(124), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    creation_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    update_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class _SessionTokenEntry(TypedDict):
    token: str
    end: datetime.datetime


class SessionTokens(TypedDict):
    access: _SessionTokenEntry
    refresh: _SessionTokenEntry


async def gen_session(
    user_id: int,
    session: AsyncSession,
    login_method: str = "unknown",
) -> SessionTokens:
    ddate = datetime.datetime.now()
    result = await session.execute(
        select(Session).where(
            Session.owner_id == user_id,
            Session.broken.is_(None),
            Session.end_date_refresh > ddate,
        )
    )
    rows = result.scalars().all()

    if len(rows) > 9:
        await session.execute(
            update(Session)
            .where(Session.id.in_([row.id for row in rows]))
            .values(broken="too many sessions")
        )

    access_token = (
        bcrypt.hashpw(
            str(datetime.datetime.now().microsecond).encode("utf-8"), bcrypt.gensalt(6)
        )
    ).decode("utf-8")
    refresh_token = (
        bcrypt.hashpw(
            str(datetime.datetime.now().microsecond).encode("utf-8"), bcrypt.gensalt(7)
        )
    ).decode("utf-8")

    end_access = ddate + datetime.timedelta(minutes=40)
    end_refresh = ddate + datetime.timedelta(days=60)

    await session.execute(
        insert(Session).values(
            owner_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            login_method=login_method,
            last_request_date=ddate,
            start_date=ddate,
            end_date_access=end_access,
            end_date_refresh=end_refresh,
        )
    )

    return {
        "access": {"token": access_token, "end": end_access},
        "refresh": {"token": refresh_token, "end": end_refresh},
    }


async def no_from_russia(request: Request) -> str | None:
    if request.headers.get("CF-Connecting-IP", "") == "185.64.104.19":
        return "Запрещено на основании законодательства РФ."
    if request.headers.get("CF-IPCountry", "") == "RU":
        return "Запрещено на основании законодательства РФ."
    if request.headers.get("X-Region", "") == "ru":
        return "Запрещено на основании законодательства РФ."
    if request.headers.get("X-From-Russia", "") == "1":
        return "Запрещено на основании законодательства РФ."
    return None


def _access_context_from_rows(
    account_row: Account,
    session_row: Session,
) -> access_client.AccessState:
    password_change_available_at = (
        account_row.last_password_reset + datetime.timedelta(minutes=5)
        if account_row.last_password_reset
        else None
    )
    username_change_available_at = (
        account_row.last_username_reset + datetime.timedelta(days=30)
        if account_row.last_username_reset
        else None
    )
    return access_client.AccessState(
        authenticated=True,
        owner_id=account_row.id,
        login_method=session_row.login_method,
        admin=bool(account_row.admin),
        write_comments=bool(account_row.write_comments),
        set_reactions=bool(account_row.set_reactions),
        create_reactions=bool(account_row.create_reactions),
        mute_until=account_row.mute_until,
        mute_users=bool(account_row.mute_users),
        publish_mods=bool(account_row.publish_mods),
        change_authorship_mods=bool(account_row.change_authorship_mods),
        change_self_mods=bool(account_row.change_self_mods),
        change_mods=bool(account_row.change_mods),
        delete_self_mods=bool(account_row.delete_self_mods),
        delete_mods=bool(account_row.delete_mods),
        publish_modpacks=bool(account_row.publish_modpacks),
        change_authorship_modpacks=bool(account_row.change_authorship_modpacks),
        change_self_modpacks=bool(account_row.change_self_modpacks),
        change_modpacks=bool(account_row.change_modpacks),
        delete_self_modpacks=bool(account_row.delete_self_modpacks),
        delete_modpacks=bool(account_row.delete_modpacks),
        create_forums=bool(account_row.create_forums),
        change_authorship_forums=bool(account_row.change_authorship_forums),
        change_self_forums=bool(account_row.change_self_forums),
        change_forums=bool(account_row.change_forums),
        delete_self_forums=bool(account_row.delete_self_forums),
        delete_forums=bool(account_row.delete_forums),
        change_username=bool(account_row.change_username),
        change_about=bool(account_row.change_about),
        change_avatar=bool(account_row.change_avatar),
        vote_for_reputation=bool(account_row.vote_for_reputation),
        last_username_reset=account_row.last_username_reset,
        last_password_reset=account_row.last_password_reset,
        password_change_available_at=password_change_available_at,
        username_change_available_at=username_change_available_at,
    )


def should_touch_session(
    last_request_date: datetime.datetime | None,
    now: datetime.datetime | None = None,
) -> bool:
    now = now or datetime.datetime.now()
    interval_raw = getattr(config, "SESSION_TOUCH_INTERVAL_SECONDS", 60)
    try:
        interval_seconds = int(interval_raw)
    except (TypeError, ValueError):
        interval_seconds = 60

    if interval_seconds <= 0 or last_request_date is None:
        return True

    try:
        return now - last_request_date >= datetime.timedelta(seconds=interval_seconds)
    except TypeError:
        return True


async def check_access(request: Request) -> access_client.AccessState | bool:
    access_token = request.cookies.get("accessToken", "")
    refresh_token = request.cookies.get("refreshToken", "")

    if not access_token or not refresh_token:
        return False

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Session).where(
                Session.access_token == access_token,
                Session.refresh_token == refresh_token,
                Session.broken.is_(None),
            )
        )
        session_row = result.scalar_one_or_none()
        if session_row is None or session_row.owner_id is None:
            return False

        account_row = await session.get(Account, session_row.owner_id)
        if account_row is None:
            return False

        now = datetime.datetime.now()
        if should_touch_session(session_row.last_request_date, now):
            session_row.last_request_date = now
            await session.commit()
        return _access_context_from_rows(account_row, session_row)


async def update_session(request: Request) -> bool:
    access_result = await check_access(request=request)
    return bool(access_result and access_result.get("owner_id", -1) >= 0)


async def init_models() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
