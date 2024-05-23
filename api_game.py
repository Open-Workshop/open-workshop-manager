from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import JSONResponse
import tools
from ow_config import MAIN_URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, delete
from sql_logic import sql_catalog as catalog
from datetime import datetime


router = APIRouter()



@router.get("/info/game/{game_id}")
async def game_info(game_id: int, short_description: bool = False, description: bool = False, dates: bool = False,
                    statistics: bool = False):
    """
    Возвращает информацию об конкретной игре, а так же его состояние на сервере.

    1. `short_description` *(bool)* - отправлять ли короткое описание. По умолчанию `False`.
    2. `description` *(bool)* - отправлять ли описание. По умолчанию `False`.
    3. `dates` *(bool)* - отправлять ли даты. По умолчанию `False`.
    4. `statistics` *(bool)* - отправлять ли статистику. По умолчанию `False`.
    """
    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()

    # Выполнение запроса
    query = session.query(catalog.Game.name, catalog.Game.type, catalog.Game.logo, catalog.Game.source)
    if description:
        query = query.add_column(catalog.Game.description)
    if short_description:
        query = query.add_column(catalog.Game.short_description)
    if dates:
        query = query.add_column(catalog.Game.creation_date)
    if statistics:
        query = query.add_columns(catalog.Game.mods_count, catalog.Game.mods_downloads)

    query = query.filter(catalog.Game.id == game_id)
    output = {"pre_result": query.first()}
    session.close()

    if output["pre_result"]:
        output["result"] = {"name": output["pre_result"].name, "type": output["pre_result"].type,
                            "logo": output["pre_result"].logo, "source": output["pre_result"].source}
        if description:
            output["result"]["description"] = output["pre_result"].description
        if short_description:
            output["result"]["short_description"] = output["pre_result"].short_description
        if dates:
            output["result"]["creation_date"] = output["pre_result"].creation_date
        if statistics:
            output["result"]["mods_count"] = output["pre_result"].mods_count
            output["result"]["mods_downloads"] = output["pre_result"].mods_downloads
    else:
        output["result"] = None
    del output["pre_result"]

    return output

@router.get("/list/games/", tags=["Game"])
async def games_list(page_size: int = 10, page: int = 0, sort: str = "MODS_DOWNLOADS", name: str = "",
                     type_app=[], genres=[], primary_sources=[],
                     short_description: bool = False, description: bool = False, dates: bool = False,
                     statistics: bool = False):
    """
    Возвращает список игр, моды к которым есть на сервере.

    1. "page_size" - размер 1 страницы. Диапазон - 1...50 элементов.
    2. "page" - номер странице. Не должна быть отрицательной.
    3. "short_description" - отправлять ли короткое описание. По умолчанию `False`.
    4. "description" - отправлять ли описание. По умолчанию `False`.
    5. "dates" - отправлять ли даты. По умолчанию `False`.
    6. "statistics" - отправлять ли статистику. По умолчанию `False`.

    О сортировке:
    Префикс `i` указывает что сортировка должна быть инвертированной.
    1. `NAME` - сортировка по имени.
    2. `TYPE` - сортировка по типу *(`game` или `app`)*.
    3. `CREATION_DATE` - сортировка по дате регистрации на сервере.
    4. `MOD_DOWNLOADS` - сортировка по суммарному количеству скачанных модов для игры *(по умолчанию)*.
    5. `MODS_COUNT` - сортировка по суммарному количеству модов для игры.
    6. `SOURCE` - сортировка по источнику.

    О фильтрации:
    1. `name` - фильтрация по имени.
    2. `type_app` - фильтрация по типу *(массив str)*.
    3. `genres` - фильтрация по жанрам (массив id)*.
    4. `primary_sources` - фильтрация по первоисточнику *(массив str)*.
    """

    genres = tools.str_to_list(genres)
    type_app = tools.str_to_list(type_app)
    primary_sources = tools.str_to_list(primary_sources)

    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})
    elif (len(type_app) + len(genres) + len(primary_sources)) > 30:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 30 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()
    # Выполнение запроса
    query = session.query(catalog.Game.id, catalog.Game.name, catalog.Game.type, catalog.Game.logo, catalog.Game.source)
    if description:
        query = query.add_column(catalog.Game.description)
    if short_description:
        query = query.add_column(catalog.Game.short_description)
    if dates:
        query = query.add_column(catalog.Game.creation_date)
    if statistics:
        query = query.add_columns(catalog.Game.mods_count, catalog.Game.mods_downloads)

    query = query.order_by(tools.sort_games(sort))

    # Фильтрация по жанрам
    if len(genres) > 0:
        for genre in genres:
            print(type(genre))
            query = query.filter(catalog.Game.genres.any(id=genre))

            # filtered_games = session.query(Game).filter(Game.genres.any(id=excluded_genre_id))

    # Фильтрация по первоисточникам
    if len(primary_sources) > 0:
        query = query.filter(catalog.Game.source.in_(primary_sources))

    # Фильтрация по типу
    if len(type_app) > 0:
        query = query.filter(catalog.Game.type.in_(type_app))

    # Фильтрация по имени
    if len(name) > 0:
        query = query.filter(catalog.Game.name.ilike(f'%{name}%'))

    mods_count = query.count()
    offset = page_size * page
    games = query.offset(offset).limit(page_size).all()

    output_games = []
    for game in games:
        out = {"id": game.id, "name": game.name, "type": game.type, "logo": game.logo, "source": game.source}
        if description:
            out["description"] = game.description
        if short_description:
            out["short_description"] = game.short_description
        if dates:
            out["creation_date"] = game.creation_date
        if statistics:
            out["mods_count"] = game.mods_count
            out["mods_downloads"] = game.mods_downloads
        output_games.append(out)

    session.close()
    return {"database_size": mods_count, "offset": offset, "results": output_games}

