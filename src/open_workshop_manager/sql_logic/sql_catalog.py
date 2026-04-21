from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, relationship

from open_workshop_manager import settings as config

async_engine: AsyncEngine = create_async_engine(
    config.mysql_url("catalog"),
    pool_pre_ping=True,
)
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
base: Any = declarative_base()


# Связывающие БД
game_genres = Table(
    "unity_games_genres",
    base.metadata,  # Теги для игр
    Column("game_id", Integer, ForeignKey("games.id")),
    Column("genre_id", Integer, ForeignKey("genres.id")),
)

allowed_mods_tags = Table(
    "unity_allowed_mods_tags",
    base.metadata,  # Разрешенные игрой теги для модов
    Column("game_id", Integer, ForeignKey("games.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

mods_tags = Table(
    "unity_mods_tags",
    base.metadata,  # Теги для игр
    Column("mod_id", Integer, ForeignKey("mods.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

mods_dependencies = Table(
    "unity_mods_dependencies",
    base.metadata,  # Зависимости мода
    Column("mod_id", Integer, ForeignKey("mods.id")),
    Column("dependence", Integer, ForeignKey("mods.id")),
    extend_existing=True,
)


# Основные БД
class Game(base):  # Таблица "игры"
    __tablename__ = "games"
    id: Any = Column(Integer, primary_key=True)
    name: Any = Column(String(128))
    type: Any = Column(String(32))

    short_description: Any = Column(String(512))
    description: Any = Column(Text)

    mods_downloads: Any = Column(BigInteger)
    mods_count: Any = Column(BigInteger)

    creation_date: Any = Column(DateTime)

    source: Any = Column(String(64))
    source_id: Any = Column(BigInteger, nullable=True)

    genres: Any = relationship("Genre", secondary=game_genres, backref="games")
    allowed_tags_for_mods: Any = relationship(
        "Tag", secondary=allowed_mods_tags, backref="games", viewonly=True
    )


class Mod(base):  # Таблица "моды"
    __tablename__ = "mods"
    id: Any = Column(Integer, primary_key=True)
    name: Any = Column(String(128))

    short_description: Any = Column(String(512))
    description: Any = Column(Text)

    size: Any = Column(BigInteger)
    size_unpacked: Any = Column(BigInteger, nullable=True)

    condition: Any = Column(Integer)  # 0 - загружен, 1 - загружается
    public: Any = Column(
        Integer
    )  # 0 - публичен, 1 - публичен, не встречается в каталоге, не индексируется, 2 - доступен с предоставлением токена

    date_creation: Any = Column(DateTime)
    date_update_file: Any = Column(DateTime)
    date_edit: Any = Column(DateTime)

    source: Any = Column(String(64))
    source_id: Any = Column(BigInteger, nullable=True)
    downloads: Any = Column(BigInteger)

    tags: Any = relationship("Tag", secondary=mods_tags, backref="mods")
    dependencies: Any = relationship(
        "Mod",
        secondary=mods_dependencies,
        primaryjoin=(mods_dependencies.c.mod_id == id),
        secondaryjoin=(mods_dependencies.c.dependence == id),
        backref="mods",
        foreign_keys=[mods_dependencies.c.mod_id, mods_dependencies.c.dependence],
    )
    game: Any = Column(Integer, ForeignKey("games.id"))


class Resource(base):  # Ресурсы (скриншоты и лого)
    __tablename__ = "resources"
    id: Any = Column(Integer, primary_key=True)
    type: Any = Column(String(64))

    # Если начинается с local/, то по факту можно заменить на {config.STORAGE_URL}/(действие)/resource/...
    # При возвращении юзеру обязательно перерабатывать url в фактический (с точки зрения юзера)
    url: Any = Column(String(512))
    size: Any = Column(BigInteger, nullable=True)

    @property
    def real_url(self, action: str = "download"):
        if self.url.startswith("local/"):
            return f"{config.STORAGE_URL}/{action}/resource/{self.url.replace('local/', '')}"
        return self.url

    date_event: Any = Column(DateTime)

    owner_type: Any = Column(String(64))  # games, mods, etc...
    owner_id: Any = Column(Integer)


# Теги
class Genre(base):  # Жанры для игр
    __tablename__ = "genres"
    id: Any = Column(Integer, primary_key=True)
    name: Any = Column(String(128))


class Tag(base):  # Теги для модов
    __tablename__ = "tags"
    id: Any = Column(Integer, primary_key=True)
    name: Any = Column(String(128))

    associated_games: Any = relationship(
        "Game", secondary=allowed_mods_tags, backref="tags", viewonly=True
    )


async def init_models() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(base.metadata.create_all)
