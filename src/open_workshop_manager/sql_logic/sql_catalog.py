from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from open_workshop_manager import settings as config

async_engine: AsyncEngine = create_async_engine(
    config.mysql_url("catalog"),
    pool_pre_ping=True,
)
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Связывающие БД
game_genres = Table(
    "unity_games_genres",
    Base.metadata,  # Теги для игр
    Column("game_id", Integer, ForeignKey("games.id")),
    Column("genre_id", Integer, ForeignKey("genres.id")),
)

allowed_mods_tags = Table(
    "unity_allowed_mods_tags",
    Base.metadata,  # Разрешенные игрой теги для модов
    Column("game_id", Integer, ForeignKey("games.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

mods_tags = Table(
    "unity_mods_tags",
    Base.metadata,  # Теги для игр
    Column("mod_id", Integer, ForeignKey("mods.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

mods_dependencies = Table(
    "unity_mods_dependencies",
    Base.metadata,  # Зависимости мода
    Column("mod_id", Integer, ForeignKey("mods.id")),
    Column("dependence", Integer, ForeignKey("mods.id")),
    Column("optional", Boolean, nullable=False, server_default=text("0")),
    extend_existing=True,
)

Index(
    "ix_unity_mods_dependencies_mod_dependence",
    mods_dependencies.c.mod_id,
    mods_dependencies.c.dependence,
)
Index(
    "ix_unity_mods_dependencies_dependence_mod",
    mods_dependencies.c.dependence,
    mods_dependencies.c.mod_id,
)

mods_conflicts = Table(
    "unity_mods_conflicts",
    Base.metadata,  # Конфликты мода
    Column("mod_id", Integer, ForeignKey("mods.id")),
    Column("conflict", Integer, ForeignKey("mods.id")),
)

Index(
    "ix_unity_mods_conflicts_mod_conflict",
    mods_conflicts.c.mod_id,
    mods_conflicts.c.conflict,
)
Index(
    "ix_unity_mods_conflicts_conflict_mod",
    mods_conflicts.c.conflict,
    mods_conflicts.c.mod_id,
)


# Основные БД
class Game(Base):  # Таблица "игры"
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))

    short_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    mods_downloads: Mapped[int] = mapped_column(BigInteger)
    mods_count: Mapped[int] = mapped_column(BigInteger)

    creation_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    genres: Mapped[list["Genre"]] = relationship("Genre", secondary=game_genres, backref="games")
    allowed_tags_for_mods: Mapped[list["Tag"]] = relationship(
        "Tag", secondary=allowed_mods_tags, backref="games", viewonly=True
    )


class Mod(Base):  # Таблица "моды"
    __tablename__ = "mods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))

    short_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    size: Mapped[int] = mapped_column(BigInteger)
    size_unpacked: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    condition: Mapped[int] = mapped_column(Integer)  # 0 - загружен, 1 - загружается
    public: Mapped[int] = mapped_column(
        Integer
    )  # 0 - публичен, 1 - публичен, не встречается в каталоге, не индексируется, 2 - доступен с предоставлением токена

    date_creation: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    date_update_file: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    date_edit: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    git_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    downloads: Mapped[int] = mapped_column(BigInteger)

    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=mods_tags, backref="mods")
    dependencies: Mapped[list["Mod"]] = relationship(
        "Mod",
        secondary=mods_dependencies,
        primaryjoin=(mods_dependencies.c.mod_id == id),
        secondaryjoin=(mods_dependencies.c.dependence == id),
        backref="mods",
        foreign_keys=[mods_dependencies.c.mod_id, mods_dependencies.c.dependence],
    )
    conflicts: Mapped[list["Mod"]] = relationship(
        "Mod",
        secondary=mods_conflicts,
        primaryjoin=(mods_conflicts.c.mod_id == id),
        secondaryjoin=(mods_conflicts.c.conflict == id),
        backref="conflicted_by",
        foreign_keys=[mods_conflicts.c.mod_id, mods_conflicts.c.conflict],
    )
    game: Mapped[int | None] = mapped_column(Integer, ForeignKey("games.id"))
    adult: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Resource(Base):  # Ресурсы (скриншоты и лого)
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Если начинается с local/, то по факту можно заменить на {config.STORAGE_URL}/(действие)/resource/...
    # При возвращении юзеру обязательно перерабатывать url в фактический (с точки зрения юзера)
    url: Mapped[str] = mapped_column(String(512))
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    @property
    def real_url(self, action: str = "download") -> str:
        if self.url.startswith("local/"):
            return f"{config.STORAGE_URL}/{action}/resource/{self.url.replace('local/', '')}"
        return self.url

    date_event: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    owner_type: Mapped[str] = mapped_column(String(64))  # games, mods, etc...
    owner_id: Mapped[int] = mapped_column(Integer)


Index(
    "ix_resources_owner_type_owner_id_sort_order",
    Resource.owner_type,
    Resource.owner_id,
    Resource.sort_order,
    Resource.id,
)


class UploadJob(Base):  # Очередь загрузочных задач
    __tablename__ = "upload_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    transfer_url: Mapped[str] = mapped_column(String(2048))
    ws_url: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# Теги
class Genre(Base):  # Жанры для игр
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class Tag(Base):  # Теги для модов
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))

    associated_games: Mapped[list["Game"]] = relationship(
        "Game", secondary=allowed_mods_tags, backref="tags", viewonly=True
    )


async def init_models() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
