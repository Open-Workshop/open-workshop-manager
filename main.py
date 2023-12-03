from fastapi import FastAPI, Request, Response
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


SERVER_ADDRESS = "http://127.0.0.1:8000"
MAIN_URL = "/api/accounts"
STANDART_STR_TIME = "%d.%m.%Y/%H:%M:%S"



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
                        img.save(f"accounts_avatars/{str(id)}.jpeg", "JPEG")

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

    response.set_cookie(key='loginJS', value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME), max_age=5184000)
    response.set_cookie(key='accessJS', value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME), max_age=5184000)

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"

@app.post(MAIN_URL+"/authorization/refresh")
async def refresh(response: Response, request: Request):
    """
    Получение новой пары access+refresh токенов на основе еще живого refresh токена
    """
    # Создание сессии
    Session = sessionmaker(bind=account.engine)
    session = Session()

    # Выполнение запроса
    old_refresh_token = request.cookies.get("refreshToken", "")
    row = session.query(account.Session).filter_by(refresh_token=old_refresh_token, broken=None)

    today = datetime.datetime.now()
    row = row.filter(account.Session.end_date_refresh > today)

    if row.first():
        access_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(6))).decode('utf-8')
        refresh_token = (bcrypt.hashpw(str(datetime.datetime.now().microsecond).encode('utf-8'), bcrypt.gensalt(7))).decode('utf-8')

        end_access = today+datetime.timedelta(minutes=40)
        end_refresh = today+datetime.timedelta(days=60)

        # Обновление БД
        row.update({"end_date_access": end_access, "end_date_refresh": end_refresh,
                    "access_token": access_token, "refresh_token": refresh_token})
        session.commit()

        # Обновление данных в куки юзера
        response.set_cookie(key='accessToken', value=access_token, httponly=True, secure=True, max_age=2100)
        response.set_cookie(key='refreshToken', value=refresh_token, httponly=True, secure=True, max_age=5184000)

        response.set_cookie(key='loginJS', value=end_refresh.strftime(STANDART_STR_TIME), max_age=5184000)
        response.set_cookie(key='accessJS', value=end_access.strftime(STANDART_STR_TIME), max_age=5184000)

        return True
    return False

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

    # Удаление токенов у юзера
    response.delete_cookie(key='accessToken')
    response.delete_cookie(key='refreshToken')
    response.delete_cookie(key='loginJS')
    response.delete_cookie(key='accessJS')

    return True


@app.get(MAIN_URL+"/profile/info/{user_id}")
async def info_profile(user_id:int):
    """
    Тестовая функция
    """
    # TODO логика получения информации о профиле (своём или чужом)
    return 0

@app.post(MAIN_URL+"/profile/edit/{user_id}")
async def edit_profile(user_id:int):
    """
    Тестовая функция
    """
    # TODO логика редактирования профиля (своего или чужого) (проверка хватает ли прав на это)
    # Разрешено только .jpeg в аватарах
    return 0

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
