from __future__ import annotations

import datetime

import bcrypt
from fastapi import Request, Response
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from open_workshop_manager import settings as config

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

    reputation: Mapped[int] = mapped_column(Integer, default=0)

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


async def gen_session(user_id: int, session: AsyncSession, login_method: str = "unknown"):
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


async def check_access(response: Response, request: Request):
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
        row = result.scalar_one_or_none()

        if row is None:
            return False

        row.last_request_date = datetime.datetime.now()
        await session.commit()

        return {
            "owner_id": row.owner_id,
            "login_method": row.login_method,
        }


async def update_session(response: Response, request: Request) -> bool:
    access_result = await check_access(response=response, request=request)
    if not access_result or access_result.get("owner_id", -1) < 0:
        return False

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Session).where(
                Session.access_token == request.cookies.get("accessToken", "")
            )
        )

        row = result.scalar_one_or_none()
        if row is None:
            return False

        row.last_request_date = datetime.datetime.now()
        await session.commit()
        return True


async def init_models() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
