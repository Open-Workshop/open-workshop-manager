"""Association mutation routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, insert, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


def _raise_not_found(request: Request, code: str, detail: str) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail=detail,
        code=code,
        instance=str(request.url),
    )


def _raise_conflict(request: Request, code: str, detail: str) -> None:
    raise standarts.StandardAPIError(
        status_code=409,
        title="Conflict",
        detail=detail,
        code=code,
        instance=str(request.url),
    )


async def _ensure_game_exists(request: Request, game_id: int) -> None:
    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
    if game is None:
        _raise_not_found(request, "GAME_NOT_FOUND", "Game not found.")


async def _ensure_genre_exists(request: Request, genre_id: int) -> None:
    async with catalog.AsyncSessionLocal() as session:
        genre = await session.get(catalog.Genre, genre_id)
    if genre is None:
        _raise_not_found(request, "GENRE_NOT_FOUND", "Genre not found.")


async def _ensure_tag_exists(request: Request, tag_id: int) -> None:
    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(catalog.Tag, tag_id)
    if tag is None:
        _raise_not_found(request, "TAG_NOT_FOUND", "Tag not found.")


async def _ensure_mod_exists(request: Request, mod_id: int) -> None:
    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
    if mod is None:
        _raise_not_found(request, "MOD_NOT_FOUND", "Mod not found.")


async def _associate(
    request: Request,
    *,
    table,
    insert_values: dict[str, object],
    exists_where,
    delete_where,
    conflict_code: str,
    conflict_detail: str,
) -> None:
    async with catalog.AsyncSessionLocal() as session:
        exists = await session.execute(select(table).where(*exists_where))
        if exists.first() is not None:
            _raise_conflict(request, conflict_code, conflict_detail)
        await session.execute(insert(table).values(**insert_values))
        await session.commit()


async def _delete_assoc(request: Request, *, table, delete_where) -> None:
    async with catalog.AsyncSessionLocal() as session:
        await session.execute(delete(table).where(*delete_where))
        await session.commit()


@router.post(
    "/games/{game_id}/genres/{genre_id}",
    tags=["Association", "Game", "Genre"],
    status_code=204,
)
async def add_game_genre(request: Request, game_id: int, genre_id: int):
    await tools.access_admin(request=request)
    await _ensure_game_exists(request, game_id)
    await _ensure_genre_exists(request, genre_id)

    async with catalog.AsyncSessionLocal() as session:
        exists = await session.execute(
            select(catalog.game_genres).where(
                catalog.game_genres.c.game_id == game_id,
                catalog.game_genres.c.genre_id == genre_id,
            )
        )
        if exists.first() is not None:
            _raise_conflict(request, "ASSOCIATION_ALREADY_EXISTS", "The association is already present.")
        await session.execute(
            insert(catalog.game_genres).values(game_id=game_id, genre_id=genre_id)
        )
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/games/{game_id}/genres/{genre_id}",
    tags=["Association", "Game", "Genre"],
    status_code=204,
)
async def delete_game_genre(request: Request, game_id: int, genre_id: int):
    await tools.access_admin(request=request)
    await _ensure_game_exists(request, game_id)
    await _ensure_genre_exists(request, genre_id)

    async with catalog.AsyncSessionLocal() as session:
        await session.execute(
            delete(catalog.game_genres).where(
                catalog.game_genres.c.game_id == game_id,
                catalog.game_genres.c.genre_id == genre_id,
            )
        )
        await session.commit()

    return Response(status_code=204)


@router.post(
    "/games/{game_id}/tags/{tag_id}",
    tags=["Association", "Game", "Tag"],
    status_code=204,
)
async def add_game_tag(request: Request, game_id: int, tag_id: int):
    await tools.access_admin(request=request)
    await _ensure_game_exists(request, game_id)
    await _ensure_tag_exists(request, tag_id)

    async with catalog.AsyncSessionLocal() as session:
        exists = await session.execute(
            select(catalog.allowed_mods_tags).where(
                catalog.allowed_mods_tags.c.game_id == game_id,
                catalog.allowed_mods_tags.c.tag_id == tag_id,
            )
        )
        if exists.first() is not None:
            _raise_conflict(request, "ASSOCIATION_ALREADY_EXISTS", "The association is already present.")
        await session.execute(
            insert(catalog.allowed_mods_tags).values(game_id=game_id, tag_id=tag_id)
        )
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/games/{game_id}/tags/{tag_id}",
    tags=["Association", "Game", "Tag"],
    status_code=204,
)
async def delete_game_tag(request: Request, game_id: int, tag_id: int):
    await tools.access_admin(request=request)
    await _ensure_game_exists(request, game_id)
    await _ensure_tag_exists(request, tag_id)

    async with catalog.AsyncSessionLocal() as session:
        await session.execute(
            delete(catalog.allowed_mods_tags).where(
                catalog.allowed_mods_tags.c.game_id == game_id,
                catalog.allowed_mods_tags.c.tag_id == tag_id,
            )
        )
        await session.commit()

    return Response(status_code=204)


@router.post(
    "/mods/{mod_id}/dependencies/{dependency_mod_id}",
    tags=["Association", "Mod"],
    status_code=204,
)
async def add_mod_dependency(request: Request, mod_id: int, dependency_mod_id: int):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)
    await _ensure_mod_exists(request, dependency_mod_id)

    async with catalog.AsyncSessionLocal() as session:
        exists = await session.execute(
            select(catalog.mods_dependencies).where(
                catalog.mods_dependencies.c.mod_id == mod_id,
                catalog.mods_dependencies.c.dependence == dependency_mod_id,
            )
        )
        if exists.first() is not None:
            _raise_conflict(request, "ASSOCIATION_ALREADY_EXISTS", "The association is already present.")
        await session.execute(
            insert(catalog.mods_dependencies).values(
                mod_id=mod_id,
                dependence=dependency_mod_id,
            )
        )
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/mods/{mod_id}/dependencies/{dependency_mod_id}",
    tags=["Association", "Mod"],
    status_code=204,
)
async def delete_mod_dependency(request: Request, mod_id: int, dependency_mod_id: int):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)
    await _ensure_mod_exists(request, dependency_mod_id)

    async with catalog.AsyncSessionLocal() as session:
        await session.execute(
            delete(catalog.mods_dependencies).where(
                catalog.mods_dependencies.c.mod_id == mod_id,
                catalog.mods_dependencies.c.dependence == dependency_mod_id,
            )
        )
        await session.commit()

    return Response(status_code=204)


@router.post(
    "/mods/{mod_id}/tags/{tag_id}",
    tags=["Association", "Mod", "Tag"],
    status_code=204,
)
async def add_mod_tag(request: Request, mod_id: int, tag_id: int):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)
    await _ensure_tag_exists(request, tag_id)

    async with catalog.AsyncSessionLocal() as session:
        exists = await session.execute(
            select(catalog.mods_tags).where(
                catalog.mods_tags.c.mod_id == mod_id,
                catalog.mods_tags.c.tag_id == tag_id,
            )
        )
        if exists.first() is not None:
            _raise_conflict(request, "ASSOCIATION_ALREADY_EXISTS", "The association is already present.")
        await session.execute(
            insert(catalog.mods_tags).values(mod_id=mod_id, tag_id=tag_id)
        )
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/mods/{mod_id}/tags/{tag_id}",
    tags=["Association", "Mod", "Tag"],
    status_code=204,
)
async def delete_mod_tag(request: Request, mod_id: int, tag_id: int):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)
    await _ensure_tag_exists(request, tag_id)

    async with catalog.AsyncSessionLocal() as session:
        await session.execute(
            delete(catalog.mods_tags).where(
                catalog.mods_tags.c.mod_id == mod_id,
                catalog.mods_tags.c.tag_id == tag_id,
            )
        )
        await session.commit()

    return Response(status_code=204)
