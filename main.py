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
import tools
from PIL import Image
from io import BytesIO
import os
from google_auth_oauthlib.flow import Flow
import json
import urllib
import random
import string
import io


SERVER_ADDRESS = "http://127.0.0.1:8000"
MAIN_URL = "/api/accounts"
STANDART_STR_TIME = account.STANDART_STR_TIME



# Создаем объект Flow
with open('credentials.json', 'r') as config_file:
    google_config = json.load(config_file)
data = {
    'client_id': google_config["web"]["client_id"],
    'client_secret': google_config["web"]["client_secret"],
    'redirect_uri': google_config["web"]["redirect_uris"][0],
    'grant_type': 'authorization_code'
}
flow = Flow.from_client_config(
    google_config,
    scopes=['openid', 'profile'],
    redirect_uri=google_config["web"]["redirect_uris"][0]
)
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


@app.get(MAIN_URL+"/test/test")
async def test_test(request: Request):
    """
    Тестовая функция :)
    """
    my_header = request.headers.get('x-real-ip')
    return {"real-ip": my_header, "ip": request.client.host}

@app.get("/")
async def main_redirect():
    """
    Переадресация на документацию.
    """
    return RedirectResponse(url=MAIN_URL)

@app.get(MAIN_URL+"/authorization/google/link", response_class=HTMLResponse)
async def google_send_link(request: Request):
    """
    Получение ссылки на авторизацию через Google
    """
    ru = await account.no_from_russia(request=request)
    if ru: return ru

    authorization_url, state = flow.authorization_url()
    return RedirectResponse(url=authorization_url)

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

@app.get(MAIN_URL+"/authorization/google/complite", response_class=HTMLResponse)
async def google_complite(response: Response, request: Request, code:str, _state:str = "", _scope:str = "",
                          _authuser:int = -1, _prompt:str = ""):
    """
    Авторизация в систему через Google.

    Если данный аккаунт не привязан ни к одному из аккаунтов OW и при этом передать access_token то произойдет коннект.
    """
    ru = await account.no_from_russia(request=request)
    if ru: return ru

    async with aiohttp.ClientSession() as session:
        data_complite = data.copy()
        data_complite["code"] = urllib.parse.unquote(code)

        async with session.post('https://oauth2.googleapis.com/token', data=data_complite) as token_response:
            google_access = await token_response.json()
            print(google_access)

            async with session.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={
                'Authorization': f'Bearer {google_access["access_token"]}'}) as user_info_response:
                user_data = await user_info_response.json()


    # Создание сессии
    Session = sessionmaker(bind=account.engine)

    # Выполнение запроса
    session = Session()
    rows = session.query(account.Account.id).filter(account.Account.google_id == user_data["id"]).first()

    if not rows:
        access_result = await account.check_access(request=request, response=response)

        if access_result and access_result.get("owner_id", -1) >= 0:
            row_connect = session.query(account.Account).filter_by(google_id=None, id=access_result.get("owner_id", -1))
            row_connect_result = row_connect.first()

            if row_connect_result:
                row_connect.update({"google_id": user_data["id"]})
                session.commit()
                id = row_connect_result.id
            else:
                session.close()
                return JSONResponse(status_code=400, content="Пользователь привязанный за токеном не найден, или к его аккаунту уже подключен Google ID")
        else:
            dtime = datetime.datetime.now()

            async def generate_unique_username():
                prefix = "OW user "
                suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                return prefix + suffix

            print(dtime, type(dtime))
            insert_statement = insert(account.Account).values(
                google_id=user_data["id"],

                username=await generate_unique_username(),

                comments=0,
                author_mods=0,

                registration_date=dtime,

                reputation=0
            ).returning(account.Account.id)
            # Выполнение операции INSERT
            result = session.execute(insert_statement)
            id = result.fetchone()[0]  # Получаем значение `id` созданного элемента

            if len(user_data.get("picture", "")) > 0:
                session.commit()
                session.close()
                async with aiohttp.ClientSession() as session:
                    async with session.get(user_data["picture"]) as resp:
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
                            print("Google регистрация: во время сохранения изображения произошла ошибка!")
    else:
        id = rows.id

    sessions_data = await account.gen_session(user_id=id, session=session, login_method="google")

    session.commit()
    session.close()

    response.set_cookie(key='accessToken', value=sessions_data["access"]["token"], httponly=True, secure=True,
                        max_age=2100)
    response.set_cookie(key='refreshToken', value=sessions_data["refresh"]["token"], httponly=True, secure=True,
                        max_age=5184000)

    response.set_cookie(key='loginJS', value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME), secure=True,
                        max_age=5184000)
    response.set_cookie(key='accessJS', value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME), secure=True,
                        max_age=5184000)
    response.set_cookie(key='userID', value=id, secure=True, max_age=5184000)

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"

