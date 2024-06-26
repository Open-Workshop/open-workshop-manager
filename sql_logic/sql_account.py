from sqlalchemy import create_engine, Column, Integer, String, DateTime, Table, ForeignKey, Boolean, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from fastapi import Request, Response
import bcrypt
import datetime
import ow_config as config


engine = create_engine(f'mysql+mysqldb://{config.user_sql}:{config.password_sql}@{config.url_sql}/catalog')
base = declarative_base()

STANDART_STR_TIME = "%d.%m.%Y/%H:%M:%S"

class Account(base): # Аккаунты юзеров
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)

    yandex_id = Column(Integer)
    google_id = Column(String(512))

    username = Column(String(128))
    last_username_reset = Column(DateTime)

    about = Column(String(512), default="") # Ограничение 512 символов
    # если содержит "local" - обращаться к этому же серверу по id юзера, в ином случае содержит прямую ссылку, если пуст, то аватара нет
    avatar_url = Column(String(512), default="") # если "local", так же содержит после себя .расширение_файла, т.е. "local.png", "local.webp"
    grade = Column(String(128), default="")

    comments = Column(Integer, default=0)
    author_mods = Column(Integer, default=0)

    registration_date = Column(DateTime)

    password_hash = Column(String(512))
    last_password_reset = Column(DateTime)

    reputation = Column(Integer, default=0)

    ## Права пользователей
    admin = Column(Boolean, default=False) # только админ может менять грейды у всех юзеров, а так же назначать новых админов и назначать права юзерам, дает доступ ко всем правам

    write_comments = Column(Boolean, default=True) # писать и редактировать
    set_reactions = Column(Boolean, default=True)

    create_reactions = Column(Boolean, default=False)

    mute_until = Column(DateTime) # временное ограничение на все права социальными действиями на сервисе, активен если время тут больше текущего
    mute_users = Column(Boolean, default=False) # право на мут пользователей

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
    last_username_reset = Column(DateTime)
    change_about = Column(Boolean, default=True)
    change_avatar = Column(Boolean, default=True)

    vote_for_reputation = Column(Boolean, default=True)

blocked_account_creation = Table('blocked_account_creation', base.metadata,
    Column('yandex_id', Integer),
    Column('google_id', String(512)),
    Column('forget', DateTime)
)


class Session(base): # Теги для модов
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True)

    owner_id = Column(Integer)

    access_token = Column(String(512))
    refresh_token = Column(String(512))

    broken = Column(String(124)) # Сессия закрыта по причине - `logout`, `too many sessions`

    login_method = Column(String(124))

    last_request_date = Column(DateTime)
    start_date = Column(DateTime)
    end_date_access = Column(DateTime)
    end_date_refresh = Column(DateTime)

black_list = Table('black_list', base.metadata,
    Column('user_id', Integer, ForeignKey('accounts.id')),
    Column('blocked_id', Integer, ForeignKey('accounts.id')),
    Column('when', DateTime),
)

mod_and_author = Table('mods_and_authors', base.metadata,
    Column('user_id', Integer, ForeignKey('accounts.id')),
    Column('owner', Boolean), #только овнеры могут удалять свои моды, передавать овнерство другим, приглашать других на правах члена (не может удалить мод и не может приглашать новых членов)
    Column('mod_id', Integer)
)

class Forum(base): # Форумы, личные сообщения и все что угодно
    __tablename__ = 'forums'
    id = Column(Integer, primary_key=True)

    title = Column(String(124))
    description = Column(String(4096)) # Ограничение 4096 символов

    to_type = Column(String(64)) #game / mod / private_messages
    to_id = Column(Integer)
    author_id = Column(Integer)

    reputation = Column(Integer)

    creation_date = Column(DateTime)
    update_date = Column(DateTime)
    last_comment_date = Column(DateTime)

class Comment(base): # Теги для модов
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True)

    text = Column(String(8192))

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
    name = Column(String(124))
    icon_url = Column(String(512))

    creation_date = Column(DateTime)
    update_date = Column(DateTime)



