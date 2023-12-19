from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert
import account_sql as account
import ow_config as config
from yandexid import AsyncYandexOAuth, AsyncYandexID
import datetime
import bcrypt
import aiohttp
from PIL import Image
from io import BytesIO
import os
import re


SERVER_ADDRESS = "http://127.0.0.1:8000"
MAIN_URL = "/api/accounts"
STANDART_STR_TIME = account.STANDART_STR_TIME



yandex_oauth = AsyncYandexOAuth(
    client_id=config.yandex_client_id,
    client_secret=config.yandex_client_secret,
    redirect_uri='https://openworkshop.su'+MAIN_URL+'/authorization/yandex/complite'
)


app = FastAPI(
    title="Open Workshop Accounts",
    docs_url=MAIN_URL,
    openapi_url=MAIN_URL+"/openapi.json",
    contact={
        "name": "GitHub",
        "url": "https://github.com/Open-Workshop/open-workshop-accounts"
    },
    license_info={
        "name": "MPL-2.0 license",
        "identifier": "MPL-2.0",
    },
)


@app.get("/")
async def main_redirect():
    """
    Переадресация на документацию.
    """
    return RedirectResponse(url=MAIN_URL)

@app.get(MAIN_URL+"/authorization/yandex/link")
async def yandex_send_link():
    """
    Получение ссылки на авторизацию через YandexID
    """
    return RedirectResponse(url=yandex_oauth.get_authorization_url())

@app.post(MAIN_URL+"/authorization/password")
async def password_authorization(response: Response, login: str, password: str):
    """
    Авторизация в систему через пароль. Не очень безопасный метод :)
    """
    # Создание сессии
    USession = sessionmaker(bind=account.engine)
    session = USession()

    # Получаем запись о юзере
    user_query = session.query(account.Account.id, account.Account.password_hash).filter_by(username=login)
    user = user_query.first()


    if user and user.password_hash is not None and len(user.password_hash) > 1 and \
            bcrypt.checkpw(password=password.encode('utf-8'), hashed_password=user.password_hash.encode('utf-8')):
        sessions_data = await account.gen_session(user_id=user.id, session=session, login_method="password")

        response.set_cookie(key='accessToken', value=sessions_data["access"]["token"], httponly=True, secure=True,
                            max_age=2100)
        response.set_cookie(key='refreshToken', value=sessions_data["refresh"]["token"], httponly=True, secure=True,
                            max_age=5184000)

        response.set_cookie(key='loginJS', value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME),
                            secure=True, max_age=5184000)
        response.set_cookie(key='accessJS', value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME),
                            secure=True, max_age=5184000)
        response.set_cookie(key='userID', value=user.id, secure=True, max_age=5184000)

        session.commit()
        session.close()

        return True

    session.close()
    return JSONResponse(status_code=412, content=False)