@app.get(MAIN_URL+"/authorization/yandex/complite", response_class=HTMLResponse)
async def yandex_complite(response: Response, request: Request, code:int):
    """
    Авторизация в систему через YandexID.

    Если данный аккаунт не привязан ни к одному из аккаунтов OW и при этом передать access_token то произойдет коннект.
    """
    token = await yandex_oauth.get_token_from_code(code)
    user_data = await AsyncYandexID(oauth_token=token.access_token).get_user_info_json()

    # Создание сессии
    Session = sessionmaker(bind=account.engine)

    # Выполнение запроса
    session = Session()
    rows = session.query(account.Account.id).filter(account.Account.yandex_id == user_data.id).first()

    if not rows:
        access_result = await account.check_access(request=request, response=response)

        if access_result and access_result.get("owner_id", -1) >= 0:
            row_connect = session.query(account.Account).filter_by(yandex_id=None, id=access_result.get("owner_id", -1))
            row_connect_result = row_connect.first()

            if row_connect_result:
                row_connect.update({"yandex_id": user_data.id})
                session.commit()
                id = row_connect_result.id
            else:
                session.close()
                return JSONResponse(status_code=400, content="Пользователь привязанный за токеном не найден, или к его аккаунту уже подключен Yandex ID")
        else:
            dtime = datetime.datetime.now()
            print(dtime, type(dtime))
            insert_statement = insert(account.Account).values(
                yandex_id=user_data.id,

                username=user_data.login,

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

@app.get(MAIN_URL+"/authorization/disconnect")
async def disconnect_service(response: Response, request: Request, service_name: str):
    """
    Отвязываем один из сервисов от аккаунта, при этом OW не допустит чтобы от аккаунта были отвязаны все сервисы.

    `service_name` - доступные параметры: `google`, `yandex`
    """
    services = ["google", "yandex"]

    if service_name not in services:
        return JSONResponse(status_code=400, content="Недопустимое значение service_name!")

    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)

        # Выполнение запроса
        session = Session()
        row = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1))
        row_result = row.first()
        if row_result:
            if row_result.yandex_id and row_result.google_id:
                row.update({service_name+"_id": None})

                session.commit()
                session.close()

                return JSONResponse(status_code=200, content="Успешно!")
            else:
                session.close()
                return JSONResponse(status_code=406, content="Нельзя отсоединить все сервисы от аккаунта!")
        else:
            session.close()
            return JSONResponse(status_code=404, content="Пользователь не найден!")
    else:
        return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

