from fastapi import APIRouter, Request, Response, Query, Path
from fastapi.responses import JSONResponse
import tools
from ow_config import MAIN_URL
from limits import LIMITS
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert
from sql_logic import sql_catalog as catalog


router = APIRouter()


@router.get(
    MAIN_URL+"/tags",
    tags=["Tag", "Game", "Association"],
    summary="Ассоциации тегов с играми",
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
                            {"id": 1, "name": "?"},
                            {"id": 2, "name": "!"},
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
    },
)
@router.get(
    MAIN_URL+"/list/tags",
    tags=["Tag", "Game", "Association"],
    summary="Ассоциации тегов с играми",
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
                            {"id": 1, "name": "?"},
                            {"id": 2, "name": "!"},
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
        }
    }
)
async def list_tags(
    game_id: int = Query(-1, description="ID игры *(для активации фильтра значение `>0`)*."),
    page_size: int = Query(LIMITS.page.default, description="Размер 1 страницы. Диапазон - 1...50 элементов."),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    name: str = Query("", description="Поиск по названию.", max_length=LIMITS.tag.name_max),
    tags_ids = Query([], description="Фильтрация по id тегов *(массив id)*.", example="[1, 2, 3]"),
):
    """
    Возвращает список тегов. Они могут быть отфильтрованны по закрепленности за конкретной игрой.
    """
    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})

    tags_ids = tools.str_to_list(tags_ids)

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()
    # Выполнение запроса
    query = session.query(catalog.Tag)
    if game_id > 0:
        query = query.filter(catalog.Tag.associated_games.any(catalog.Game.id == game_id))
    if len(name) > 0:
        query = query.filter(catalog.Tag.name.ilike(f'%{name}%'))

    if len(tags_ids) > 0:
        query = query.filter(catalog.Tag.id.in_(tags_ids))

    tags_count = query.count()
    offset = page_size * page
    tags = query.offset(offset).limit(page_size).all()

    session.close()
    return {"database_size": tags_count, "offset": offset, "results": tags}

@router.get(
    MAIN_URL+"/list/tags/mods/{mods_ids_list}",
    tags=["Mod", "Tag", "Association"],
    summary="Ассоциации модов с тегами",
    status_code=200,
    responses={
        200: {
            "description": "OK",
            "content": {
                "application/json": {
                    "example": {
                        1: [
                            {"id": 1, "name": "tag1"},
                            {"id": 2, "name": "tag2"}
                        ]
                    }
                }
            }
        }
    }
)
async def list_tags_for_mods(
    response: Response, 
    request: Request, 
    mods_ids_list = Path(description="Список модов к которым нужно вернуть ассоциации.", example="[1, 2, 3]"), 
    tags = Query([], description="Список тегов ассоциации с которыми интересуют.", example="[1, 2, 3]"),
    only_ids: bool = Query(False, description="Если True вернет только ID тегов, если False вернет все данные о теге.")
):
    """
    Возвращает ассоциации модов с тегами.
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    tags = tools.str_to_list(tags)

    if (len(mods_ids_list) + len(tags)) > LIMITS.association.filters_max:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 1})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    query = session.query(catalog.Mod.id)
    query = query.filter(catalog.Mod.id.in_(mods_ids_list))

    if len(query.all()) > 0:
        result_access = await tools.access_mods(response=response, request=request, mods_ids=mods_ids_list)
        if result_access != True:
            return result_access

    # Выполнение запроса
    result = {}
    query_global = session.query(catalog.Tag).join(catalog.mods_tags)
    for mod_id in mods_ids_list:
        query = query_global.filter(catalog.mods_tags.c.mod_id == mod_id)
        if len(tags) > 0:
            query = query.filter(catalog.Tag.id.in_(tags))

        if only_ids:
            if result.get(mod_id, None) == None: result[mod_id] = []
            for id in query.all(): result[mod_id].append(id.id)
        else:
            result[mod_id] = query.all()

    return result

@router.get(
    MAIN_URL+"/list/genres/games/{games_ids_list}", 
    tags=["Game", "Genre", "Association"],
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
    genres = Query([], description="Фильтрация по ID жанров (т.е. если жанра нет в переденном списке, он не передается). Неактивен если пуст.", example="[1, 2, 3]"),
    only_ids: bool = Query(False, description="Возвращать только массив ID жанров. В обычной ситуации возвращает массив словарей с подробной информацией."),
):
    """
    Передает информацию о жанрах запрошенных игр.
    """
    games_ids_list = tools.str_to_list(games_ids_list)
    genres = tools.str_to_list(genres)

    if (len(games_ids_list) + len(genres)) > LIMITS.association.filters_max:
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