@router.get("/list/genres/games/{games_ids_list}", tags=["Game", "Genre"])
async def list_genres_for_games(games_ids_list, genres=[], only_ids: bool = False):
    """
    Возвращает ассоциации игр с жанрами

    1. `games_ids_list` - список игр к которым нужно вернуть ассоциации (принимает список ID игр).
    2. `genres` - если не пуст возвращает ассоциации конкретно с этими жанрами (принимает список ID жанров).
    3. `only_ids` - если True возвращает только ID ассоцируемых жанров, если False возвращает всю информацию о каждом ассоцируемом жанре.
    """
    games_ids_list = tools.str_to_list(games_ids_list)
    genres = tools.str_to_list(genres)

    if (len(games_ids_list) + len(genres)) > 80:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()

    # Выполнение запроса
    result = {}
    query_global = session.query(catalog.Genre).join(catalog.game_genres)
    for game_id in games_ids_list:
        query = query_global.filter(catalog.game_genres.c.game_id == game_id)
        if len(genres) > 0:
            query = query.filter(catalog.Genre.id.in_(genres))

        if only_ids:
            if result.get(game_id, None) == None: result[game_id] = []
            for id in query.all(): result[game_id].append(id.id)
        else:
            result[game_id] = query.all()

    return result


@router.post(
    MAIN_URL+"/add/game", 
    tags=["Game"],
    status_code=202,
    responses={
        202: {"description": "OK"},
        401: {"description": "Недействительный ключ сессии!"},
        403: {"description": "Вы не админ!"},
    }
)
async def add_game(
    response: Response,  # Ответ HTTP
    request: Request,  # Запрос HTTP
    game_name: str = Form(..., description="Название игры"),  # Название игры
    game_short_desc: str = Form(..., description="Краткое описание игры"),  # Краткое описание игры
    game_desc: str = Form(..., description="Полное описание игры"),  # Описание игры
    game_type: str = Form("game", description="Тип игры"),  # Тип игры (по умолчанию "game")
    game_logo: str = Form("", description="Логотип игры (url)")  # Логотип игры (по умолчанию пустая строка)
) -> JSONResponse:
    """
    Возвращает ID вставленной строки в базе данных.
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Game).values(
            name=game_name,
            type=game_type,
            logo=game_logo,
            short_description=game_short_desc,
            description=game_desc,
            mods_downloads=0,
            mods_count=0,
            creation_date=datetime.now(),
            source='local'
        )

        result = session.execute(insert_statement)
        id = result.lastrowid

        session.commit()
        session.close()

        return JSONResponse(status_code=202, content=id)
    else:
        return access_result

@router.post(
    MAIN_URL+"/edit/game",
    tags=["Game"],
    status_code=202,
    responses={
        202: {"description": "Изменение данных в базе данных по указанному ID игры."},
        401: {"description": "Недействительный ключ сессии!"},
        403: {"description": "Вы не админ!"},
        404: {"description": "Элемент не найден."},
        418: {"description": "Пустой запрос."},
    }
)
async def edit_game(
    response: Response,  # Ответ HTTP
    request: Request,  # Запрос HTTP
    game_id: int = Form(..., description="ID игры для редактирования"),  # ID игры для редактирования
    game_name: str = Form(None, description="Название игры"),  # Название игры
    game_short_desc: str = Form(None, description="Краткое описание игры"),  # Краткое описание игры
    game_desc: str = Form(None, description="Полное описание игры"),  # Описание игры
    game_type: str = Form(None, description="Тип игры"),  # Тип игры
    game_logo: str = Form(None, description="Логотип игры (url)"),  # Логотип игры (url)
    game_source: str = Form(None, description="Источник игры"),  # Источник игры
) -> JSONResponse:
    """
    Изменяет данные в базе данных по указанному ID игры.
    Для изменения нет данных, возвращает 418 "Некорректный запрос".
    Если игры нет в базе данных, возвращает 404 "Элемент не найден".

    game_id (int) - ID игры для редактирования
    game_name (str) - Название игры
    game_short_desc (str) - Краткое описание игры
    game_desc (str) - Полное описание игры
    game_type (str) - Тип игры
    game_logo (https url/str) - Логотип игры (url)
    game_source (str) - Источник игры

    Возвращает код состояния и сообщение о результате.
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        game = session.query(catalog.Game).filter_by(id=game_id)
        if not game.first():
            return JSONResponse(status_code=404, content="The element does not exist.")

        # Подготавливаем данные
        data_edit = {}
        if game_name:
            data_edit["name"] = game_name
        if game_short_desc:
            data_edit["short_description"] = game_short_desc
        if game_desc:
            data_edit["description"] = game_desc
        if game_type:
            data_edit["type"] = game_type
        if game_logo:
            data_edit["logo"] = game_logo
        if game_source:
            data_edit["source"] = game_source

        if len(data_edit) <= 0:
            return JSONResponse(status_code=418, content="The request is empty")

        # Меняем данные в БД
        game.update(data_edit)
        session.commit()
        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.delete(
    MAIN_URL+"/delete/game",
    tags=["Game"],
    description="Удаление игры из базы данных.",
    status_code=202,
    responses={
        202: {"description": "Удаление игры из базы данных."},
        401: {"description": "Недействительный ключ сессии!"},
        403: {"description": "Вы не админ!"},
    },
)
async def delete_game(
    response: Response, request: Request, game_id: int = Form(..., description="ID игры для удаления")
) -> JSONResponse:
    """
    Удаляет игру и все ассоциированные с ней жанры и теги из базы данных.

    game_id (int) - ID игры для удаления

    Возвращает код состояния и сообщение о результате.
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        delete_game = delete(catalog.Game).where(catalog.Game.id == game_id)

        delete_genres_association = catalog.game_genres.delete().where(catalog.game_genres.c.game_id == game_id)
        delete_tags_association = catalog.allowed_mods_tags.delete().where(catalog.allowed_mods_tags.c.game_id == game_id)

        # Выполнение операции DELETE
        session.execute(delete_game)
        session.execute(delete_genres_association)
        session.execute(delete_tags_association)
        session.commit()
        session.close()

        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