@app.get(MAIN_URL+"/authorization/delete")
async def delete_account(response: Response, request: Request):
    """
    Удаление аккаунта. Сделать это может только сам пользователь, при этом удаляются только персональные данные пользователя.
    Т.е. - аватар, никнейм, "обо мне", электронный адрес, ассоциация с сервисами авторизации, текста комментариев.
    "следы" такие, как история сессий, комментарии (сохраняется факт их наличия, содержимое удаляется) и т.п..
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)

        # Выполнение запроса
        session = Session()

        user_id = access_result.get("owner_id", -1)

        session.query(account.Account).filter_by(id=user_id).update({
            "yandex_id": None,
            "google_id": None,
            "username": None,
            "about": None,
            "avatar_url": None,
            "grade": None,
            "password_hash": None
        })
        session.query(account.Session).filter_by(owner_id=user_id).update({
            "broken": "account deleted",
        })

        session.commit()
        session.close()

        return JSONResponse(status_code=200, content="Успешно!")
    else:
        return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

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
                result["private"]["yandex"] = bool(row.yandex_id)
                result["private"]["google"] = bool(row.google_id)

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
                result["rights"]["change_self_forums"] = row.change_self_forums
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
async def edit_profile(response: Response, request: Request, user_id: int, username: str = None,
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
                        for i in [username, about, avatar, empty_avatar, grade, off_password, new_password]:
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

@app.post(MAIN_URL+"/edit/profile/rights")
async def edit_profile_rights(response: Response, request: Request, user_id:int, write_comments: bool = None,
                              set_reactions: bool = None, create_reactions: bool = None, mute_users: bool = None,
                              publish_mods: bool = None, change_authorship_mods: bool = None,
                              change_self_mods: bool = None, change_mods: bool = None, delete_self_mods: bool = None,
                              delete_mods: bool = None, create_forums: bool = None,
                              change_authorship_forums: bool = None, change_self_forums: bool = None,
                              change_forums: bool = None, delete_self_forums: bool = None, delete_forums: bool = None,
                              change_username: bool = None, change_about: bool = None, change_avatar: bool = None,
                              vote_for_reputation: bool = None):
    """
    Функция для изменения прав пользователей
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0: # авторизован ли юзер в системе
        owner_id = access_result.get("owner_id", -1)  # id юзера запрашивающего изменения

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


        # Проверка, может ли просящий выполнить такую операцию
        query = session.query(account.Account).filter_by(id=owner_id)
        row = query.first()
        if not row.admin:
            session.close()
            return JSONResponse(status_code=403, content="Только админ может менять права!")


        # Подготавливаемся к выполнению операции и смотрим чтобы переданные данные были корректны
        sample_query_update = {
            "write_comments": write_comments,
            "set_reactions": set_reactions,
            "create_reactions": create_reactions,
            "mute_users": mute_users,
            "publish_mods": publish_mods,
            "change_authorship_mods": change_authorship_mods,
            "change_self_mods": change_self_mods,
            "change_mods": change_mods,
            "delete_self_mods": delete_self_mods,
            "delete_mods": delete_mods,
            "create_forums": create_forums,
            "change_authorship_forums": change_authorship_forums,
            "change_self_forums": change_self_forums,
            "change_forums": change_forums,
            "delete_self_forums": delete_self_forums,
            "delete_forums": delete_forums,
            "change_username": change_username,
            "change_about": change_about,
            "change_avatar": change_avatar,
            "vote_for_reputation": vote_for_reputation
        }

        query_update = {}
        for key in sample_query_update.keys():
            if sample_query_update[key] is not None:
                query_update[key] = sample_query_update[key]


        # Выполняем запрошенную операцию
        user_query.update(query_update)
        session.commit()
        session.close()

        # Возвращаем успешный результат
        return JSONResponse(status_code=202, content='Изменения приняты :)')
    else:
        return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

@app.get(MAIN_URL+"/profile/avatar/{user_id}")
async def avatar_profile(user_id:int):
    """
    Возвращает аватары пользователей при условии, что они есть.
    """
    image_path = f"accounts_avatars/{user_id}.jpeg"
    if os.path.exists(image_path):
        return FileResponse(path=image_path)
    return JSONResponse(status_code=404, content="File not found! :(")

@app.get(MAIN_URL+"/list/mods/{user_id}")
async def list_mods(response: Response, request: Request, user_id:int, page:int = 0, page_size:int = 30,
                    public:bool = True):
    """
    Тестовая функция
    """
    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})
    elif page < 0:
        return JSONResponse(status_code=413, content={"message": "incorrect page", "error_id": 2})

    if not public:
        access_result = await account.check_access(request=request, response=response)

        if not access_result or access_result.get("owner_id", -1) < 0:
            return JSONResponse(status_code=401, content="Недействительный ключ сессии!")


    # Создание сессии
    Session = sessionmaker(bind=account.engine)
    session = Session()

    if not public and user_id != access_result.get("owner_id", -1):
        # Выполнение запроса
        row = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1))
        row_result = row.first()
        if not row_result or not row_result.admin:
            session.close()
            return JSONResponse(status_code=403, content="Вы не имеете доступа к этой информации!")

    offset = page_size * page
    row = session.query(account.mod_and_author).filter_by(user_id=user_id).offset(offset).limit(page_size).all()

    row_list_ids = []
    row_result = {}
    for i in row:
        row_list_ids.append(i.mod_id)
        row_result[i.mod_id] = i.owner

    if len(row_result) <= 0:
        session.close()
        return {}

    async with aiohttp.ClientSession() as session:
        url = SERVER_ADDRESS + f'/public/mod/{str(row_list_ids)}?catalog=true'
        print(url)
        async with session.get(url=url) as ioresponse:
            result = await ioresponse.text()
            print(result)
            result = json.loads(result)

            rw = {}
            for i in result:
                if public:
                    rw[i] = row_result[i]
                elif not public:
                    del row_result[i]

            if public: row_result = rw

            session.close()
            return row_result


