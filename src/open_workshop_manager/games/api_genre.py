"""Genre management routes."""

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


@router.get(
    MAIN_URL + "/list/genres",
    tags=["Genre"],
    summary="Список жанров игр",
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
async def list_genres(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    name: str = Query(
        "", description="Поиск по названию.", max_length=LIMITS.genre.name_max
    ),
):
    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 1},
        )

    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Genre)
        list_stmt = select(catalog.Genre)
        if len(name) > 0:
            condition = catalog.Genre.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        genres_count = int((await session.execute(count_stmt)).scalar_one())
        offset = page_size * page
        genres = (
            await session.execute(list_stmt.offset(offset).limit(page_size))
        ).scalars().all()

    return {"database_size": genres_count, "offset": offset, "results": genres}


@router.post(
    MAIN_URL + "/add/genre",
    tags=["Genre"],
    summary="Добавляет жанр",
    status_code=202,
    responses={
        202: {
            "description": "Возвращает ID добавленного жанра.",
        },
        401: standarts.responses[401],
        403: standarts.responses["admin"][403],
    },
)
async def add_genre(
    response: Response,
    request: Request,
    genre_name: str = Form(
        ..., description="Название добавляемого жанра", max_length=LIMITS.genre.name_max
    ),
):
    access_result = await tools.access_admin(response=response, request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            new_genre = catalog.Genre(name=genre_name)
            session.add(new_genre)
            await session.flush()
            genre_id = int(new_genre.id)  # Получаем ID последней вставленной строки

            await session.commit()

        return JSONResponse(status_code=202, content=genre_id)  # Возвращаем значение `id`
    else:
        return access_result


@router.post(
    MAIN_URL + "/edit/genre",
    tags=["Genre"],
    summary="Редактирует жанр",
    status_code=202,
    responses={
        202: {"description": "Изменение данных в базе данных по указанному ID жанра."},
        401: standarts.responses[401],
        403: standarts.responses["admin"][403],
        404: {"description": "Жанр не найден."},
        418: {
            "description": "Пустой запрос. Возникает если не передан ни один из параметров-свойств."
        },
    },
)
async def edit_genre(
    response: Response,
    request: Request,
    genre_id: int = Form(..., description="ID жанра для редактирования"),
    genre_name: str = Form(
        None, description="Название жанра", max_length=LIMITS.genre.name_max
    ),
):
    access_result = await tools.access_admin(response=response, request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            genre = await session.get(catalog.Genre, genre_id)
            if not genre:
                raise standarts.NotFoundError(
                    detail="The element does not exist.",
                    instance=str(request.url),
                )

            # Подготавливаем данные
            data_edit = {}
            if genre_name:
                data_edit["name"] = genre_name

            if len(data_edit) <= 0:
                raise standarts.RequestRejectedError(
                    detail="The request is empty",
                    instance=str(request.url),
                )

            for key, value in data_edit.items():
                setattr(genre, key, value)
            await session.commit()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result


@router.delete(
    MAIN_URL + "/delete/genre",
    tags=["Genre"],
    summary="Удаляет жанр",
    status_code=202,
    responses={
        202: {"description": "Удалено успешно."},
        401: standarts.responses[401],
        403: standarts.responses["admin"][403],
    },
)
async def delete_genre(
    response: Response,
    request: Request,
    genre_id: int = Form(..., description="ID жанра для удаления"),
):
    access_result = await tools.access_admin(response=response, request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            delete_game = delete(catalog.Genre).where(catalog.Genre.id == genre_id)

            delete_genres_association = catalog.game_genres.delete().where(
                catalog.game_genres.c.genre_id == genre_id
            )

            # Выполнение операции DELETE
            await session.execute(delete_game)
            await session.execute(delete_genres_association)
            await session.commit()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
