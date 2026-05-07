"""Association lookup routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import make_list_response, unique_ints
from open_workshop_manager.api_models import GenreListResponse, GenreRead, TagListResponse
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import serialize_tag
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


def _raise_game_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Game not found.",
        code="GAME_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_mod_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Mod not found.",
        code="MOD_NOT_FOUND",
        instance=str(request.url),
    )


def _serialize_genres(rows) -> list[dict[str, object]]:
    return [GenreRead(id=int(row.id), name=str(row.name)).model_dump(mode="json", exclude_none=True) for row in rows]


def _serialize_tags(rows) -> list[dict[str, object]]:
    return [serialize_tag(row).model_dump(mode="json", exclude_none=True) for row in rows]


@router.get(
    "/games/{game_id}/genres",
    tags=["Game", "Genre", "Association"],
    summary="List game genres",
    description="Returns all genres associated with a game.",
    status_code=200,
    response_model=GenreListResponse,
    response_model_exclude_none=True,
    response_description="Paginated genre list.",
)
async def get_game_genres(request: Request, game_id: int) -> dict[str, object]:
    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if game is None:
            _raise_game_not_found(request)

        rows = (
            await session.execute(
                select(catalog.Genre)
                .join(catalog.game_genres)
                .where(catalog.game_genres.c.game_id == game_id)
                .order_by(catalog.Genre.name)
            )
        ).scalars().all()

    items = _serialize_genres(rows)
    return make_list_response(items, page=0, page_size=max(len(items), 1), total=len(items))


@router.get(
    "/games/{game_id}/tags",
    tags=["Game", "Tag", "Association"],
    summary="List game tags",
    description="Returns all tags allowed for a game.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag list.",
)
async def get_game_tags(request: Request, game_id: int) -> dict[str, object]:
    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if game is None:
            _raise_game_not_found(request)

        rows = (
            await session.execute(
                select(catalog.Tag)
                .join(catalog.allowed_mods_tags)
                .where(
                    catalog.allowed_mods_tags.c.game_id == game_id,
                    catalog.Tag.group_id.is_(None),
                )
                .order_by(catalog.Tag.name)
            )
        ).scalars().all()

    items = _serialize_tags(rows)
    return make_list_response(items, page=0, page_size=max(len(items), 1), total=len(items))


@router.get(
    "/mods/tags",
    tags=["Mod", "Tag", "Association"],
    summary="Map mod tags",
    description="Returns tags grouped by mod ID, optionally filtered to specific tags.",
    status_code=200,
)
async def get_mod_tags_map(
    request: Request,
    mod_ids: list[int] = Query(default_factory=list, description="Mod IDs to map."),
    tag_ids: list[int] = Query(default_factory=list, description="Optional tag IDs to filter by."),
    only_ids: bool = Query(default=False, description="Return only tag IDs instead of full tag objects."),
) -> dict[str, object]:
    mod_ids = unique_ints(mod_ids)
    tag_ids = unique_ints(tag_ids)

    if not mod_ids:
        return {"items_by_mod_id": {}}

    if len(mod_ids) + len(tag_ids) > LIMITS.association.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 80 elements in sum",
            instance=str(request.url),
            context={"field": "mod_ids"},
        )

    async with catalog.AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(catalog.Mod.id).where(catalog.Mod.id.in_(mod_ids))
            )
        ).scalars().all()
        if rows:
            allowed_ids = await tools.access_mods(request=request, mods_ids=mod_ids, check_mode=True)
            if len(allowed_ids) != len(mod_ids):
                raise standarts.ForbiddenError(
                    detail="Access denied.",
                    instance=str(request.url),
                )

        result: dict[str, list[object]] = {}
        for mod_id in mod_ids:
            query = select(catalog.Tag).join(catalog.mods_tags).where(
                catalog.mods_tags.c.mod_id == mod_id
            ).options(joinedload(catalog.Tag.group))
            if tag_ids:
                query = query.where(catalog.Tag.id.in_(tag_ids))
            tags = (await session.execute(query)).scalars().all()
            if only_ids:
                result[str(mod_id)] = [int(tag.id) for tag in tags]
            else:
                result[str(mod_id)] = _serialize_tags(tags)

    return {"items_by_mod_id": result}


@router.get(
    "/games/genres",
    tags=["Game", "Genre", "Association"],
    summary="Map game genres",
    description="Returns genres grouped by game ID, optionally filtered to specific genres.",
    status_code=200,
)
async def get_game_genres_map(
    request: Request,
    game_ids: list[int] = Query(default_factory=list, description="Game IDs to map."),
    genre_ids: list[int] = Query(default_factory=list, description="Optional genre IDs to filter by."),
    only_ids: bool = Query(default=False, description="Return only genre IDs instead of full genre objects."),
) -> dict[str, object]:
    game_ids = unique_ints(game_ids)
    genre_ids = unique_ints(genre_ids)

    if not game_ids:
        return {"items_by_game_id": {}}

    if len(game_ids) + len(genre_ids) > LIMITS.association.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 80 elements in sum",
            instance=str(request.url),
            context={"field": "game_ids"},
        )

    async with catalog.AsyncSessionLocal() as session:
        result: dict[str, list[object]] = {}
        for game_id in game_ids:
            query = select(catalog.Genre).join(catalog.game_genres).where(
                catalog.game_genres.c.game_id == game_id
            )
            if genre_ids:
                query = query.where(catalog.Genre.id.in_(genre_ids))
            genres = (await session.execute(query)).scalars().all()
            if only_ids:
                result[str(game_id)] = [int(genre.id) for genre in genres]
            else:
                result[str(game_id)] = _serialize_genres(genres)

    return {"items_by_game_id": result}