@app.get(MAIN_URL+"/info/mod/{mod_id}")
async def info_mod(response: Response, request: Request, mod_id: int, dependencies: bool = None,
                   short_description: bool = None, description: bool = None, dates: bool = None,
                   general: bool = True, game: bool = None, authors: bool = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/info/mod/{mod_id}?token={config.token_info_mod}&general=true'
    if dependencies: url+=f'&dependencies={dependencies}'
    if short_description: url+=f'&short_description={short_description}'
    if description: url+=f'&description={description}'
    if dates: url+=f'&dates={dates}'
    if game: url+=f'&game={game}'


    async with aiohttp.ClientSession() as session:
        async with session.get(url=url) as ioresponse:
            result = await ioresponse.text()
            if ioresponse.status >= 200 and ioresponse.status < 300:
                result = json.loads(result)
            else:
                return JSONResponse(status_code=404, content="Не найдено!")

            # Создание сессии
            Session = sessionmaker(bind=account.engine)
            session = Session()

            if authors:
                row = session.query(account.mod_and_author).filter_by(mod_id=mod_id)
                row_results = row.all()
                result["authors"] = []

                for i in row_results:
                    result["authors"].append({"user": i.user_id, "owner": i.owner})

            if result["result"]["public"] >= 2:
                access_result = await account.check_access(request=request, response=response)

                if access_result and access_result.get("owner_id", -1) >= 0:
                    row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1)).first()

                    if row.admin:
                        session.close()
                        return JSONResponse(status_code=200, content=result)

                    row = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=access_result.get("owner_id", -1))

                    if row.first():
                        session.close()
                        return JSONResponse(status_code=200, content=result)

                    session.close()
                    return JSONResponse(status_code=403, content="Доступ воспрещен!")
                else:
                    session.close()
                    return JSONResponse(status_code=401, content="Недействительный ключ сессии!")
            else:
                session.close()

                if not general:
                    del result["result"]["name"]
                    del result["result"]["size"]
                    del result["result"]["source"]
                    del result["result"]["downloads"]
                    del result["result"]["public"]

                return JSONResponse(status_code=200, content=result)

