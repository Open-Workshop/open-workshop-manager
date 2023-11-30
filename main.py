from fastapi import FastAPI, Request, Response
from starlette.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert
import account_sql as account
import ow_config as config
from yandexid import AsyncYandexOAuth, AsyncYandexID
import datetime


SERVER_ADDRESS = "http://127.0.0.1:8000"
MAIN_URL = "/api/accounts"


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



@app.get(MAIN_URL+"/authorization/yandex/link")
async def yandex_send_link():
    """
    Получение ссылки на авторизацию через YandexID
    """
    return RedirectResponse(url=yandex_oauth.get_authorization_url())

@app.get(MAIN_URL+"/authorization/yandex/complite", response_class=HTMLResponse)
async def yandex_complite(response: Response, request: Request, code:int):
    """
    Авторизация в систему через YandexID
    """

    print(request.cookies)

    token = await yandex_oauth.get_token_from_code(code)
    user_data = await AsyncYandexID(oauth_token=token.access_token).get_user_info_json()

    print(user_data)

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
    else:
        id = rows.id

    sessions_data = await account.gen_session(id, session)

    session.commit()
    session.close()

    response.set_cookie(key='accessToken', value=sessions_data["access"]["token"], httponly=True, max_age=2100)
    response.set_cookie(key='refreshToken', value=sessions_data["refresh"]["token"], httponly=True, max_age=5184000)

    response.set_cookie(key='loginJS', value='true', max_age=5184000)

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"

@app.get(MAIN_URL+"/authorization/logout")
async def logout(response: Response, request: Request):
    """
    Выход из системы
    """

    # Создание сессии
    Session = sessionmaker(bind=account.engine)

    # Выполнение запроса
    session = Session()
    session.query(account.Session).filter_by(refresh_token=request.cookies.get("refreshToken", "")).update(
        {"broken": "logout"})
    session.commit()

    # Удаление токенов у юзера
    response.delete_cookie(key='accessToken')
    response.delete_cookie(key='refreshToken')
    response.delete_cookie(key='loginJS')

    return True


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


@app.post(MAIN_URL+"/edit/profile")
async def edit_profile():
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