@app.get(MAIN_URL+"/authorization/yandex/complite", response_class=HTMLResponse)
async def yandex_complite(response: Response, code:int):
    """
    Авторизация в систему через YandexID
    """
    token = await yandex_oauth.get_token_from_code(code)
    user_data = await AsyncYandexID(oauth_token=token.access_token).get_user_info_json()

    # Создание сессии
    Session = sessionmaker(bind=account.engine)

    # Выполнение запроса
    session = Session()
    rows = session.query(account.Account.id).filter(account.Account.yandex_id == user_data.id).first()

    if not rows:
        dtime = datetime.datetime.now()
        print(dtime, type(dtime))
        insert_statement = insert(account.Account).values(
            yandex_id=user_data.id,

            username=user_data.login,

            email=user_data.default_email,

            comments=0,
            author_mods=0,

            registration_date=dtime,

            reputation=0
        ).returning(account.Account.id)
        # Выполнение операции INSERT
        result = session.execute(insert_statement)
        id = result.fetchone()[0]  # Получаем значение `id` созданного элемента

        if not user_data.is_avatar_empty:
            session.commit()
            session.close()
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://avatars.yandex.net/get-yapic/{user_data.default_avatar_id}/islands-200") as resp:
                    if resp.status == 200:
                        # Сохраняем изображение
                        # Чтение и конвертация изображения
                        img = Image.open(BytesIO(await resp.read()))

                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")

                        img.save(f"accounts_avatars/{str(id)}.jpeg", "JPEG", quality=50)

                        # Помечаем в БД пользователя, что у него есть аватар
                        session = Session()
                        session.query(account.Account).filter(account.Account.id == id).update({"avatar_url": "local"})
                    else:
                        session = Session()
                        print("Яндекс регистрация: во время сохранения изображения произошла ошибка!")
    else:
        id = rows.id

    sessions_data = await account.gen_session(user_id=id, session=session, login_method="yandex")

    session.commit()
    session.close()

    response.set_cookie(key='accessToken', value=sessions_data["access"]["token"], httponly=True, secure=True, max_age=2100)
    response.set_cookie(key='refreshToken', value=sessions_data["refresh"]["token"], httponly=True, secure=True, max_age=5184000)

    response.set_cookie(key='loginJS', value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
    response.set_cookie(key='accessJS', value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
    response.set_cookie(key='userID', value=id, secure=True, max_age=5184000)

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"

@app.post(MAIN_URL+"/authorization/refresh")
async def refresh(response: Response, request: Request):
    """
    Получение новой пары access+refresh токенов на основе еще живого refresh токена
    """
    return bool(await account.update_session(response=response, request=request))

@app.post(MAIN_URL+"/authorization/logout")
async def logout(response: Response, request: Request):
    """
    Выход из системы.
    Удаляет аккаунт-куки у пользователя, а так же убивает сессию (соответсвующее токены становятся невалидными)!
    """

    # Создание сессии
    Session = sessionmaker(bind=account.engine)

    # Выполнение запроса
    session = Session()
    session.query(account.Session).filter_by(access_token=request.cookies.get("accessToken", "")).update(
        {"broken": "logout"})
    session.commit()
    session.close()

    # Удаление токенов у юзера
    response.delete_cookie(key='accessToken')
    response.delete_cookie(key='refreshToken')
    response.delete_cookie(key='loginJS')
    response.delete_cookie(key='accessJS')
    response.delete_cookie(key='userID')

    return True


@app.get(MAIN_URL+"/profile/info/{user_id}")
async def info_profile(response: Response, request: Request, user_id:int, general:bool = True, rights:bool = False, private:bool = False):
    """
    Возвращает информацию о пользователях.

    `general` - могут просматривать все.
    `rights` - исключительно админы и сам пользователь.
    `private` - исключительно админы и сам пользователь.
    """
    result = {}
    # Создание сессии
    USession = sessionmaker(bind=account.engine)
    session = USession()

    query = session.query(account.Account).filter_by(id=user_id)
    row = query.first()
    if not row:
        session.close()
        return JSONResponse(status_code=404, content="Пользователь не найден(")

    if rights or private:
        # Чекаем сессию юзера
        print(request.cookies.get("accessToken", ""))
        access_result = await account.check_access(request=request, response=response)

        # Смотрим действительна ли она (сессия)
        if access_result and access_result.get("owner_id", -1) >= 0:
            owner_id = access_result.get("owner_id", -1) # id юзера запрашивающего данные

            if user_id != owner_id: # Доп проверка если запрос делает не сам пользователь "про себя"
                query = session.query(account.Account.admin).filter_by(id=owner_id)
                owner_row = query.first()

                if not owner_row.admin:
                    session.close()
                    return JSONResponse(status_code=403, content="Вы не имеете доступа к этой информации!")

            if private:
                result["private"] = {}
                result["private"]["last_username_reset"] = row.last_username_reset
                result["private"]["last_password_reset"] = row.last_password_reset
                result["private"]["email"] = row.email

            if rights:
                result["rights"] = {}
                result["rights"]["admin"] = row.admin
                result["rights"]["write_comments"] = row.write_comments
                result["rights"]["set_reactions"] = row.set_reactions
                result["rights"]["create_reactions"] = row.create_reactions
                result["rights"]["publish_mods"] = row.publish_mods
                result["rights"]["change_authorship_mods"] = row.change_authorship_mods
                result["rights"]["change_self_mods"] = row.change_self_mods
                result["rights"]["change_mods"] = row.change_mods
                result["rights"]["delete_self_mods"] = row.admin
                result["rights"]["delete_mods"] = row.delete_mods
                result["rights"]["mute_users"] = row.mute_users
                result["rights"]["create_forums"] = row.create_forums
                result["rights"]["change_authorship_forums"] = row.change_authorship_forums
                result["rights"]["change_self_forumss"] = row.change_self_forums
                result["rights"]["change_forums"] = row.change_forums
                result["rights"]["delete_self_forums"] = row.delete_self_forums
                result["rights"]["delete_forums"] = row.delete_forums
                result["rights"]["change_username"] = row.change_username
                result["rights"]["change_about"] = row.change_about
                result["rights"]["change_avatar"] = row.change_avatar
                result["rights"]["vote_for_reputation"] = row.vote_for_reputation
        else:
            session.close()
            return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

    if general:
        result["general"] = {}
        result["general"]["id"] = row.id
        result["general"]["username"] = row.username
        result["general"]["about"] = row.about
        result["general"]["avatar_url"] = row.avatar_url
        result["general"]["grade"] = row.grade
        result["general"]["comments"] = row.comments
        result["general"]["author_mods"] = row.author_mods
        result["general"]["registration_date"] = row.registration_date
        result["general"]["reputation"] = row.reputation
        result["general"]["mute"] = row.mute_until if row.mute_until and row.mute_until > datetime.datetime.now() else False # есть ли мут, если да, то до какого времени действует

    session.close()
    return result

@app.post(MAIN_URL+"/profile/edit/{user_id}")
async def edit_profile(response: Response, request: Request, user_id: int, email: str = None, username: str = None,
                       about: str = None, avatar: UploadFile = None, empty_avatar: bool = None, grade: str = None,
                       off_password:bool = None, new_password: str = None, mute: datetime.datetime = None):
    """
    Редактирование пользователей *(самого себя или другого юзера)*.
    """
    try:
        global STANDART_STR_TIME

        access_result = await account.check_access(request=request, response=response)

        # Смотрим действительна ли она (сессия)
        if access_result and access_result.get("owner_id", -1) >= 0:
            owner_id = access_result.get("owner_id", -1) # id юзера запрашивающего данные

            # Создание сессии
            USession = sessionmaker(bind=account.engine)
            session = USession()

            # Получаем запись о юзере
            user_query = session.query(account.Account).filter_by(id=user_id)
            user = user_query.first()

            # Проверка, существует ли пользователь
            if not user:
                session.close()
                return JSONResponse(status_code=404, content="Пользователь не найден!")


            try:
                today = datetime.datetime.now()
                # Проверка, может ли просящий выполнить такую операцию
                query = session.query(account.Account).filter_by(id=owner_id)
                row = query.first()
                if owner_id != user_id:
                    if not row.admin:
                        # Перебираем все запрещенные поля и убеждаемся, что их изменить не пытаются
                        for i in [email, username, about, avatar, empty_avatar, grade, off_password, new_password]:
                            if i is not None:
                                session.close()
                                return JSONResponse(status_code=403, content="Доступ запрещен!")
                        else:
                            # Проверяем, есть ли у запрашивающего право мутить других пользователей и пытается ли он замутить
                            if not row.mute_users or mute is None: #разрешено ли мутить, пытается ли замутить
                                session.close()
                                return JSONResponse(status_code=403, content="Доступ запрещен!")
                    elif new_password is not None or off_password is not None:
                        session.close()
                        return JSONResponse(status_code=403, content="Даже администраторы не могут менять пароли!")
                else:
                    if mute is not None:
                        session.close()
                        return JSONResponse(status_code=400, content="Нельзя замутить самого себя!")
                    elif not row.admin: # Админы могут менять свои пароли и имена пользователей без ограничений
                        if row.mute_until and row.mute_until > today: # Даже если админ замутен, то на него ограничение не распространяется
                            session.close()
                            return JSONResponse(status_code=425, content="Вам выдано временное ограничение на социальную активность :(")

                        if grade is not None:
                            session.close()
                            return JSONResponse(status_code=403, content="Не админ не может менять грейды!")

                        if new_password is not None and row.last_password_reset and row.last_password_reset+datetime.timedelta(minutes=5) > today:
                            session.close()
                            return JSONResponse(status_code=425, content=(row.last_password_reset+datetime.timedelta(minutes=5)).strftime(STANDART_STR_TIME))
                        if username is not None:
                            if not row.change_username:
                                session.close()
                                return JSONResponse(status_code=403, content="Вам по какой-то причине запрещено менять никнейм!")
                            elif row.last_username_reset and (row.last_username_reset + datetime.timedelta(days=30)) > today:
                                session.close()
                                return JSONResponse(status_code=425, content=(row.last_username_reset+datetime.timedelta(days=30)).strftime(STANDART_STR_TIME))
                        if avatar is not None or empty_avatar is not None:
                            if not row.change_avatar:
                                session.close()
                                return JSONResponse(status_code=403, content="Вам по какой-то причине запрещено менять аватар!")
                        if about is not None:
                            if not row.change_about:
                                session.close()
                                return JSONResponse(status_code=403, content="Вам по какой-то причине запрещено менять \"обо мне\"!")
            except:
                session.close()
                return JSONResponse(status_code=500, content='Что-то пошло не так при проверке ваших прав...')


            # Подготавливаемся к выполнению операции и смотрим чтобы переданные данные были корректны
            query_update = {}

            try:
                try:
                    if email:
                        if not bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", email)):
                            session.close()
                            return JSONResponse(status_code=400, content="Некорректный электронный адрес!")
                        elif len(email) > 512:
                            session.close()
                            return JSONResponse(status_code=413, content="Слишком длинный электронный адрес!")

                        query_update["email"] = email
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (email) на обновление БД...')
                
                try:
                    if username:
                        if len(username) < 2:
                            session.close()
                            return JSONResponse(status_code=411, content="Слишком короткий никнейм! (минимальная длина 2 символа)")
                        elif len(username) > 50:
                            session.close()
                            return JSONResponse(status_code=413, content="Слишком длинный никнейм! (максимальная длина 50 символов)")

                        query_update["username"] = username
                        query_update["last_username_reset"] = today
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (username) на обновление БД...')
                
                try:
                    if about:
                        if len(about) > 512:
                            session.close()
                            return JSONResponse(status_code=413, content="Слишком длинное поле \"обо мне\"! (максимальная длина 512 символов)")

                        query_update["about"] = about
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (about) на обновление БД...')
                        
                try:
                    if grade:
                        if len(grade) < 2:
                            session.close()
                            return JSONResponse(status_code=411, content="Слишком короткий грейд! (минимальная длина 2 символа)")
                        elif len(grade) > 100:
                            session.close()
                            return JSONResponse(status_code=413, content="Слишком длинный грейд! (максимальная длина 100 символов)")

                        query_update["grade"] = grade
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (grade) на обновление БД...')

                try:
                    if off_password:
                        query_update["password_hash"] = None
                        query_update["last_password_reset"] = today
                    elif new_password:
                        if len(new_password) < 6:
                            session.close()
                            return JSONResponse(status_code=411, content="Слишком короткий пароль! (минимальная длина 6 символа)")
                        elif len(new_password) > 100:
                            session.close()
                            return JSONResponse(status_code=413, content="Слишком длинный пароль! (максимальная длина 100 символов)")

                        query_update["password_hash"] = (bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt(9))).decode('utf-8')
                        query_update["last_password_reset"] = today
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (password) на обновление БД...')

                try:
                    if mute:
                        if mute < today:
                            session.close()
                            return JSONResponse(status_code=411, content="Указанная дата окончания мута уже прошла!")

                        query_update["mute_until"] = mute
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (mute) на обновление БД...')

                try:
                    if empty_avatar:

                        query_update["avatar_url"] = ""

                        image_avatar = f"accounts_avatars/{user_id}.jpeg"
                        if os.path.isfile(image_avatar):
                            os.remove(image_avatar)
                    elif avatar is not None: # Проверка на аватар в самом конце, т.к. он приводит к изменениям в файловой системе
                        query_update["avatar_url"] = "local"

                        if avatar.size >= 2097152:
                            session.close()
                            return JSONResponse(status_code=413, content="Вес аватара не должен превышать 2 МБ.")

                        try:
                            im = Image.open(BytesIO(await avatar.read()))
                            if im.mode in ("RGBA", "P"):
                                im = im.convert("RGB")
                            im.save(f'accounts_avatars/{user_id}.jpeg', 'JPEG', quality=50)
                        except:
                            await avatar.close()
                            session.close()
                            return JSONResponse(status_code=500, content="Что-то пошло не так при обработке аватара ._.")
                except:
                    session.close()
                    return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных (avatar) на обновление БД...')
            except:
                return JSONResponse(status_code=500, content='Что-то пошло не так при подготовке данных на обновление БД...')


            # Выполняем запрошенную операцию
            user_query.update(query_update)
            session.commit()
            session.close()


            # Возвращаем успешный результат
            return JSONResponse(status_code=202, content='Изменения приняты :)')
        else:
            return JSONResponse(status_code=403, content="Недействительный ключ сессии!")
    except:
        session.close()
        return JSONResponse(status_code=500, content='В огромной функции произошла неизвестная ошибка...')


@app.get(MAIN_URL+"/profile/avatar/{user_id}")
async def avatar_profile(user_id:int):
    """
    Возвращает аватары пользователей при условии, что они есть.
    """
    image_path = f"accounts_avatars/{user_id}.jpeg"
    if os.path.exists(image_path):
        return FileResponse(path=image_path)
    return JSONResponse(status_code=404, content="File not found! :(")


@app.get(MAIN_URL+"/info/mod/{mod_id}")
async def info_mod():
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/resources_mods/{mods_list_id}")
async def list_resources_for_mods():
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/tags/mods/{mods_ids_list}")
async def list_tags_for_mods():
    """
    Тестовая функция
    """
    return 0


@app.get(MAIN_URL+"/list/forum/")
async def list_forums():
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/comment/{forum_id}")
async def list_comment(forum_id: int):
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/reaction/")
async def list_reaction():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/edit/profile/rights")
async def edit_profile_rights():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/add/game")
async def add_game():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/add/genre")
async def add_genre():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/add/tag")
async def add_tag():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/add/resource")
async def add_resource():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/add/mod")
async def add_mod():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/edit/game")
async def edit_game():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/genre")
async def edit_genre():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/tag")
async def edit_tag():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/resource")
async def edit_resource():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/mod")
async def edit_mod():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/delete/game")
async def delete_game():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/genre")
async def delete_genre():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/tag")
async def delete_tag():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/resource")
async def delete_resource():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/mod")
async def delete_mod():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/association/game/genre")
async def association_game_with_genre():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/association/game/tag")
async def association_game_with_tag():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/association/mod/tag")
async def association_mod_with_tag():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/association/mod/dependencie")
async def association_mod_with_dependencie():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/add/forum")
async def add_forum():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/forum")
async def edit_forum():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/reputation/forum")
async def reputation_forum():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/forum")
async def delete_forum():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/add/forum/comment")
async def add_forum_comment():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/forum/comment")
async def edit_forum_comment():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/reputation/forum/comment")
async def reputation_forum_comment():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/reaction/forum/comment")
async def reaction_forum_comment():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/forum/comment")
async def delete_forum_comment():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/add/reaction")
async def add_reaction():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/edit/reaction")
async def edit_reaction():
    """
    Тестовая функция
    """
    return 0

@app.post(MAIN_URL+"/delete/reaction")
async def delete_reaction():
    """
    Тестовая функция
    """
    return 0


@app.post(MAIN_URL+"/list/black/set")
async def black_list():
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/black/get")
async def black_list():
    """
    Тестовая функция
    """
    return 0

@app.get(MAIN_URL+"/list/black/in/{user_id}") # состою ли в ЧС у определенного юзера
async def black_list(user_id):
    """
    Тестовая функция
    """
    return 0