@app.get(MAIN_URL+"/list/resources_mods/{mods_list_id}")
async def list_resources_for_mods(response: Response, request: Request, mods_ids_list, page_size: int = 10,
                                  page: int = 0, types_resources=[]):
    """
    Тестовая функция
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    types_resources = tools.str_to_list(types_resources)
    if len(mods_ids_list) < 1 or len(mods_ids_list) > 50:
        return JSONResponse(status_code=413, content={"message": "the size of the array is not correct", "error_id": 1})
    if len(types_resources) + len(mods_ids_list) > 80:
        return JSONResponse(status_code=413, content={"message": "the maximum complexity of filters is 80 elements in sum", "error_id": 2})
    elif page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 3})
    elif page < 0:
        return JSONResponse(status_code=413, content={"message": "incorrect page", "error_id": 4})

    async with aiohttp.ClientSession() as session:
        async with session.get(url=SERVER_ADDRESS+f'/public/mod/{str(mods_ids_list)}') as ioresponse:
            result = json.loads(await ioresponse.text())

            l = []
            for i in mods_ids_list:
                if i not in result:
                    l.append(i)

            if len(l) > 0:
                access_result = await account.check_access(request=request, response=response)

                if access_result and access_result.get("owner_id", -1) >= 0:
                    row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1)).first()

                    rowT = session.query(account.mod_and_author).filter_by(user_id=access_result.get("owner_id", -1))
                    rowT = rowT.filter(account.mod_and_author.c.mod_id.in_(l))

                    if rowT.count() != len(l) and not row.admin:
                        session.close()
                        return JSONResponse(status_code=403, content="Доступ воспрещен!")
                else:
                    session.close()
                    return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

            async with aiohttp.ClientSession() as session:
                url = SERVER_ADDRESS+f'/list/resources_mods/{str(mods_ids_list)}?token={config.token_info_mod}'
                if page_size is not None: url+=f'&page_size={page_size}'
                if page is not None: url+=f'&page={page}'
                if types_resources is not None: url+=f'&types_resources={types_resources}'

                async with session.get(url=url) as aioresponse:
                    return json.loads(await aioresponse.text())

@app.get(MAIN_URL+"/list/tags/mods/{mods_ids_list}")
async def list_tags_for_mods(response: Response, request: Request, mods_ids_list, tags=[], only_ids: bool = False):
    """
    Тестовая функция
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    tags = tools.str_to_list(tags)
    if len(mods_ids_list) < 1 or len(mods_ids_list) > 50:
        return JSONResponse(status_code=413, content={"message": "the size of the array is not correct", "error_id": 1})
    if len(tags) + len(mods_ids_list) > 80:
        return JSONResponse(status_code=413, content={"message": "the maximum complexity of filters is 80 elements in sum", "error_id": 2})

    async with aiohttp.ClientSession() as session:
        async with session.get(url=SERVER_ADDRESS+f'/public/mod/{str(mods_ids_list)}') as ioresponse:
            result = json.loads(await ioresponse.text())

            l = []
            for i in mods_ids_list:
                if i not in result:
                    l.append(i)

            if len(l) > 0:
                access_result = await account.check_access(request=request, response=response)

                if access_result and access_result.get("owner_id", -1) >= 0:
                    row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1)).first()

                    rowT = session.query(account.mod_and_author).filter_by(user_id=access_result.get("owner_id", -1))
                    rowT = rowT.filter(account.mod_and_author.c.mod_id.in_(l))

                    if rowT.count() != len(l) and not row.admin:
                        session.close()
                        return JSONResponse(status_code=403, content="Доступ воспрещен!")
                else:
                    session.close()
                    return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

            async with aiohttp.ClientSession() as session:
                url = SERVER_ADDRESS+f'/list/tags/mods/{str(mods_ids_list)}?token={config.token_info_mod}'
                if tags is not None: url+=f'&tags={str(tags)}'
                if only_ids is not None: url+=f'&only_ids={only_ids}'

                async with session.get(url=url) as aioresponse:
                    return json.loads(await aioresponse.text())


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


@app.post(MAIN_URL+"/add/game")
async def add_game(response: Response, request: Request, game_name: str, game_short_desc: str, game_desc: str,
                   game_type: str = "game", game_logo: str = ""):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS+f'/account/add/game?token={config.token_add_game}&game_name={game_name}&game_short_desc={game_short_desc}&game_desc={game_desc}&game_type={game_type}&game_logo={game_logo}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/add/genre")
