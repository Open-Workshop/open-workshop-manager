from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, DateTime, Table, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
import ow_config as config


engine = create_engine(f'mysql+mysqldb://{config.user_sql}:{config.password_sql}@{config.url_sql}/catalog')
base = declarative_base()


# Связывающие БД
game_genres = Table('unity_games_genres', base.metadata, # Теги для игр
    Column('game_id', Integer, ForeignKey('games.id')),
    Column('genre_id', Integer, ForeignKey('genres.id'))
)

allowed_mods_tags = Table('unity_allowed_mods_tags', base.metadata, # Разрешенные игрой теги для модов
    Column('game_id', Integer, ForeignKey('games.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

mods_tags = Table('unity_mods_tags', base.metadata, # Теги для игр
    Column('mod_id', Integer, ForeignKey('mods.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

mods_dependencies = Table('unity_mods_dependencies', base.metadata, # Зависимости мода
    Column('mod_id', Integer, ForeignKey('mods.id')),
    Column('dependence', Integer, ForeignKey('mods.id')),
    extend_existing=True
)


# Основные БД
class Game(base): # Таблица "игры"
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    type = Column(String(32))

    short_description = Column(String(512))
    description = Column(Text)

    mods_downloads = Column(BigInteger)
    mods_count = Column(BigInteger)

    creation_date = Column(DateTime)

    source = Column(String(64))
    source_id = Column(BigInteger, unique=True, nullable=True)

    genres = relationship('Genre', secondary=game_genres, backref='games')
    allowed_tags_for_mods = relationship('Tag', secondary=allowed_mods_tags, backref='games', viewonly=True)

class Mod(base): # Таблица "моды"
    __tablename__ = 'mods'
    id = Column(Integer, primary_key=True)
    name = Column(String(128))

    short_description = Column(String(512))
    description = Column(Text)

    size = Column(BigInteger)

    condition = Column(Integer) #0 - загружен, 1 - загружается
    public = Column(Integer) #0 - публичен, 1 - публичен, не встречается в каталоге, не индексируется, 2 - доступен с предоставлением токена

    date_creation = Column(DateTime)
    date_update_file = Column(DateTime)
    date_edit = Column(DateTime)

    source = Column(String(64))
    source_id = Column(BigInteger, unique=True, nullable=True)
    downloads = Column(BigInteger)

    tags = relationship('Tag', secondary=mods_tags, backref='mods')
    dependencies = relationship('Mod', secondary=mods_dependencies, primaryjoin=(mods_dependencies.c.mod_id == id),
        secondaryjoin=(mods_dependencies.c.dependence == id), backref='mods',
        foreign_keys=[mods_dependencies.c.mod_id, mods_dependencies.c.dependence]
    )
    game = Column(Integer, ForeignKey('games.id'))

class Resource(base): # Ресурсы (скриншоты и лого)
    __tablename__ = 'resources'
    id = Column(Integer, primary_key=True)
    type = Column(String(64))

    # Если начинается с local/, то по факту можно заменить на {config.STORAGE_URL}/(действие)/resource/...
    # При возвращении юзеру обязательно перерабатывать url в фактический (с точки зрения юзера)
    url = Column(String(512))
    @property
    def real_url(self, action='download'):
        if self.url.startswith('local/'):
            return f"{config.STORAGE_URL}/{action}/resource/{self.url.replace('local/', '')}"
        else:
            return self.url

    date_event = Column(DateTime)

    owner_type = Column(String(64)) #games, mods, etc...
    owner_id = Column(Integer)


# Теги
class Genre(base): # Жанры для игр
    __tablename__ = 'genres'
    id = Column(Integer, primary_key=True)
    name = Column(String(128))

class Tag(base): # Теги для модов
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String(128))

    associated_games = relationship('Game', secondary=allowed_mods_tags, backref='tags', viewonly=True)


base.metadata.create_all(engine)