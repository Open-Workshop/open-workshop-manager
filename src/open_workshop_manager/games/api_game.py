"""Game REST routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select

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
    TagRead,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

GAME_INCLUDE_FIELDS = {
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


def _serialize_game_base(row: catalog.Game) -> dict[str, object]:
    return {
        "id": int(row.id),
        "name": str(getattr(row, "name", "")),
        "short_description": getattr(row, "short_description", None),
        "description": getattr(row, "description", None),
        "type": str(getattr(row, "type", "game")),
        "source": str(getattr(row, "source", "local")),
        "source_id": getattr(row, "source_id", None),
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
        tags = (
            await session.execute(
                select(catalog.Tag)
                .join(catalog.allowed_mods_tags)
                .where(catalog.allowed_mods_tags.c.game_id == row.id)
                .order_by(catalog.Tag.name)
            )
        ).scalars().all()
        payload["tags"] = [TagRead(id=int(item.id), name=item.name).model_dump(mode="json") for item in tags]

    if "resources" in include:
        resources = (
            await session.execute(
                select(catalog.Resource)
                .where(
                    catalog.Resource.owner_type == "games",
                    catalog.Resource.owner_id == row.id,
                )
                .order_by(catalog.Resource.id)
            )
        ).scalars().all()
        payload["resources"] = await tools.resources_serialize(resources)

    return GameRead.model_validate(payload)


@router.get(
    "/games",
    tags=["Game"],
    status_code=200,
    response_model=GameListResponse,
    response_model_exclude_none=True,
)
async def list_games(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
    ),
    page: int = Query(0, ge=0),
    sort: str = Query(default="-mods_downloads"),
    name: str | None = Query(default=None, max_length=LIMITS.game.name_max),
    types: list[str] = Query(default_factory=list),
    genre_ids: list[int] = Query(default_factory=list),
    sources: list[str] = Query(default_factory=list),
    source_ids: list[int] = Query(default_factory=list),
    ids: list[int] = Query(default_factory=list),
    include: list[str] = Query(default_factory=list),
):
    include_set = _normalize_includes(request, include)
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
    status_code=200,
    response_model=GameRead,
    response_model_exclude_none=True,
)
async def get_game(
    request: Request,
    game_id: int,
    include: list[str] = Query(default_factory=list),
) -> GameRead:
    include_set = _normalize_includes(request, include)

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Game, game_id)
        if row is None:
            _raise_game_not_found(request)

        if include_set:
            return await _serialize_game_with_includes(session, request, row, include_set)
        payload = _serialize_game_base(row)
        payload.pop("description", None)
        return GameRead.model_validate(payload)


@router.post(
    "/games",
    tags=["Game"],
    status_code=201,
    response_model=GameRead,
    response_model_exclude_none=True,
)
async def create_game(
    response: Response,
    request: Request,
    payload: GameCreate,
) -> GameRead:
    await tools.access_admin(request=request)

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
    status_code=200,
    response_model=GameRead,
    response_model_exclude_none=True,
)
async def patch_game(
    request: Request,
    game_id: int,
    payload: GamePatch,
) -> GameRead:
    await tools.access_admin(request=request)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name", "type", "source"),
        detail="Game patch fields cannot be null.",
    )

    async with catalog.AsyncSessionLocal() as session:
        game = await session.get(catalog.Game, game_id)
        if game is None:
            _raise_game_not_found(request)

        if "source" in data or "source_id" in data:
            candidate_source = data.get("source", game.source)
            candidate_source_id = data.get("source_id", game.source_id)
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
    status_code=204,
)
async def delete_game(request: Request, game_id: int) -> Response:
    await tools.access_admin(request=request)

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
