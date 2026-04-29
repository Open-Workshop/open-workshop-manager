"""Association mutation routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, func, insert, select, update

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_models import ModAuthorUpsert
from open_workshop_manager.sql_logic import sql_account as account
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
    summary="Add game genre",
    description="Associates a genre with a game.",
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
    summary="Remove game genre",
    description="Removes a genre association from a game.",
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
    summary="Allow game tag",
    description="Allows a tag for a game.",
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
    summary="Disallow game tag",
    description="Removes a tag allowance from a game.",
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
    summary="Add mod dependency",
    description="Adds a dependency between two mods.",
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
    summary="Remove mod dependency",
    description="Removes a dependency between two mods.",
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
    summary="Add mod tag",
    description="Associates a tag with a mod.",
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
    summary="Remove mod tag",
    description="Removes a tag association from a mod.",
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


@router.put(
    "/mods/{mod_id}/authors/{author_id}",
    tags=["Association", "Mod", "Author"],
    summary="Set mod author",
    description="Creates or updates a mod author assignment. When owner is true, this author becomes the owner and other authors are demoted.",
    status_code=204,
)
async def put_mod_author(request: Request, mod_id: int, author_id: int, payload: ModAuthorUpsert):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.mod_and_author.c.owner).where(
                account.mod_and_author.c.mod_id == mod_id,
                account.mod_and_author.c.user_id == author_id,
            )
        )

        if payload.owner:
            await session.execute(
                update(account.mod_and_author)
                .where(account.mod_and_author.c.mod_id == mod_id)
                .where(account.mod_and_author.c.user_id != author_id)
                .values(owner=False)
            )

        if relation_owner is None:
            await session.execute(
                insert(account.mod_and_author).values(
                    mod_id=mod_id,
                    user_id=author_id,
                    owner=bool(payload.owner),
                )
            )
            await session.execute(
                update(account.Account)
                .where(account.Account.id == author_id)
                .values(author_mods=func.coalesce(account.Account.author_mods, 0) + 1)
            )
        else:
            await session.execute(
                update(account.mod_and_author)
                .where(account.mod_and_author.c.mod_id == mod_id)
                .where(account.mod_and_author.c.user_id == author_id)
                .values(owner=bool(payload.owner))
            )

        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/mods/{mod_id}/authors/{author_id}",
    tags=["Association", "Mod", "Author"],
    summary="Remove mod author",
    description="Removes a mod author assignment.",
    status_code=204,
)
async def delete_mod_author(request: Request, mod_id: int, author_id: int):
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)
    await _ensure_mod_exists(request, mod_id)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.mod_and_author.c.owner).where(
                account.mod_and_author.c.mod_id == mod_id,
                account.mod_and_author.c.user_id == author_id,
            )
        )

        if relation_owner is not None:
            await session.execute(
                delete(account.mod_and_author).where(
                    account.mod_and_author.c.mod_id == mod_id,
                    account.mod_and_author.c.user_id == author_id,
                )
            )
            await session.execute(
                update(account.Account)
                .where(account.Account.id == author_id)
                .values(author_mods=func.coalesce(account.Account.author_mods, 0) - 1)
            )

        await session.commit()

    return Response(status_code=204)
