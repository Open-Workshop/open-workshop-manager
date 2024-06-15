from fastapi import APIRouter, Request, Response, Form, Query, Path
from fastapi.responses import JSONResponse
import tools
from ow_config import MAIN_URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, delete
from sql_logic import sql_catalog as catalog
from datetime import datetime


router = APIRouter()



@router.get(
    MAIN_URL+"/list/games/",
    tags=["Game"],
    summary="Возвращает список игр, моды к которым есть на сервере.",
    status_code=200,
    responses={
        200: {
            "description": "OK",
            "content": {
                "application/json": {
                    "example": {
                        "database_size": 123,
                        "offset": 123,
                        "results": [
                            {"id": 1, "name": "?", "type": "app", "source": "local"},
                            {"id": 2, "name": "!?", "type": "game", "source": "steam"},
                        ]
                    }
                }
            }
        },
        413: {
            "description": "Неккоректный диапазон параметров(размеров).",
            "content": {
                "application/json": {
                    "example": {
                        "message": "incorrect page size",
                        "error_id": 1
                    }
                }
            }
        },
    }
)
async def games_list(
    page_size: int = Query(10, description="Размер 1 страницы. Диапазон - 1...50 элементов."), 
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."), 
    sort: str = Query("MODS_DOWNLOADS", description="Сортировка. Префикс `i` указывает что сортировка должна быть инвертированной."),
    name: str = Query("", description="Фильтр по заголовку/названию."),
    type_app = Query([], description="Фильтр по типу *(`game` и/или `app`)*.", example="['game','app']"),
    genres=Query([], description="Фильтр по жанрам. Передать id интересующих жанров.", example="[1,2]"),
    primary_sources=Query([], description="Фильтр по источникам. Передать id источников.", example="['local','steam']"), 
    allowed_ids=Query([], description="Фильтр по id. Передать id игр.", example="[1,2]"),
    short_description: bool = Query(False, description="Отправлять ли короткое описание."),
    description: bool = Query(False, description="Отправлять ли описание."),
    dates: bool = Query(False, description="Отправлять ли даты (дата создания)."),
    statistics: bool = Query(False, description="Отправлять ли статистику (количество модов и их общее количество скачиваний).")
):
    """
    О сортировке:
    1. `NAME` - сортировка по имени.
    2. `TYPE` - сортировка по типу *(`game` или `app`)*.
    3. `CREATION_DATE` - сортировка по дате регистрации на сервере.
    4. `MOD_DOWNLOADS` - сортировка по суммарному количеству скачанных модов для игры *(по умолчанию)*.
    5. `MODS_COUNT` - сортировка по суммарному количеству модов для игры.
    6. `SOURCE` - сортировка по источнику.
    """

    genres = tools.str_to_list(genres)
    type_app = tools.str_to_list(type_app)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)

    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})
    elif (len(type_app) + len(genres) + len(primary_sources) + len(allowed_ids)) > 50:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 30 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Game.id, catalog.Game.name, catalog.Game.type, catalog.Game.source)
    if description:
        query = query.add_column(catalog.Game.description)
    if short_description:
        query = query.add_column(catalog.Game.short_description)
    if dates:
        query = query.add_column(catalog.Game.creation_date)
    if statistics:
        query = query.add_columns(catalog.Game.mods_count, catalog.Game.mods_downloads)

    query = query.order_by(tools.sort_games(sort))

    # Фильтрация по разрешенным ID
    if len(allowed_ids) > 0:
        query = query.filter(catalog.Game.id.in_(allowed_ids))

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
        out = {"id": game.id, "name": game.name, "type": game.type, "source": game.source}
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

@router.get(
    MAIN_URL+"/list/genres/games/{games_ids_list}", 
    tags=["Game", "Genre"],
    summary="Ассоциации игр с жанрами",
    status_code=200,
    responses={
        200: {
            "description": "Запрос успешно обработан.",
            "content": {
                "application/json": {
                    "example": {
                        123: [{"id": 1, "name": "Стратегия"}]
                    }
                }
            },
        },
        413: {
            "description": "Превышен максимальный размер сложности фильтрации.",
            "content": {
                "application/json": {
                    "example": {"message": "the maximum complexity of filters is 80 elements in sum", "error_id": 2}
                }
            },
        },
    }
)
async def list_genres_for_games(
    games_ids_list = Path(..., description="Список ID запрошенных игр.", example="[1, 2, 3]"),
    genres=Query([], description="Фильтрация по ID жанров (т.е. если жанра нет в переденном списке, он не передается). Неактивен если пуст.", example="[1, 2, 3]"),
    only_ids: bool = Query(False, description="Возвращать только массив ID жанров. В обычной ситуации возвращает массив словарей с подробной информацией."),
):
    """
    Передает информацию о жанрах запрошенных игр.
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
    summary="Добавление игры",
    status_code=202,
    responses={
        202: {"description": "Возвращает ID созданной игры", "content": {"application/json": {"example": 123}}},
        401: {"description": "Недействительный ключ сессии! (пользователь не авторизован)"},
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
) -> JSONResponse:
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Game).values(
            name=game_name,
            type=game_type,
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
    summary="Редактирование игры",
    status_code=202,
    responses={
        202: {"description": "Изменение данных в базе данных по указанному ID игры."},
        401: {"description": "Недействительный ключ сессии!"},
        403: {"description": "Вы не админ!"},
        404: {"description": "Игра не найдена."},
        418: {"description": "Пустой запрос. Возникает если не передан ни один из параметров-свойств."},
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
    game_source: str = Form(None, description="Источник игры"),  # Источник игры
) -> JSONResponse:
    """
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
    summary="Удаление игры",
    status_code=202,
    responses={
        202: {"description": "Успешно"},
        401: {"description": "Недействительный ключ сессии! (не авторизован)"},
        403: {"description": "Вы не админ!"},
    },
)
async def delete_game(
    response: Response,
    request: Request, 
    game_id: int = Form(..., description="ID игры для удаления")
) -> JSONResponse:
    """
    Удаляет игру, все её ассоциации и ресурсы. 

    Для относительной безопасности(возможность вручную восстановить игру), удаление никак не затрагивает моды игры, в том числе у них не изменяется game_id.
    Т.е. чтобы удалить все моды игры, нужно пройтись парсингом по каждому моду.
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        await tools.delete_resources(owner_type='games', owner_id=game_id)

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
