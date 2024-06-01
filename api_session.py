from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sql_logic import sql_account as account
import json
from yandexid import AsyncYandexOAuth, AsyncYandexID
from google_auth_oauthlib.flow import Flow
import bcrypt
import urllib
import datetime
import random
import string
import tools
from PIL import Image
from io import BytesIO
from ow_config import MAIN_URL
import ow_config as config
import aiohttp
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker


STANDART_STR_TIME = account.STANDART_STR_TIME


router = APIRouter()


# Создаем объект Flow
with open('credentials.json', 'r') as config_file:
    google_config = json.load(config_file)
data = {
    'client_id': google_config["web"]["client_id"],
    'client_secret': google_config["web"]["client_secret"],
    'redirect_uri': google_config["web"]["redirect_uris"][0],
    'grant_type': 'authorization_code'
}
yandex_oauth = AsyncYandexOAuth(
    client_id=config.yandex_client_id,
    client_secret=config.yandex_client_secret,
    redirect_uri="https://openworkshop.su/broken/yandex"#'https://openworkshop.su'+MAIN_URL+'/authorization/yandex/complite'
)


@router.get(MAIN_URL+"/session/google/link", response_class=HTMLResponse, tags=["Session"])
async def google_send_link(request: Request):
    """
    Получение ссылки на авторизацию через Google
    """
    ru = await account.no_from_russia(request=request)
    if ru: return ru

    authorization_url, state = Flow.authorization_url()
    return RedirectResponse(url=authorization_url)

@router.get(MAIN_URL+"/session/yandex/link", tags=["Session"])
async def yandex_send_link():
    """
    Получение ссылки на авторизацию через YandexID
    """
    return RedirectResponse(url=yandex_oauth.get_authorization_url())

@router.post(MAIN_URL+"/session/password", tags=["Session"])
async def password_authorization(response: Response, login: str, password: str):
    """
    Авторизация в систему через пароль. Не очень безопасный метод :)
    """
    # Создание сессии
    session = sessionmaker(bind=account.engine)()

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

@router.get(MAIN_URL+"/session/google/complite", response_class=HTMLResponse, tags=["Session"])
async def google_complite(response: Response, request: Request, code:str, _state:str = "", _scope:str = "",
                          _authuser:int = -1, _prompt:str = ""):
    """
    Авторизация в систему через Google.

    Если данный аккаунт не привязан ни к одному из аккаунтов OW и при этом передать access_token то произойдет коннект.
    """
    ru = await account.no_from_russia(request=request)
    if ru: return ru

    async with aiohttp.ClientSession() as NETsession:
        data_complite = data.copy()
        data_complite["code"] = urllib.parse.unquote(code)

        async with NETsession.post('https://oauth2.googleapis.com/token', data=data_complite) as token_response:
            google_access = await token_response.json()
            print(google_access)

            async with NETsession.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={
                'Authorization': f'Bearer {google_access["access_token"]}'}) as user_info_response:
                user_data = await user_info_response.json()


    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    # Выполнение запроса
    rows = session.query(account.Account.id).filter(account.Account.google_id == user_data["id"]).first()

    if not rows:
        if session.query(account.blocked_account_creation).filter_by(google_id=user_data["id"]).first():
            return "Этот аккаунт Google использовался в недавно удаленном аккаунте Open Workshop!"

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
            )
            # Выполнение операции INSERT
            result = session.execute(insert_statement)
            id = result.lastrowid

            if len(user_data.get("picture", "")) > 0:
                session.commit()
                session.close()
                
                async with aiohttp.ClientSession() as NETsession:
                    async with NETsession.get(user_data["picture"]) as resp:
                        if resp.status == 200:
                            # Чтобы узнать расширение файла из ответа сервера: resp.headers['Content-Type']
                            # может содержать: image/jpeg, image/png, image/gif, image/bmp, image/webp
                            format_name = resp.headers['Content-Type'].split("/")[1]

                            if await tools.storage_file_upload(type="avatar", path=f"{id}.{format_name}", file=BytesIO(await resp.read())):
                                # Помечаем в БД пользователя, что у него есть аватар
                                session.query(account.Account).filter(account.Account.id == id).update({"avatar_url": f"local.{format_name}"})
                                session.commit()
                            else:
                                print("Google регистрация: во время загрузки аватара произошла ошибка!")
                        else:
                            print("Google регистрация: во время получения изображения произошла ошибка!")
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

@router.get(MAIN_URL+"/session/yandex/complite", response_class=HTMLResponse, tags=["Session"])
async def yandex_complite(response: Response, request: Request, code:int):
    """
    Авторизация в систему через YandexID.

    Если данный аккаунт не привязан ни к одному из аккаунтов OW и при этом передать access_token то произойдет коннект.
    """
    token = await yandex_oauth.get_token_from_code(code)
    user_data = await AsyncYandexID(oauth_token=token.access_token).get_user_info_json()

    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    # Выполнение запроса
    rows = session.query(account.Account.id).filter(account.Account.yandex_id == user_data.id).first()

    if not rows:
        if session.query(account.blocked_account_creation).filter_by(yandex_id=user_data.id).first():
            return "Этот аккаунт Yandex использовался в недавно удаленном аккаунте Open Workshop!"

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
            )
            # Выполнение операции INSERT
            result = session.execute(insert_statement)
            id = result.lastrowid

            if not user_data.is_avatar_empty:
                session.commit()
                session.close()
                
                async with aiohttp.ClientSession() as NETsession:
                    async with NETsession.get(f"https://avatars.yandex.net/get-yapic/{user_data.default_avatar_id}/islands-200") as resp:
                        if resp.status == 200:
                            # Чтобы узнать расширение файла из ответа сервера: resp.headers['Content-Type']
                            # может содержать: image/jpeg, image/png, image/gif, image/bmp, image/webp
                            format_name = resp.headers['Content-Type'].split("/")[1]

                            if await tools.storage_file_upload(type="avatar", path=f"{id}.{format_name}", file=BytesIO(await resp.read())):
                                # Помечаем в БД пользователя, что у него есть аватар
                                session.query(account.Account).filter(account.Account.id == id).update({"avatar_url": f"local.{format_name}"})
                                session.commit()
                            else:
                                print("Яндекс регистрация: во время загрузки аватара произошла ошибка!")
                        else:
                            print("Яндекс регистрация: во время получения аватара произошла ошибка!")
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

@router.post(MAIN_URL+"/session/disconnect", tags=["Session", "Profile"])
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

@router.post(MAIN_URL+"/session/refresh", tags=["Session"])
async def refresh(response: Response, request: Request):
    """
    Получение новой пары access+refresh токенов на основе еще живого refresh токена
    """
    return bool(await account.update_session(response=response, request=request))

@router.post(MAIN_URL+"/session/logout", tags=["Session"])
async def logout(response: Response, request: Request):
    """
    Выход из системы.
    Удаляет аккаунт-куки у пользователя, а так же убивает сессию (соответсвующее токены становятся невалидными)!
    """

    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    # Выполнение запроса
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