async def add_genre(response: Response, request: Request, genre_name: str):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/add/genre?token={config.token_add_genre}&genre_name={genre_name}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/add/tag")
async def add_tag(response: Response, request: Request, tag_name: str):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/add/tag?token={config.token_add_tag}&tag_name={tag_name}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/add/resource")
async def add_resource(response: Response, request: Request, resource_type_name: str, resource_url: str, resource_owner_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/add/resource?token={config.token_add_resource}&resource_type_name={resource_type_name}&resource_url={resource_url}&resource_owner_id={resource_owner_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/add/mod")
async def add_mod(response: Response, request: Request, mod_name: str, mod_short_description: str,
                  mod_description: str, mod_source: str, mod_game: int, mod_public: int, mod_file: UploadFile):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/add/mod?token={config.token_add_mod}&mod_name={mod_name}&mod_short_description={mod_short_description}&mod_description={mod_description}&mod_source={mod_source}&mod_game={mod_game}&mod_public={mod_public}'
    real_mod_file = io.BytesIO(await mod_file.read())
    real_mod_file.name = mod_file.filename

    result_code, result_data, result = await tools.mod_to_backend(response=response, request=request, url=url, body={"mod_file": real_mod_file})

    print(int(request.cookies.get('userID', 0)), result_code, flush=True)
    print(result_data, flush=True)

    if result_code in [201]:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        # Выполнение запроса
        insert_statement = insert(account.mod_and_author).values(
            user_id=int(request.cookies.get('userID', 0)),
            owner=True,
            mod_id=int(result_data)
        )
        session.execute(insert_statement)

        # Подтверждение
        session.commit()
        session.close()

    return result


@app.post(MAIN_URL+"/edit/game")
async def edit_game(response: Response, request: Request, game_id: int, game_name: str = None,
                    game_short_desc: str = None, game_desc: str = None, game_type: str = None, game_logo: str = None,
                    game_source: str = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/edit/game?token={config.token_edit_game}&game_id={game_id}'
    if game_name is not None: url += f'&game_name={game_name}'
    if game_short_desc is not None: url += f'&game_short_desc={game_short_desc}'
    if game_desc is not None: url += f'&game_desc={game_desc}'
    if game_type is not None: url += f'&game_type={game_type}'
    if game_logo is not None: url += f'&game_logo={game_logo}'
    if game_source is not None: url += f'&game_source={game_source}'

    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/edit/genre")
async def edit_genre(response: Response, request: Request, genre_id: int, genre_name: str = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/edit/genre?token={config.token_edit_genre}&genre_id={genre_id}'
    if genre_name is not None: url+=f'&genre_name={genre_name}'

    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/edit/tag")
async def edit_tag(response: Response, request: Request, tag_id: int, tag_name: str = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/edit/tag?token={config.token_edit_tag}&tag_id={tag_id}'
    if tag_name is not None: url+=f'&tag_name={tag_name}'

    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/edit/resource")
async def edit_resource(response: Response, request: Request, resource_id: int, resource_type: str = None,
                        resource_url: str = None, resource_owner_id: int = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/edit/resource?token={config.token_edit_resource}&resource_id={resource_id}'
    if resource_type is not None: url+=f'&resource_type={resource_type}'
    if resource_url is not None: url+=f'&resource_url={resource_url}'
    if resource_owner_id is not None: url+=f'&resource_owner_id={resource_owner_id}'

    return await tools.to_backend(response=response, request=request, url=url)


@app.post(MAIN_URL+"/edit/mod/authors")
async def edit_authors_mod(response: Response, request: Request, mod_id:int, mode:bool, author:int, owner:bool = False):
    """
    Тестовая функция
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        req_user_id = access_result.get("owner_id", -1)
        user_req = session.query(account.Account).filter_by(id=req_user_id).first()
        user_add = session.query(account.Account).filter_by(id=mod_id).first()

        async def mini():
            if not user_add:
                return False
            elif user_req.admin:
                return True
            else:
                if user_req.mute_until and user_req.mute_until > datetime.datetime.now():
                    return False

                in_mod = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=req_user_id).first()

                if in_mod:
                    if in_mod.owner:
                        if req_user_id == author and mode == False:
                            return False

                        return True
                    elif req_user_id == author and mode == False:
                        return True
                elif user_req.change_authorship_mods:
                    return True
            return False


        if await mini():
            if mode:
                has_owner = session.query(account.mod_and_author).filter_by(mod_id=mod_id, owner=True).first()
                if owner and has_owner:
                    delete_member = account.mod_and_author.delete().where(account.mod_and_author.c.mod_id == mod_id,
                                                                          account.mod_and_author.c.user_id == has_owner.user_id)
                    # Выполнение операции DELETE
                    session.execute(delete_member)
                    session.commit()

                insert_statement = insert(account.mod_and_author).values(
                    user_id=author,
                    owner=owner,
                    mod_id=mod_id
                )
                session.execute(insert_statement)
                session.commit()
            else:
                delete_member = account.mod_and_author.delete().where(account.mod_and_author.c.mod_id == mod_id,
                                                                      account.mod_and_author.c.user_id == author)
                # Выполнение операции DELETE
                session.execute(delete_member)
                session.commit()

            session.close()
            return JSONResponse(status_code=200, content="Выполнено")
        else:
            session.close()
            return JSONResponse(status_code=403, content="Операция заблокирована!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

@app.post(MAIN_URL+"/edit/mod")
async def edit_mod(response: Response, request: Request, mod_id: int, mod_name: str = None,
                   mod_short_description: str = None, mod_description: str = None, mod_source: str = None,
                   mod_game: int = None, mod_public: int = None, mod_file: UploadFile = None):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/edit/mod?token={config.token_edit_mod}&mod_id={mod_id}'
    if mod_name is not None: url+=f'&mod_name={mod_name}'
    if mod_short_description is not None: url += f'&mod_short_description={mod_short_description}'
    if mod_description is not None: url += f'&mod_description={mod_description}'
    if mod_source is not None: url += f'&mod_source={mod_source}'
    if mod_game is not None: url += f'&mod_game={mod_game}'
    if mod_public is not None: url += f'&mod_public={mod_public}'

    print(url)

    if mod_file:
        real_mod_file = io.BytesIO(await mod_file.read())
        real_mod_file.name = mod_file.filename
    else:
        real_mod_file = ''

    result_code, result_data, result = await tools.mod_to_backend(response=response, request=request, url=url, body={"mod_file": real_mod_file})

    return result


@app.post(MAIN_URL+"/delete/game")
async def delete_game(response: Response, request: Request, game_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS+f'/account/delete/game?token={config.token_delete_game}&game_id={game_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/delete/genre")
async def delete_genre(response: Response, request: Request, genre_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/delete/genre?token={config.token_delete_genre}&genre_id={genre_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/delete/tag")
async def delete_tag(response: Response, request: Request, tag_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/delete/tag?token={config.token_delete_tag}&tag_id={tag_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/delete/resource")
async def delete_resource(response: Response, request: Request, resource_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/delete/resource?token={config.token_delete_resource}&resource_id={resource_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/delete/mod")
async def delete_mod(response: Response, request: Request, mod_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/delete/mod?token={config.token_delete_mod}&mod_id={mod_id}'
    code_result, result_data, result = await tools.mod_to_backend(response=response, request=request, url=url, no_members_access=True)

    if code_result in [202, 500]:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        # Выполнение запроса
        delete_mod = account.mod_and_author.delete().where(account.mod_and_author.c.mod_id == mod_id)

        # Выполнение операции DELETE
        session.execute(delete_mod)
        session.commit()
        session.close()

    return result


@app.post(MAIN_URL+"/association/game/genre")
async def association_game_with_genre(response: Response, request: Request, game_id: int, mode: bool, genre_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/association/game/genre?token={config.token_association_game_genre}&game_id={game_id}&mode={mode}&genre_id={genre_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/association/game/tag")
async def association_game_with_tag(response: Response, request: Request, game_id: int, mode: bool, tag_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/association/game/tag?token={config.token_association_game_tag}&game_id={game_id}&mode={mode}&tag_id={tag_id}'
    return await tools.to_backend(response=response, request=request, url=url)

@app.post(MAIN_URL+"/association/mod/tag")
async def association_mod_with_tag(response: Response, request: Request, mod_id: int, mode: bool, tag_id: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/association/mod/tag?token={config.token_association_mod_tag}&mod_id={mod_id}&mode={mode}&tag_id={tag_id}'
    code_result, result_data, result = await tools.mod_to_backend(response=response, request=request, url=url)
    return result

@app.post(MAIN_URL+"/association/mod/dependencie")
async def association_mod_with_dependencie(response: Response, request: Request, mod_id: int, mode: bool, dependencie: int):
    """
    Тестовая функция
    """
    url = SERVER_ADDRESS + f'/account/association/mod/dependencie?token={config.token_association_mod_dependencie}&mod_id={mod_id}&mode={mode}&dependencie={dependencie}'
    code_result, result_data, result = await tools.mod_to_backend(response=response, request=request, url=url)
    return result


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
