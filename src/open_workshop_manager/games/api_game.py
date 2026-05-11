"""Game REST routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    GameCreate,
    GameListResponse,
    GamePatch,
    GameRead,
    GenreRead,
    ResourceRead,
    stringify_source_id,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import serialize_tag
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

GameIncludeField = Literal["short_description", "description", "dates", "statistics", "genres", "tags", "resources"]

GAME_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The request contains invalid filters or include fields.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

GAME_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Game not found.",
        code="GAME_NOT_FOUND",
    ),
    "Game not found.",
)

GAME_CONFLICT_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="Game source already exists.",
        code="GAME_SOURCE_ALREADY_EXISTS",
    ),
    "Game source already exists.",
)

GAME_INCLUDE_FIELDS = {
    "short_description",
    "description",
    "dates",
    "statistics",
    "genres",
    "tags",
    "resources",
}


def _raise_game_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Game not found.",
        code="GAME_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_unsupported_include(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported include field.",
        code="UNSUPPORTED_INCLUDE_FIELD",
        instance=str(request.url),
        context={"field": field, "allowed": sorted(GAME_INCLUDE_FIELDS)},
    )


def _raise_unsupported_sort(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported sort field.",
        code="UNSUPPORTED_SORT_FIELD",
        instance=str(request.url),
        context={
            "field": field,
            "allowed": ["name", "type", "created_at", "source", "mods_downloads", "mods_count"],
        },
    )


def _normalize_includes(request: Request, include: list[str]) -> set[str]:
    normalized = {item.strip() for item in include if item and item.strip()}
    unknown = normalized.difference(GAME_INCLUDE_FIELDS)
    if unknown:
        _raise_unsupported_include(request, sorted(unknown)[0])
    return normalized


async def _load_game_tags(session, game_id: int) -> list[catalog.Tag]:
    return (
        await session.execute(
            select(catalog.Tag)
            .join(catalog.allowed_mods_tags)
            .where(catalog.allowed_mods_tags.c.game_id == game_id)
            .options(joinedload(catalog.Tag.group))
            .order_by(catalog.Tag.group_id, catalog.Tag.name, catalog.Tag.id)
        )
    ).scalars().all()


def _serialize_game_base(row: catalog.Game) -> dict[str, object]:
    return {
        "id": int(row.id),
        "name": str(getattr(row, "name", "")),
        "short_description": getattr(row, "short_description", None),
        "description": getattr(row, "description", None),
        "type": str(getattr(row, "type", "game")),
        "source": str(getattr(row, "source", "local")),
        "source_id": stringify_source_id(getattr(row, "source_id", None)),
        "mods_count": int(getattr(row, "mods_count", 0)) if getattr(row, "mods_count", None) is not None else None,
        "mods_downloads": int(getattr(row, "mods_downloads", 0)) if getattr(row, "mods_downloads", None) is not None else None,
        "created_at": getattr(row, "creation_date", None),
    }


async def _serialize_game_with_includes(
    session,
    request: Request,
    row: catalog.Game,
    include: set[str],
) -> GameRead:
    payload = _serialize_game_base(row)

    if "short_description" not in include:
        payload.pop("short_description", None)
    if "statistics" not in include:
        payload.pop("mods_count", None)
        payload.pop("mods_downloads", None)
    if "description" not in include:
        payload.pop("description", None)
    if "dates" not in include:
        payload.pop("created_at", None)

    if "genres" in include:
        genres = (
            await session.execute(
                select(catalog.Genre)
                .join(catalog.game_genres)
                .where(catalog.game_genres.c.game_id == row.id)
                .order_by(catalog.Genre.name)
            )
        ).scalars().all()
        payload["genres"] = [GenreRead(id=int(item.id), name=item.name).model_dump(mode="json") for item in genres]

    if "tags" in include:
        tags = await _load_game_tags(session, row.id)
        payload["tags"] = [serialize_tag(item).model_dump(mode="json", exclude_none=True) for item in tags]

    if "resources" in include:
        resources = (
            await session.execute(
                select(catalog.Resource)
                .where(
                    catalog.Resource.owner_type == "games",
                    catalog.Resource.owner_id == row.id,
                )
                .order_by(catalog.Resource.sort_order, catalog.Resource.id)
            )
        ).scalars().all()
        payload["resources"] = await tools.resources_serialize(resources)

    return GameRead.model_validate(payload)


@router.get(
    "/games",
    tags=["Game"],
    summary="List games",
    description=(
        "Returns a paginated list of games.\n\n"
        "Use `include` to opt in to extra fields:\n"
        "- `short_description`\n"
        "- `description`\n"
        "- `dates`\n"
        "- `statistics`\n"
        "- `genres`\n"
        "- `tags` (including grouped tags)\n"
        "- `resources`\n\n"
        "Use `sort` with `-` for descending order."
    ),
    status_code=200,
    response_model=GameListResponse,
    response_model_exclude_none=True,
    response_description="Paginated game list.",
    responses={400: GAME_BAD_REQUEST_RESPONSE},
)
async def list_games(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of games to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    sort: str = Query(
        default="-mods_downloads",
        description="Sort field, optionally prefixed with `-` for descending order.",
    ),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.game.name_max,
        description="Case-insensitive substring filter for the game name.",
    ),
    types: list[str] = Query(default_factory=list, description="Game types to include."),
    genre_ids: list[int] = Query(
        default_factory=list,
        description="Only return games linked to all of these genre IDs.",
    ),
    sources: list[str] = Query(default_factory=list, description="Source names to filter by."),
    source_ids: list[str] = Query(
        default_factory=list,
        description="Source-specific IDs to filter by.",
    ),
    ids: list[int] = Query(default_factory=list, description="Limit results to these game IDs."),
    include: list[GameIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in each game object.",
    ),
):
    include_set = _normalize_includes(request, include)
    source_ids = [item for item in (stringify_source_id(value) for value in source_ids) if item is not None]
    sort_clause = None
    try:
        sort_clause = tools.sort_games(sort)
    except KeyError as exc:
        _raise_unsupported_sort(request, exc.args[0] if exc.args else str(exc))

    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Game)
        list_stmt = select(catalog.Game).order_by(sort_clause)

        if ids:
            count_stmt = count_stmt.where(catalog.Game.id.in_(ids))
            list_stmt = list_stmt.where(catalog.Game.id.in_(ids))

        if types:
            count_stmt = count_stmt.where(catalog.Game.type.in_(types))
            list_stmt = list_stmt.where(catalog.Game.type.in_(types))

        if sources:
            count_stmt = count_stmt.where(catalog.Game.source.in_(sources))
            list_stmt = list_stmt.where(catalog.Game.source.in_(sources))

        if source_ids:
            count_stmt = count_stmt.where(catalog.Game.source_id.in_(source_ids))
            list_stmt = list_stmt.where(catalog.Game.source_id.in_(source_ids))

        if genre_ids:
            for genre_id in genre_ids:
                condition = catalog.Game.genres.any(id=genre_id)
                count_stmt = count_stmt.where(condition)
                list_stmt = list_stmt.where(condition)

        if name:
            condition = catalog.Game.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

        items: list[dict[str, object]] = []
        for row in rows:
            payload = _serialize_game_base(row)
            if "statistics" not in include_set:
                payload.pop("mods_count", None)
                payload.pop("mods_downloads", None)
            if "short_description" not in include_set:
                payload.pop("short_description", None)
            if "description" not in include_set:
                payload.pop("description", None)
            if "dates" not in include_set:
                payload.pop("created_at", None)

            if include_set:
                serialized = await _serialize_game_with_includes(session, request, row, include_set)
                payload = serialized.model_dump(mode="json", exclude_none=True)
            items.append(payload)

    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/games/{game_id}",
    tags=["Game"],
    summary="Get game",
    description=(
        "Returns a single game by ID.\n\n"
        "Use `include` to opt in to extra fields:\n"
        "- `short_description`\n"
        "- `description`\n"
        "- `dates`\n"
        "- `statistics`\n"
        "- `genres`\n"
        "- `tags` (including grouped tags)\n"
        "- `resources`"
    ),
    status_code=200,
    response_model=GameRead,
    response_model_exclude_none=True,
    response_description="Game resource.",
    responses={400: GAME_BAD_REQUEST_RESPONSE, 404: GAME_NOT_FOUND_RESPONSE},
)
async def get_game(
    request: Request,
    game_id: int,
    include: list[GameIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in the game object.",
    ),
) -> GameRead:
    include_set = _normalize_includes(request, include)

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Game, game_id)
        if row is None:
            _raise_game_not_found(request)

        if include_set:
            return await _serialize_game_with_includes(session, request, row, include_set)
        payload = _serialize_game_base(row)
        payload.pop("short_description", None)
        payload.pop("mods_count", None)
        payload.pop("mods_downloads", None)
        payload.pop("created_at", None)
        payload.pop("description", None)
        return GameRead.model_validate(payload)


@router.post(
    "/games",
    tags=["Game"],
    summary="Create game",
    description="Creates a new game record. Admin privileges are required.",
    status_code=201,
    response_model=GameRead,
    response_model_exclude_none=True,
    response_description="Created game resource.",
    responses={403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC},
)
async def create_game(
    response: Response,
    request: Request,
    payload: GameCreate,
) -> GameRead:
    access_result = await tools.access_game_add(request=request)
    tools.require_access_right(request, access_result, access_result.add)

    async with catalog.AsyncSessionLocal() as session:
        game = catalog.Game(
            name=payload.name,
            short_description=payload.short_description,
            description=payload.description,
            type=payload.type,
            mods_downloads=0,
            mods_count=0,
            creation_date=datetime.now(),
            source="local",
            source_id=None,
        )
        session.add(game)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/games/{game.id}"
        return GameRead.model_validate(_serialize_game_base(game))


@router.patch(
    "/games/{game_id}",
    tags=["Game"],
    summary="Update game",
    description=(
        "Updates a game record.\n\n"
        "The `source` and `source_id` pair must remain unique across games. "
        "Admin privileges are required."
    ),
    status_code=200,
    response_model=GameRead,
    response_model_exclude_none=True,
    response_description="Updated game resource.",
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: GAME_NOT_FOUND_RESPONSE,
        409: GAME_CONFLICT_RESPONSE,
    },
)
async def patch_game(
    request: Request,
    game_id: int,
    payload: GamePatch,
) -> GameRead:
    access_result = await tools.access_game_action(request=request, game_id=game_id)
    edit_rights = access_result.edit
    tools.require_any_access_right(
        request,
        access_result,
        [
            edit_rights.title,
            edit_rights.description,
            edit_rights.short_description,
        ],
    )

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name", "type", "source"),
        detail="Game patch fields cannot be null.",
    )
    field_rights = {
        "name": edit_rights.title,
        "type": edit_rights.title,
        "source": edit_rights.title,
        "source_id": edit_rights.title,
        "description": edit_rights.description,
        "short_description": edit_rights.short_description,
    }
    for field_name in data:
        tools.require_access_right(request, access_result, field_rights.get(field_name))

    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if game is None:
            _raise_game_not_found(request)

        if "source" in data or "source_id" in data:
            candidate_source = data.get("source", game.source)
            candidate_source_id = stringify_source_id(data.get("source_id", game.source_id))
            if candidate_source_id is not None:
                existing = await session.scalar(
                    select(catalog.Game.id).where(
                        catalog.Game.id != game_id,
                        catalog.Game.source == candidate_source,
                        catalog.Game.source_id == candidate_source_id,
                    )
                )
                if existing is not None:
                    raise standarts.StandardAPIError(
                        status_code=409,
                        title="Conflict",
                        detail="Game source already exists.",
                        code="GAME_SOURCE_ALREADY_EXISTS",
                        instance=str(request.url),
                        context={
                            "source": candidate_source,
                            "source_id": candidate_source_id,
                        },
                    )
            game.source = candidate_source
            game.source_id = candidate_source_id
            data.pop("source", None)
            data.pop("source_id", None)

        for key, value in data.items():
            setattr(game, key, value)

        await session.commit()
        return GameRead.model_validate(_serialize_game_base(game))


@router.delete(
    "/games/{game_id}",
    tags=["Game"],
    summary="Delete game",
    description="Deletes a game and removes its association records and resources.",
    status_code=204,
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: GAME_NOT_FOUND_RESPONSE,
    },
)
async def delete_game(request: Request, game_id: int) -> Response:
    access_result = await tools.access_game_action(request=request, game_id=game_id)
    tools.require_access_right(request, access_result, access_result.delete)

    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if game is None:
            _raise_game_not_found(request)

        await tools.delete_resources(owner_type="games", owner_id=game_id)
        await session.execute(catalog.game_genres.delete().where(catalog.game_genres.c.game_id == game_id))
        await session.execute(
            catalog.allowed_mods_tags.delete().where(catalog.allowed_mods_tags.c.game_id == game_id)
        )
        await session.execute(delete(catalog.Game).where(catalog.Game.id == game_id))
        await session.commit()

    return Response(status_code=204)
