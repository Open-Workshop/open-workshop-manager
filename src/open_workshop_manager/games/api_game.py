"""Game management routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, Form, Path, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, func, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    MAIN_URL + "/games",
    tags=["Game"],
    summary="Список игр.",
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
    MAIN_URL + "/list/games/",
    tags=["Game"],
    summary="Список игр.",
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
async def games_list(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    sort: str = Query(
        "MODS_DOWNLOADS",
        description="Сортировка. Префикс `i` указывает что сортировка должна быть инвертированной.",
    ),
    name: str = Query("", description="Фильтр по заголовку/названию."),
    type_app=Query(
        [],
        description="Фильтр по типу *(`game` и/или `app`)*.",
        example="['game','app']",
    ),
    genres=Query(
        [],
        description="Фильтр по жанрам. Передать id интересующих жанров.",
        example="[1,2]",
    ),
    primary_sources=Query(
        [],
        description="Фильтр по источникам. Передать названия источников.",
        example="['local','steam']",
    ),
    allowed_sources_ids=Query(
        [],
        description="Фильтр по source_id. Передать id в источниках (не работает если не передан `primary_sources`).",
        example="[1,2]",
    ),
    allowed_ids=Query(
        [], description="Фильтр по id. Передать id игр.", example="[1,2]"
    ),
    short_description: bool = Query(
        False, description="Отправлять ли короткое описание."
    ),
    description: bool = Query(False, description="Отправлять ли описание."),
    dates: bool = Query(False, description="Отправлять ли даты (дата создания)."),
    statistics: bool = Query(
        False,
        description="Отправлять ли статистику (количество модов и их общее количество скачиваний).",
    ),
):
    genres = tools.str_to_list(genres)
    type_app = tools.str_to_list(type_app)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)
    allowed_sources_ids = tools.str_to_list(allowed_sources_ids)

    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 1},
        )
    if (
        len(type_app)
        + len(genres)
        + len(primary_sources)
        + len(allowed_ids)
        + len(allowed_sources_ids)
    ) > LIMITS.game.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 80 elements in sum",
            instance=str(request.url),
            context={"error_id": 2},
        )

    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Game)
        list_stmt = select(catalog.Game)
        list_stmt = list_stmt.order_by(tools.sort_games(sort))

        if allowed_ids:
            condition = catalog.Game.id.in_(allowed_ids)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if genres:
            for genre in genres:
                logger.debug("Genre filter type=%s", type(genre))
                count_stmt = count_stmt.where(catalog.Game.genres.any(id=genre))
                list_stmt = list_stmt.where(catalog.Game.genres.any(id=genre))

        if primary_sources:
            condition = catalog.Game.source.in_(primary_sources)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)
            if allowed_sources_ids:
                condition = catalog.Game.source_id.in_(allowed_sources_ids)
                count_stmt = count_stmt.where(condition)
                list_stmt = list_stmt.where(condition)

        if type_app:
            condition = catalog.Game.type.in_(type_app)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if name:
            condition = catalog.Game.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        games_count = int((await session.execute(count_stmt)).scalar_one())
        offset = page_size * page
        games = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

    output_games = []
    for game in games:
        out = {
            "id": game.id,
            "name": game.name,
            "type": game.type,
            "source": game.source,
            "source_id": game.source_id,
        }
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

    return {"database_size": games_count, "offset": offset, "results": output_games}


@router.get(
    MAIN_URL + "/games/{game_id}",
    tags=["Game"],
    summary="Информация об игре",
    status_code=200,
    responses={
        200: {"description": "OK"},
        404: {"description": "Игра не найдена."},
    },
)
async def game_info(
    request: Request,
    game_id: int = Path(description="ID игры"),
    short_description: bool = Query(
        False, description="Отправлять ли короткое описание."
    ),
    description: bool = Query(False, description="Отправлять ли описание."),
    dates: bool = Query(False, description="Отправлять ли даты (дата создания)."),
    statistics: bool = Query(
        False,
        description="Отправлять ли статистику (количество модов и их общее количество скачиваний).",
    ),
):
    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Game).where(catalog.Game.id == game_id)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if not row:
        raise standarts.NotFoundError(
            detail="Game not found.",
            instance=str(request.url),
        )

    out = {
        "id": row.id,
        "name": row.name,
        "type": row.type,
        "source": row.source,
        "source_id": row.source_id,
    }
    if description:
        out["description"] = row.description
    if short_description:
        out["short_description"] = row.short_description
    if dates:
        out["creation_date"] = row.creation_date
    if statistics:
        out["mods_count"] = row.mods_count
        out["mods_downloads"] = row.mods_downloads

    return out


@router.post(
    MAIN_URL + "/add/game",
    tags=["Game"],
    summary="Добавление игры",
    status_code=202,
    responses={
        202: {
            "description": "Возвращает ID созданной игры",
            "content": {"application/json": {"example": 123}},
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def add_game(
    response: Response,
    request: Request,
    game_name: str = Form(..., description="Название игры", max_length=LIMITS.game.name_max),
    game_short_desc: str = Form(
        ..., description="Краткое описание игры", max_length=LIMITS.game.short_desc_max
    ),
    game_desc: str = Form(
        ..., description="Полное описание игры", max_length=LIMITS.game.desc_max
    ),
    game_type: str = Form("game", description="Тип игры", max_length=LIMITS.game.type_max),
):
    access_result = await tools.access_admin(response=response, request=request)
    if access_result is not True:
        return access_result

    async with catalog.AsyncSessionLocal() as session:
        new_game = catalog.Game(
            name=game_name,
            type=game_type,
            short_description=game_short_desc,
            description=game_desc,
            mods_downloads=0,
            mods_count=0,
            creation_date=datetime.now(),
            source="local",
        )
        session.add(new_game)
        await session.flush()
        game_id = int(new_game.id)
        await session.commit()

    return JSONResponse(status_code=202, content=game_id)


@router.post(
    MAIN_URL + "/edit/game",
    tags=["Game"],
    summary="Редактирование игры",
    status_code=202,
    responses={
        202: {"description": "Изменение данных в базе данных по указанному ID игры."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Игра не найдена."},
        412: {"description": "Такая source-связка уже существует."},
        418: {"description": "Пустой запрос. Возникает если не передан ни один из параметров-свойств."},
    },
)
async def edit_game(
    response: Response,
    request: Request,
    game_id: int = Form(..., description="ID игры для редактирования"),
    game_name: str = Form(None, description="Название игры", max_length=LIMITS.game.name_max),
    game_short_desc: str = Form(
        None, description="Краткое описание игры", max_length=LIMITS.game.short_desc_max
    ),
    game_desc: str = Form(None, description="Полное описание игры", max_length=LIMITS.game.desc_max),
    game_type: str = Form(None, description="Тип игры", max_length=LIMITS.game.type_max),
    game_source: str = Form(
        None,
        description="Источник игры. Так же обязательно передавать и `game_source_id`!",
        max_length=LIMITS.game.source_max,
    ),
    game_source_id: int = Form(None, description="ID игры в первоисточнике"),
) -> Response:
    await tools.access_admin(response=response, request=request)

    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if not game:
            raise standarts.NotFoundError(
                detail="The element does not exist.",
                instance=str(request.url),
            )

        data_edit: dict[str, object] = {}
        if game_name:
            data_edit["name"] = game_name
        if game_short_desc:
            data_edit["short_description"] = game_short_desc
        if game_desc:
            data_edit["description"] = game_desc
        if game_type:
            data_edit["type"] = game_type
        if game_source:
            data_edit["source"] = game_source
            data_edit["source_id"] = game_source_id

            exists = (
                await session.execute(
                    select(catalog.Game).where(
                        catalog.Game.source == game_source,
                        catalog.Game.source_id == game_source_id,
                    )
                )
            ).scalar_one_or_none()
            if exists:
                raise standarts.PreconditionFailedError(
                    detail="The element already exists",
                    instance=str(request.url),
                )

        if len(data_edit) <= 0:
            raise standarts.RequestRejectedError(
                detail="The request is empty",
                instance=str(request.url),
                )

        for key, value in data_edit.items():
            setattr(game, key, value)
        await session.commit()

    return PlainTextResponse(status_code=202, content="Complite")


@router.delete(
    MAIN_URL + "/delete/game",
    tags=["Game"],
    summary="Удаление игры",
    status_code=202,
    responses={
        202: {"description": "Успешно"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def delete_game(
    response: Response,
    request: Request,
    game_id: int = Form(..., description="ID игры для удаления"),
):
    access_result = await tools.access_admin(response=response, request=request)
    if access_result is not True:
        return access_result

    await tools.delete_resources(owner_type="games", owner_id=game_id)

    async with catalog.AsyncSessionLocal() as session:
        delete_game_stmt = delete(catalog.Game).where(catalog.Game.id == game_id)
        delete_genres_association = catalog.game_genres.delete().where(
            catalog.game_genres.c.game_id == game_id
        )
        delete_tags_association = catalog.allowed_mods_tags.delete().where(
            catalog.allowed_mods_tags.c.game_id == game_id
        )

        await session.execute(delete_game_stmt)
        await session.execute(delete_genres_association)
        await session.execute(delete_tags_association)
        await session.commit()

    return JSONResponse(status_code=202, content="Complite")
