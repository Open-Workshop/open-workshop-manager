"""Association control routes."""

from typing import Any

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import insert, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

ASSOCIATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    202: {
        "description": "Запрос успешно обработан.",
        "content": {"application/json": {"example": "Complite"}},
    },
    409: {
        "description": "Запрашиваемое состояние уже реализовано.",
        "content": {
            "application/json": {"example": "The association is already present"}
        },
    },
}


async def association_game_with_genre(
    response: Response,
    request: Request,
    game_id: int,
    mode: bool,
    genre_id: int,
):
    access_result = await tools.access_admin(request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            if mode:
                result = await session.execute(
                    select(catalog.game_genres).where(
                        catalog.game_genres.c.game_id == game_id,
                        catalog.game_genres.c.genre_id == genre_id,
                    )
                )
                output = result.first()
                if output is None:
                    insert_statement = insert(catalog.game_genres).values(
                        game_id=game_id, genre_id=genre_id
                    )
                    await session.execute(insert_statement)
                    await session.commit()
                    return JSONResponse(status_code=202, content="Complite")
                else:
                    raise standarts.ConflictError(
                        detail="The association is already present",
                        instance=str(request.url),
                    )
            else:
                delete_genre_association = catalog.game_genres.delete().where(
                    catalog.game_genres.c.game_id == game_id,
                    catalog.game_genres.c.genre_id == genre_id,
                )

                # Выполнение операции DELETE
                await session.execute(delete_genre_association)
                await session.commit()
                return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result


@router.post(
    MAIN_URL + "/games/{game_id}/genres/{genre_id}",
    tags=["Association", "Game", "Genre"],
    summary="Добавление жанра игре",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def game_add_genre(
    response: Response,
    request: Request,
    game_id: int = Path(description="ID игры"),
    genre_id: int = Path(description="ID жанра"),
):
    return await association_game_with_genre(
        response=response,
        request=request,
        game_id=game_id,
        mode=True,
        genre_id=genre_id,
    )


@router.delete(
    MAIN_URL + "/games/{game_id}/genres/{genre_id}",
    tags=["Association", "Game", "Genre"],
    summary="Удаление жанра у игры",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def game_delete_genre(
    response: Response,
    request: Request,
    game_id: int = Path(description="ID игры"),
    genre_id: int = Path(description="ID жанра"),
):
    return await association_game_with_genre(
        response=response,
        request=request,
        game_id=game_id,
        mode=False,
        genre_id=genre_id,
    )


@router.post(
    MAIN_URL + "/mods/{mod_id}/dependencies/{dependencie_id}",
    tags=["Association", "Mod"],
    summary="Добавление зависимости мода",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def mod_add_dependency(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    dependencie_id: int = Path(description="ID зависимости (мода)"),
):
    return await association_mod_with_dependencie(
        response=response,
        request=request,
        mod_id=mod_id,
        mode=True,
        dependencie=dependencie_id,
    )


@router.delete(
    MAIN_URL + "/mods/{mod_id}/dependencies/{dependencie_id}",
    tags=["Association", "Mod"],
    summary="Удаление зависимости мода",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def mod_delete_dependency(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    dependencie_id: int = Path(description="ID зависимости (мода)"),
):
    return await association_mod_with_dependencie(
        response=response,
        request=request,
        mod_id=mod_id,
        mode=False,
        dependencie=dependencie_id,
    )


async def association_game_with_tag(
    response: Response,
    request: Request,
    game_id: int,
    mode: bool,
    tag_id: int,
):
    access_result = await tools.access_admin(request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            if mode:
                result = await session.execute(
                    select(catalog.allowed_mods_tags).where(
                        catalog.allowed_mods_tags.c.game_id == game_id,
                        catalog.allowed_mods_tags.c.tag_id == tag_id,
                    )
                )
                output = result.first()
                if output is None:
                    insert_statement = insert(catalog.allowed_mods_tags).values(
                        game_id=game_id, tag_id=tag_id
                    )
                    await session.execute(insert_statement)
                    await session.commit()
                    return JSONResponse(status_code=202, content="Complite")
                else:
                    raise standarts.ConflictError(
                        detail="The association is already present",
                        instance=str(request.url),
                    )
            else:
                delete_tags_association = catalog.allowed_mods_tags.delete().where(
                    catalog.allowed_mods_tags.c.game_id == game_id,
                    catalog.allowed_mods_tags.c.tag_id == tag_id,
                )

                # Выполнение операции DELETE
                await session.execute(delete_tags_association)
                await session.commit()
                return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result


async def association_mod_with_tag(
    response: Response,
    request: Request,
    mod_id: int,
    mode: bool,
    tag_id: int,
):
    access_result = await tools.access_mods(
        request=request, mods_ids=mod_id
    )

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            if mode:
                result = await session.execute(
                    select(catalog.mods_tags).where(
                        catalog.mods_tags.c.mod_id == mod_id,
                        catalog.mods_tags.c.tag_id == tag_id,
                    )
                )
                output = result.first()
                if output is None:
                    insert_statement = insert(catalog.mods_tags).values(
                        mod_id=mod_id, tag_id=tag_id
                    )
                    await session.execute(insert_statement)
                    await session.commit()
                    return JSONResponse(status_code=202, content="Complite")
                else:
                    raise standarts.ConflictError(
                        detail="The association is already present",
                        instance=str(request.url),
                    )
            else:
                delete_tags_association = catalog.mods_tags.delete().where(
                    catalog.mods_tags.c.mod_id == mod_id,
                    catalog.mods_tags.c.tag_id == tag_id,
                )

                # Выполнение операции DELETE
                await session.execute(delete_tags_association)
                await session.commit()
                return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result


@router.post(
    MAIN_URL + "/games/{game_id}/tags/{tag_id}",
    tags=["Association", "Game", "Tag"],
    summary="Добавление тега игре",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def game_add_tag(
    response: Response,
    request: Request,
    game_id: int = Path(description="ID игры"),
    tag_id: int = Path(description="ID тега"),
):
    return await association_game_with_tag(
        response=response,
        request=request,
        game_id=game_id,
        mode=True,
        tag_id=tag_id,
    )


@router.delete(
    MAIN_URL + "/games/{game_id}/tags/{tag_id}",
    tags=["Association", "Game", "Tag"],
    summary="Удаление тега у игры",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def game_delete_tag(
    response: Response,
    request: Request,
    game_id: int = Path(description="ID игры"),
    tag_id: int = Path(description="ID тега"),
):
    return await association_game_with_tag(
        response=response,
        request=request,
        game_id=game_id,
        mode=False,
        tag_id=tag_id,
    )


@router.post(
    MAIN_URL + "/mods/{mod_id}/tags/{tag_id}",
    tags=["Association", "Mod", "Tag"],
    summary="Добавление тега модификации",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def mod_add_tag(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    tag_id: int = Path(description="ID тега"),
):
    return await association_mod_with_tag(
        response=response,
        request=request,
        mod_id=mod_id,
        mode=True,
        tag_id=tag_id,
    )


@router.delete(
    MAIN_URL + "/mods/{mod_id}/tags/{tag_id}",
    tags=["Association", "Mod", "Tag"],
    summary="Удаление тега модификации",
    status_code=202,
    responses=ASSOCIATION_RESPONSES
    | {
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def mod_delete_tag(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    tag_id: int = Path(description="ID тега"),
):
    return await association_mod_with_tag(
        response=response,
        request=request,
        mod_id=mod_id,
        mode=False,
        tag_id=tag_id,
    )


async def association_mod_with_dependencie(
    response: Response,
    request: Request,
    mod_id: int,
    mode: bool,
    dependencie: int,
):
    """
    Создание ассоциативной зависимости между модом и другим модом в качестве зависимости.
    """
    access_result = await tools.access_mods(
        request=request, mods_ids=mod_id
    )

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            if mode:
                result = await session.execute(
                    select(catalog.mods_dependencies).where(
                        catalog.mods_dependencies.c.mod_id == mod_id,
                        catalog.mods_dependencies.c.dependence == dependencie,
                    )
                )
                output = result.first()
                if output is None:
                    insert_statement = insert(catalog.mods_dependencies).values(
                        mod_id=mod_id, dependence=dependencie
                    )
                    await session.execute(insert_statement)
                    await session.commit()
                    return JSONResponse(status_code=202, content="Complite")
                else:
                    raise standarts.ConflictError(
                        detail="The association is already present",
                        instance=str(request.url),
                    )
            else:
                delete_dependence_association = catalog.mods_dependencies.delete().where(
                    catalog.mods_dependencies.c.mod_id == mod_id,
                    catalog.mods_dependencies.c.dependence == dependencie,
                )

                # Выполнение операции DELETE
                await session.execute(delete_dependence_association)
                await session.commit()
                return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