async def gen_session(user_id:int, session, login_method:str = "unknown"):
    ddate = datetime.datetime.now()
    # Проверяем есть ли более 10 активных сессий
    # Если есть - аннулируем все сессии
    row = session.query(Session).filter_by(owner_id=user_id, broken=None)
    row = row.filter(Session.end_date_refresh > ddate)

    if row.count() > 9:
        row.update({"broken": "too many sessions"})


    # Генерируем псевдо-случайные токены
    access_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(6))).decode('utf-8')
    refresh_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(7))).decode('utf-8')

    # Определяем временные рамки жизни токенов
    end_access = ddate+datetime.timedelta(minutes=40)
    end_refresh = ddate+datetime.timedelta(days=60)

    # Заносим в базу
    insert_statement = insert(Session).values(
        owner_id=user_id,

        access_token=access_token,
        refresh_token=refresh_token,

        login_method=login_method,

        start_date=ddate,
        end_date_access=end_access,
        end_date_refresh=end_refresh
    )
    # Выполнение операции INSERT
    session.execute(insert_statement)

    return {"access": {"token": access_token, "end": end_access},
            "refresh": {"token": refresh_token, "end": end_refresh}}

async def update_session(response: Response, request: Request, result_row: bool = False):
    # Создание сессии
    USession = sessionmaker(bind=engine)
    session = USession()

    # Выполнение запроса
    old_refresh_token = request.cookies.get("refreshToken", "")
    row = session.query(Session).filter_by(refresh_token=old_refresh_token, broken=None)

    today = datetime.datetime.now()
    row = row.filter(Session.end_date_refresh > today)

    res = row.first()
    if res:
        access_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(6))).decode('utf-8')
        refresh_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(7))).decode('utf-8')

        end_access = today+datetime.timedelta(minutes=40)
        end_refresh = today+datetime.timedelta(days=60)

        # Обновление БД
        row.update({"end_date_access": end_access, "end_date_refresh": end_refresh,
                    "access_token": access_token, "refresh_token": refresh_token,
                    "last_request_date": today})
        session.commit()

        # Обновление данных в куки юзера
        response.set_cookie(key='accessToken', value=access_token, httponly=True, secure=True, max_age=2100)
        response.set_cookie(key='refreshToken', value=refresh_token, httponly=True, secure=True, max_age=5184000)

        response.set_cookie(key='loginJS', value=end_refresh.strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
        response.set_cookie(key='accessJS', value=end_access.strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
        response.set_cookie(key='userID', value=str(res.owner_id), secure=True, max_age=5184000)

        if result_row:
            rr = session.query(Session).filter_by(id=res.id).first().__dict__
            session.close()
            return rr
        else:
            session.close()
            return True
    session.close()
    return False

async def check_session(user_access_token:str):
    try:
        # Создание сессии
        USession = sessionmaker(bind=engine)
        session = USession()

        # Выполнение запроса
        row = session.query(Session).filter_by(access_token=user_access_token, broken=None)

        today = datetime.datetime.now()
        row = row.filter(Session.end_date_access > today)

        res = row.first()
        if res:
            res = res.__dict__
            # Обновление БД
            row.update({"last_request_date": today})
            session.commit()
            session.close()

            return res

        session.close()
        return False
    except:
        return False

async def forget_accounts():
    # Создание сессии
    USession = sessionmaker(bind=engine)
    session = USession()

    # Выполнение запроса
    delete_member = blocked_account_creation.delete().where(blocked_account_creation.c.forget < datetime.datetime.now())

    # Выполнение операции DELETE
    session.execute(delete_member)
    session.commit()
    session.close()

async def check_access(response: Response, request: Request):
    await forget_accounts()
    if "accessToken" in request.cookies:
        access = await check_session(request.cookies.get("accessToken", ""))
        if access: return access
    if "refreshToken" in request.cookies:
        refresh = await update_session(response=response, request=request, result_row=True)
        if refresh: return refresh
    return False


async def no_from_russia(request: Request):
    russia_cookie = request.cookies.get("fromRussia", "false")

    if russia_cookie == "true":
        return "Вы должны выбрать российский сервис авторизации согласно законодательству РФ!"

    return False

base.metadata.create_all(engine)