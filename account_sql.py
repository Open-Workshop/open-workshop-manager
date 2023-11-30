from sqlalchemy import create_engine, Column, Integer, String, DateTime, Table, ForeignKey, Boolean, insert
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import bcrypt
import datetime


engine = create_engine('sqlite:///accounts/account.db')
base = declarative_base()



class Account(base): # Аккаунты юзеров
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)

    yandex_id = Column(Integer)

    email = Column(String)

    username = Column(String)
    last_username_reset = Column(DateTime)

    about = Column(String, default="") # Ограничение 512 символов
    avatar_url = Column(String, default="")
    grade = Column(String, default="")

    comments = Column(Integer)
    author_mods = Column(Integer)

    registration_date = Column(DateTime)

    password_hash = Column(String)
    last_password_reset = Column(DateTime)

    reputation = Column(Integer)

    ## Права пользователей
    admin = Column(Boolean, default=False) # только админ может менять грейды у всех юзеров, а так же назначать новых админов и назначать права юзерам, дает доступ ко всем правам

    write_comments = Column(Boolean, default=True) # писать и редактировать
    set_reactions = Column(Boolean, default=True)

    create_reactions = Column(Boolean, default=False)

    mute_until = Column(DateTime) # временное ограничение на все права социальными действиями на сайте, активен если время тут больше текущего

    publish_mods = Column(Boolean, default=True)
    change_authorship_mods = Column(Boolean, default=False)
    change_self_mods = Column(Boolean, default=True)
    change_mods = Column(Boolean, default=False)
    delete_self_mods = Column(Boolean, default=True)
    delete_mods = Column(Boolean, default=False)

    create_forums = Column(Boolean, default=True)
    change_authorship_forums = Column(Boolean, default=False)
    change_self_forums = Column(Boolean, default=True)
    change_forums = Column(Boolean, default=False)
    delete_self_forums = Column(Boolean, default=True)
    delete_forums = Column(Boolean, default=False)

    change_username = Column(Boolean, default=True)
    change_about = Column(Boolean, default=True)
    change_avatar = Column(Boolean, default=True)

    vote_for_reputation = Column(Boolean, default=True)

class Session(base): # Теги для модов
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True)

    owner_id = Column(Integer)

    access_token = Column(String)
    refresh_token = Column(String)

    broken = Column(String) # Сессия закрыта по причине - `logout`, `too many sessions`

    ip = Column(String)

    login_method = Column(String)

    last_request_date = Column(DateTime)
    start_date = Column(DateTime)
    end_date_access = Column(DateTime)
    end_date_refresh = Column(DateTime)

black_list = Table('black_list', base.metadata,
    Column('user_id', Integer, ForeignKey('accounts.id')),
    Column('blocked_id', Integer, ForeignKey('accounts.id')),
    Column('when', DateTime),
)

mod = Table('mods', base.metadata,
    Column('user_id', Integer, ForeignKey('accounts.id')),
    Column('mod_id', Integer)
)

class Forum(base): # Форумы, личные сообщения и все что угодно
    __tablename__ = 'forums'
    id = Column(Integer, primary_key=True)

    title = Column(String)
    description = Column(String) # Ограничение 512 символов

    to_type = Column(String) #game / mod / private_messages
    to_id = Column(Integer)
    author_id = Column(Integer)

    reputation = Column(Integer)

    creation_date = Column(DateTime)
    update_date = Column(DateTime)
    last_comment_date = Column(DateTime)

class Comment(base): # Теги для модов
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True)

    text = Column(String)

    forum_id = Column(Integer)
    reply_id = Column(Integer)
    author_id = Column(Integer)

    creation_date = Column(DateTime)
    update_date = Column(DateTime)

    reputation = Column(Integer)

comments_reactions = Table('unity_comments_reactions', base.metadata,
    Column('comment_id', Integer, ForeignKey('comments.id')),
    Column('user_id', Integer, ForeignKey('accounts.id')),
    Column('reaction_id', Integer, ForeignKey('reactions.id')),
    Column('when', DateTime)
)

class Reaction(base): # Жанры для игр
    __tablename__ = 'reactions'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    icon_url = Column(String)

    creation_date = Column(DateTime)
    update_date = Column(DateTime)


async def gen_session(user_id:int, session, ip:str = "unknown", login_method:str = "unknown"):
    #TODO проверяем есть ли более 5 активных сессий
    #Если есть - аннулируем все сессии

    # Генерируем псевдо-случайные токены
    access_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(6))).decode('utf-8')
    refresh_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(8))).decode('utf-8')

    # Определяем временные рамки жизни токенов
    ddate = datetime.datetime.now()
    end_access = ddate+datetime.timedelta(minutes=40)
    end_refresh = ddate+datetime.timedelta(days=60)

    # Заносим в базу
    insert_statement = insert(Session).values(
        owner_id=user_id,

        access_token=access_token,
        refresh_token=refresh_token,

        ip=ip,
        login_method=login_method,

        start_date=ddate,
        end_date_access=end_access,
        end_date_refresh=end_refresh
    )
    # Выполнение операции INSERT
    session.execute(insert_statement)

    return {"access": {"token": access_token, "end": end_access},
            "refresh": {"token": refresh_token, "end": end_refresh}}


base.metadata.create_all(engine)