"""Association lookup routes."""

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import func, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


@router.get(
    MAIN_URL + "/tags",
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
                        ],
                    }
                }
            },
        },
        413: {
            "description": "Неккоректный диапазон параметров(размеров).",
            "content": {
                "application/json": {
                    "example": {"message": "incorrect page size", "error_id": 1}
                }
            },
        },
    },
)
@router.get(
    MAIN_URL + "/list/tags",
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
                        ],
                    }
                }
            },
        },
        413: {
            "description": "Неккоректный диапазон параметров(размеров).",
            "content": {
                "application/json": {
                    "example": {"message": "incorrect page size", "error_id": 1}
                }
            },
        },
    },
)
async def list_tags(
    request: Request,
    game_id: int = Query(
        -1, description="ID игры *(для активации фильтра значение `>0`)*."
    ),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    name: str = Query(
        "", description="Поиск по названию.", max_length=LIMITS.tag.name_max
    ),
    tags_ids=Query(
        [], description="Фильтрация по id тегов *(массив id)*.", example="[1, 2, 3]"
    ),
):
    """
    Возвращает список тегов. Они могут быть отфильтрованны по закрепленности за конкретной игрой.
    """
    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 1},
        )

    tags_ids = tools.str_to_list(tags_ids)

    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Tag)
        list_stmt = select(catalog.Tag)
        if game_id > 0:
            condition = catalog.Tag.associated_games.any(catalog.Game.id == game_id)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)
        if len(name) > 0:
            condition = catalog.Tag.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if len(tags_ids) > 0:
            count_stmt = count_stmt.where(catalog.Tag.id.in_(tags_ids))
            list_stmt = list_stmt.where(catalog.Tag.id.in_(tags_ids))

        tags_count = int((await session.execute(count_stmt)).scalar_one())
        offset = page_size * page
        tags = (
            await session.execute(list_stmt.offset(offset).limit(page_size))
        ).scalars().all()

    return {"database_size": tags_count, "offset": offset, "results": tags}


@router.get(
    MAIN_URL + "/list/tags/mods/{mods_ids_list}",
    tags=["Mod", "Tag", "Association"],
    summary="Ассоциации модов с тегами",
    status_code=200,
    responses={
        200: {
            "description": "OK",
            "content": {
                "application/json": {
                    "example": {
                        1: [{"id": 1, "name": "tag1"}, {"id": 2, "name": "tag2"}]
                    }
                }
            },
        }
    },
)
async def list_tags_for_mods(
    response: Response,
    request: Request,
    mods_ids_list=Path(
        description="Список модов к которым нужно вернуть ассоциации.",
        example="[1, 2, 3]",
    ),
    tags=Query(
        [],
        description="Список тегов ассоциации с которыми интересуют.",
        example="[1, 2, 3]",
    ),
    only_ids: bool = Query(
        False,
        description="Если True вернет только ID тегов, если False вернет все данные о теге.",
    ),
):
    """
    Возвращает ассоциации модов с тегами.
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    tags = tools.str_to_list(tags)

    if (len(mods_ids_list) + len(tags)) > LIMITS.association.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 80 elements in sum",
            instance=str(request.url),
            context={"error_id": 1},
        )

    async with catalog.AsyncSessionLocal() as session:
        result = await session.execute(
            select(catalog.Mod.id).where(catalog.Mod.id.in_(mods_ids_list))
        )
        if len(result.scalars().all()) > 0:
            result_access = await tools.access_mods(
                response=response, request=request, mods_ids=mods_ids_list
            )
            if not result_access:
                return result_access

        if only_ids:
            result_ids: dict[int, list[int]] = {}
            for mod_id in mods_ids_list:
                query = select(catalog.Tag.id).join(catalog.mods_tags).where(
                    catalog.mods_tags.c.mod_id == mod_id
                )
                if len(tags) > 0:
                    query = query.where(catalog.Tag.id.in_(tags))

                result_ids[mod_id] = list((await session.execute(query)).scalars().all())

            return result_ids

        result_rows: dict[int, list[catalog.Tag]] = {}
        for mod_id in mods_ids_list:
            query = select(catalog.Tag).join(catalog.mods_tags).where(
                catalog.mods_tags.c.mod_id == mod_id
            )
            if len(tags) > 0:
                query = query.where(catalog.Tag.id.in_(tags))

            result_rows[mod_id] = list((await session.execute(query)).scalars().all())

        return result_rows


@router.get(
    MAIN_URL + "/list/genres/games/{games_ids_list}",
    tags=["Game", "Genre", "Association"],
    summary="Ассоциации игр с жанрами",
    status_code=200,
    responses={
        200: {
            "description": "Запрос успешно обработан.",
            "content": {
                "application/json": {"example": {123: [{"id": 1, "name": "Стратегия"}]}}
            },
        },
        413: {
            "description": "Превышен максимальный размер сложности фильтрации.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "the maximum complexity of filters is 80 elements in sum",
                        "error_id": 2,
                    }
                }
            },
        },
    },
)
async def list_genres_for_games(
    request: Request,
    games_ids_list=Path(
        ..., description="Список ID запрошенных игр.", example="[1, 2, 3]"
    ),
    genres=Query(
        [],
        description="Фильтрация по ID жанров (т.е. если жанра нет в переденном списке, он не передается). Неактивен если пуст.",
        example="[1, 2, 3]",
    ),
    only_ids: bool = Query(
        False,
        description="Возвращать только массив ID жанров. В обычной ситуации возвращает массив словарей с подробной информацией.",
    ),
):
    """
    Передает информацию о жанрах запрошенных игр.
    """
    games_ids_list = tools.str_to_list(games_ids_list)
    genres = tools.str_to_list(genres)

    if (len(games_ids_list) + len(genres)) > LIMITS.association.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 80 elements in sum",
            instance=str(request.url),
            context={"error_id": 2},
        )

    async with catalog.AsyncSessionLocal() as session:
        if only_ids:
            result_ids: dict[int, list[int]] = {}
            for game_id in games_ids_list:
                query = select(catalog.Genre.id).join(catalog.game_genres).where(
                    catalog.game_genres.c.game_id == game_id
                )
                if len(genres) > 0:
                    query = query.where(catalog.Genre.id.in_(genres))

                result_ids[game_id] = list((await session.execute(query)).scalars().all())

            return result_ids

        result_rows: dict[int, list[catalog.Genre]] = {}
        for game_id in games_ids_list:
            query = select(catalog.Genre).join(catalog.game_genres).where(
                catalog.game_genres.c.game_id == game_id
            )
            if len(genres) > 0:
                query = query.where(catalog.Genre.id.in_(genres))

            result_rows[game_id] = list((await session.execute(query)).scalars().all())

        return result_rows
