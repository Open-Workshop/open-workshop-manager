"""Modpack REST routes."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, insert, select, update

from open_workshop_manager import reputation, standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    GameRead,
    ModAuthorUpsert,
    ModpackCreate,
    ModpackListResponse,
    ModpackPatch,
    ModpackRead,
    ModpackRatingRead,
    ModpackModRead,
    ModpackModsRead,
    ModpackModUpsert,
    ModpackModsUpsert,
    RatingVoteUpsert,
    TagListResponse,
    ResourceRead,
    TagRead,
    stringify_source_id,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

ModpackIncludeField = Literal[
    "short_description",
    "description",
    "dates",
    "game",
    "tags",
    "authors",
    "resources",
]

MODPACK_INCLUDE_FIELDS = {
    "short_description",
    "description",
    "dates",
    "game",
    "tags",
    "authors",
    "resources",
}

MODPACK_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The modpack request contains invalid filters, payload values, or sort fields.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

MODPACK_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Modpack not found.",
        code="MODPACK_NOT_FOUND",
    ),
    "Modpack not found.",
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

MODPACK_CONFLICT_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="Modpack source already exists.",
        code="MODPACK_SOURCE_ALREADY_EXISTS",
    ),
    "Modpack source already exists.",
)

MODPACK_MODS_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Modpack or referenced mod not found.",
        code="NOT_FOUND",
    ),
    "Modpack or referenced mod not found.",
)

MODPACK_TAGS_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Modpack or referenced tag not found.",
        code="NOT_FOUND",
    ),
    "Modpack or referenced tag not found.",
)

MODPACK_TAGS_CONFLICT_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="The association is already present.",
        code="ASSOCIATION_ALREADY_EXISTS",
    ),
    "The association is already present.",
)


def _raise_modpack_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Modpack not found.",
        code="MODPACK_NOT_FOUND",
        instance=str(request.url),
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
            "allowed": [
                "name",
                "created_at",
                "updated_at",
                "source",
                "downloads",
                "rating",
                "public",
                "adult",
                "game_id",
            ],
        },
    )


def _raise_vote_right_denied(request: Request, right) -> None:
    reason_code = str(getattr(right, "reason_code", "") or "forbidden")
    detail = str(getattr(right, "reason", "") or "Forbidden")
    if reason_code in {"muted", "cooldown"}:
        raise standarts.TooEarlyError(
            detail=detail,
            instance=str(request.url),
            context={"reason_code": reason_code},
        )
    raise standarts.ForbiddenError(
        detail=detail,
        instance=str(request.url),
        context={"reason_code": reason_code},
    )


def _normalize_source_id(value: object | None) -> str | None:
    return stringify_source_id(value)


def _raise_mods_not_found(request: Request, missing_ids: list[int]) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="One or more mods were not found.",
        code="MOD_NOT_FOUND",
        instance=str(request.url),
        context={"missing_ids": missing_ids},
    )


async def _ensure_mods_exist(
    request: Request,
    session,
    mod_ids: list[int],
) -> None:
    if not mod_ids:
        return

    found_ids = set(
        int(mod_id)
        for mod_id in (
            await session.execute(
                select(catalog.Mod.id).where(catalog.Mod.id.in_(mod_ids))
            )
        ).scalars().all()
    )
    missing_ids = [mod_id for mod_id in mod_ids if mod_id not in found_ids]
    if missing_ids:
        _raise_mods_not_found(request, missing_ids)


async def _ensure_tags_exist(
    request: Request,
    session,
    tag_ids: list[int],
) -> None:
    if not tag_ids:
        return

    found_ids = set(
        int(tag_id)
        for tag_id in (
            await session.execute(
                select(catalog.Tag.id).where(catalog.Tag.id.in_(tag_ids))
            )
        ).scalars().all()
    )
    missing_ids = [tag_id for tag_id in tag_ids if tag_id not in found_ids]
    if missing_ids:
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="One or more tags were not found.",
            code="TAG_NOT_FOUND",
            instance=str(request.url),
            context={"missing_ids": missing_ids},
        )


async def _load_modpack_vote_state(request: Request, modpack_id: int) -> tuple[int | None, int]:
    try:
        access_state = await account.check_access(request=request)
        current_vote: int | None = None
        async with account.AsyncSessionLocal() as session:
            if access_state and getattr(access_state, "authenticated", False):
                voter_id = int(getattr(access_state, "owner_id", -1) or -1)
                if voter_id >= 0:
                    current_vote = await reputation.current_vote_value(
                        session,
                        voter_id=voter_id,
                        target_type="modpack",
                        target_id=int(modpack_id),
                    )

            vote_counts = await reputation.count_vote_counts(
                session,
                target_type="modpack",
                target_ids=[modpack_id],
            )
        return current_vote, int(vote_counts.get(int(modpack_id), 0))
    except Exception:
        return None, 0


async def _load_modpack_vote_counts(modpack_ids: list[int]) -> dict[int, int]:
    if not modpack_ids:
        return {}

    try:
        async with account.AsyncSessionLocal() as session:
            return await reputation.count_vote_counts(
                session,
                target_type="modpack",
                target_ids=modpack_ids,
            )
    except Exception:
        return {}


async def _load_modpack_authors(
    session,
    modpack_ids: list[int],
) -> dict[int, dict[int, dict[str, bool]]]:
    if not modpack_ids:
        return {}

    result = await session.execute(
        select(
            account.modpack_and_author.c.modpack_id,
            account.modpack_and_author.c.user_id,
            account.modpack_and_author.c.owner,
        ).where(account.modpack_and_author.c.modpack_id.in_(modpack_ids))
    )
    authors_by_modpack: dict[int, dict[int, dict[str, bool]]] = {modpack_id: {} for modpack_id in modpack_ids}
    for modpack_id, user_id, owner in result.all():
        authors_by_modpack.setdefault(int(modpack_id), {})[int(user_id)] = {
            "owner": bool(owner),
        }
    return authors_by_modpack


async def _load_modpack_mods(
    session,
    modpack_ids: list[int],
) -> dict[int, list[ModpackModRead]]:
    if not modpack_ids:
        return {}

    result = await session.execute(
        select(
            catalog.modpacks_and_mods.c.modpack_id,
            catalog.modpacks_and_mods.c.mod_id,
            catalog.modpacks_and_mods.c.sort_order,
            catalog.modpacks_and_mods.c.auto_added,
        ).where(catalog.modpacks_and_mods.c.modpack_id.in_(modpack_ids))
        .order_by(
            catalog.modpacks_and_mods.c.modpack_id.asc(),
            catalog.modpacks_and_mods.c.sort_order.asc(),
            catalog.modpacks_and_mods.c.mod_id.asc(),
        )
    )

    mods_by_modpack: dict[int, list[ModpackModRead]] = {modpack_id: [] for modpack_id in modpack_ids}
    for modpack_id, mod_id, sort_order, auto_added in result.all():
        mods_by_modpack.setdefault(int(modpack_id), []).append(
            ModpackModRead(
                mod_id=int(mod_id),
                sort_order=int(sort_order or 0),
                auto_added=bool(auto_added),
            )
        )
    return mods_by_modpack


async def _load_modpack_tags(
    session,
    modpack_ids: list[int],
) -> dict[int, list[TagRead]]:
    if not modpack_ids:
        return {}

    tag_table = catalog.Tag.__table__
    result = await session.execute(
        select(
            catalog.modpacks_tags.c.modpack_id,
            tag_table.c.id,
            tag_table.c.name,
        )
        .select_from(
            catalog.modpacks_tags.join(
                tag_table,
                tag_table.c.id == catalog.modpacks_tags.c.tag_id,
            )
        )
        .where(catalog.modpacks_tags.c.modpack_id.in_(modpack_ids))
        .order_by(
            catalog.modpacks_tags.c.modpack_id.asc(),
            tag_table.c.name.asc(),
            tag_table.c.id.asc(),
        )
    )

    tags_by_modpack: dict[int, list[TagRead]] = {modpack_id: [] for modpack_id in modpack_ids}
    for modpack_id, tag_id, tag_name in result.all():
        tags_by_modpack.setdefault(int(modpack_id), []).append(
            TagRead(id=int(tag_id), name=str(tag_name))
        )
    return tags_by_modpack


async def _load_modpack_resources(
    session,
    modpack_ids: list[int],
) -> dict[int, list[ResourceRead]]:
    if not modpack_ids:
        return {}

    resources = (
        await session.execute(
            select(catalog.Resource)
            .where(
                catalog.Resource.owner_type == "modpacks",
                catalog.Resource.owner_id.in_(modpack_ids),
            )
            .order_by(
                catalog.Resource.owner_id.asc(),
                catalog.Resource.sort_order.asc(),
                catalog.Resource.id.asc(),
            )
        )
    ).scalars().all()

    resources_by_modpack: dict[int, list[ResourceRead]] = {modpack_id: [] for modpack_id in modpack_ids}
    for resource in resources:
        resource_owner_id = int(getattr(resource, "owner_id", 0) or 0)
        resources_by_modpack.setdefault(resource_owner_id, []).append(
            ResourceRead.model_validate(
                {
                    "id": int(getattr(resource, "id", 0) or 0),
                    "owner_type": str(getattr(resource, "owner_type", "")),
                    "owner_id": resource_owner_id,
                    "type": str(getattr(resource, "type", "")),
                    "sort_order": int(getattr(resource, "sort_order", 0) or 0),
                    "url": getattr(resource, "real_url", getattr(resource, "url", "")),
                    "size": (
                        int(getattr(resource, "size", 0))
                        if getattr(resource, "size", None) is not None
                        else None
                    ),
                    "created_at": getattr(resource, "date_event", None),
                    "updated_at": getattr(resource, "date_event", None),
                }
            )
        )
    return resources_by_modpack


def _normalize_modpack_mods(items: list[ModpackModUpsert]) -> list[ModpackModUpsert]:
    normalized: list[ModpackModUpsert] = []
    seen: set[int] = set()
    for item in items:
        mod_id = int(getattr(item, "mod_id", 0) or 0)
        if mod_id <= 0 or mod_id in seen:
            continue
        seen.add(mod_id)
        normalized.append(
            ModpackModUpsert(
                mod_id=mod_id,
                auto_added=bool(getattr(item, "auto_added", False)),
            )
        )
    return normalized


def _normalize_modpack_sources(primary: list[str], legacy: list[str]) -> list[str]:
    return list(dict.fromkeys([*primary, *legacy]))


def _raise_unsupported_include(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported include field.",
        code="UNSUPPORTED_INCLUDE_FIELD",
        instance=str(request.url),
        context={"field": field, "allowed": sorted(MODPACK_INCLUDE_FIELDS)},
    )


def _normalize_include(request: Request, include: list[str]) -> set[str]:
    normalized = {item.strip() for item in include if item and item.strip()}
    unknown = normalized.difference(MODPACK_INCLUDE_FIELDS)
    if unknown:
        _raise_unsupported_include(request, sorted(unknown)[0])
    return normalized


def _serialize_modpack_base(
    row: catalog.Modpack,
    *,
    current_vote: int | None = None,
    votes_count: int = 0,
) -> dict[str, object]:
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "name": str(getattr(row, "name", "") or ""),
        "short_description": getattr(row, "short_description", None),
        "description": getattr(row, "description", None),
        "source": str(getattr(row, "source", "") or ""),
        "source_id": _normalize_source_id(getattr(row, "source_id", None)),
        "game_id": (
            int(getattr(row, "game", 0)) if getattr(row, "game", None) is not None else None
        ),
        "public": int(getattr(row, "public", 0) or 0),
        "adult": bool(getattr(row, "adult", False)),
        "rating": int(getattr(row, "rating", 0) or 0),
        "votes_count": int(votes_count),
        "current_vote": current_vote,
        "downloads": (
            int(getattr(row, "downloads", 0))
            if getattr(row, "downloads", None) is not None
            else None
        ),
        "created_at": getattr(row, "date_creation", None),
        "updated_at": getattr(row, "date_edit", None),
    }


def _serialize_modpack(
    row: catalog.Modpack,
    *,
    authors: dict[int, dict[str, bool]] | None = None,
    tags: list[TagRead] | None = None,
    resources: list[ResourceRead] | None = None,
    current_vote: int | None = None,
    votes_count: int = 0,
) -> ModpackRead:
    payload = _serialize_modpack_base(
        row,
        current_vote=current_vote,
        votes_count=votes_count,
    )
    payload["authors"] = authors
    payload["tags"] = tags
    payload["resources"] = resources
    return ModpackRead.model_validate(payload)


async def _load_modpack_games(
    session,
    game_ids: list[int],
) -> dict[int, dict[str, object]]:
    if not game_ids:
        return {}

    result = await session.execute(
        select(catalog.Game).where(catalog.Game.id.in_(game_ids))
    )
    games_by_id: dict[int, dict[str, object]] = {}
    for game in result.scalars().all():
        game_id = int(getattr(game, "id", 0) or 0)
        if game_id <= 0:
            continue
        games_by_id[game_id] = GameRead(
            id=game_id,
            name=str(getattr(game, "name", "") or ""),
            short_description=getattr(game, "short_description", None),
            description=getattr(game, "description", None),
            type=str(getattr(game, "type", "game") or "game"),
            source=str(getattr(game, "source", "local") or "local"),
            source_id=_normalize_source_id(getattr(game, "source_id", None)),
            mods_count=(
                int(getattr(game, "mods_count", 0))
                if getattr(game, "mods_count", None) is not None
                else None
            ),
            mods_downloads=(
                int(getattr(game, "mods_downloads", 0))
                if getattr(game, "mods_downloads", None) is not None
                else None
            ),
            created_at=getattr(game, "creation_date", None),
        ).model_dump(mode="json", exclude_none=True)
    return games_by_id


async def _store_modpack_mods(
    session,
    modpack_id: int,
    items: list[ModpackModUpsert],
) -> None:
    await session.execute(
        delete(catalog.modpacks_and_mods).where(
            catalog.modpacks_and_mods.c.modpack_id == modpack_id
        )
    )

    if not items:
        return

    values = [
        {
            "modpack_id": modpack_id,
            "mod_id": item.mod_id,
            "sort_order": index,
            "auto_added": bool(item.auto_added),
        }
        for index, item in enumerate(items)
    ]
    await session.execute(insert(catalog.modpacks_and_mods), values)


@router.get(
    "/modpacks",
    tags=["Modpack"],
    summary="List modpacks",
    description=(
        "Returns a paginated list of modpacks.\n\n"
        "Use `show_not_public=true` together with `author_id` to include hidden modpacks "
        "that are visible to the current author context.\n\n"
        "Use filters for IDs, tags, excluded tags, source fields, game, and `include` to "
        "opt into `short_description`, `description`, `dates`, `game`, `tags`, `authors`, "
        "and `resources`."
    ),
    status_code=200,
    response_model=ModpackListResponse,
    response_model_exclude_none=True,
    response_description="Paginated modpack list.",
    responses={400: MODPACK_BAD_REQUEST_RESPONSE},
)
async def list_modpacks(
    request: Request,
    page_size: int = Query(
        default=LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of modpacks to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(default=None, max_length=LIMITS.mod.name_max),
    ids: list[int] = Query(default_factory=list, description="Limit results to these modpack IDs."),
    tags: list[int] = Query(default_factory=list, description="Require all of these tag IDs."),
    excluded_tags: list[int] = Query(default_factory=list, description="Exclude any modpack that has one of these tags."),
    sources: list[str] = Query(default_factory=list, description="Source names to filter by."),
    source: list[str] = Query(default_factory=list, include_in_schema=False),
    source_ids: list[str] = Query(default_factory=list),
    author_id: int | None = Query(default=None, ge=1),
    game_id: int | None = Query(default=None, ge=1),
    public: int | None = Query(default=None, ge=0, le=2),
    adult: int = Query(default=-1, ge=-1, le=1, description="Adult content filter: -1 any, 0 false, 1 true."),
    show_not_public: bool = Query(default=False),
    sort: str = Query(
        default="downloads",
        description="Sort field, optionally prefixed with `-` for descending order.",
    ),
    include: list[ModpackIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in each modpack object.",
    ),
):
    show_not_public = bool(show_not_public and author_id is not None)
    include_set = _normalize_include(request, include)
    source_filters = _normalize_modpack_sources(sources, source)
    source_ids_normalized = [
        normalized
        for normalized in (
            _normalize_source_id(source_id) for source_id in source_ids
        )
        if normalized is not None
    ]

    try:
        sort_clause = tools.sort_modpacks(sort)
    except KeyError as exc:
        _raise_unsupported_sort(request, exc.args[0] if exc.args else str(exc))

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Modpack).where(catalog.Modpack.condition == 0)
        if ids:
            stmt = stmt.where(catalog.Modpack.id.in_(ids))
        if author_id is not None:
            stmt = stmt.where(
                catalog.Modpack.id.in_(
                    select(account.modpack_and_author.c.modpack_id).where(
                        account.modpack_and_author.c.user_id == author_id
                    )
                )
            )
        if game_id is not None:
            stmt = stmt.where(catalog.Modpack.game == game_id)
        if public in (0, 1, 2):
            stmt = stmt.where(catalog.Modpack.public == int(public))
        if adult in (0, 1):
            stmt = stmt.where(catalog.Modpack.adult == bool(adult))
        if source_filters:
            stmt = stmt.where(catalog.Modpack.source.in_(source_filters))
        if source_ids_normalized:
            stmt = stmt.where(catalog.Modpack.source_id.in_(source_ids_normalized))
        if name:
            stmt = stmt.where(catalog.Modpack.name.ilike(f"%{name.strip()}%"))
        if tags:
            for tag_id in tags:
                stmt = stmt.where(catalog.Modpack.tags.any(catalog.Tag.id == tag_id))
        if excluded_tags:
            stmt = stmt.where(
                ~select(1)
                .where(
                    catalog.modpacks_tags.c.modpack_id == catalog.Modpack.id,
                    catalog.modpacks_tags.c.tag_id.in_(excluded_tags),
                )
                .exists()
            )

        if show_not_public:
            candidate_ids = [
                int(modpack_id)
                for modpack_id in (
                    await session.execute(
                        stmt.with_only_columns(catalog.Modpack.id).order_by(None)
                    )
                ).scalars().all()
            ]
            if not candidate_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            allowed_ids = await tools.access_modpacks(
                request=request,
                modpack_ids=candidate_ids,
                author_id=author_id,
                catalog=True,
                check_mode=True,
            )
            if not allowed_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            stmt = stmt.where(catalog.Modpack.id.in_(allowed_ids))
        else:
            stmt = stmt.where(catalog.Modpack.public == 0)

        filtered = stmt.order_by(None).subquery()
        count_stmt = select(func.count()).select_from(filtered)
        total = int((await session.scalar(count_stmt)) or 0)
        rows = (
            await session.execute(
                stmt.order_by(sort_clause, catalog.Modpack.id.asc())
                .offset(page * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        modpack_ids = [int(row.id) for row in rows]
        authors = await _load_modpack_authors(session, modpack_ids) if "authors" in include_set else {}
        tags = await _load_modpack_tags(session, modpack_ids) if "tags" in include_set else {}
        resources = await _load_modpack_resources(session, modpack_ids) if "resources" in include_set else {}
        games_by_id = (
            await _load_modpack_games(
                session,
                [int(getattr(row, "game", 0) or 0) for row in rows if getattr(row, "game", None) is not None],
            )
            if "game" in include_set
            else {}
        )
        vote_counts = await _load_modpack_vote_counts(modpack_ids)

    items: list[dict[str, object]] = []
    for row in rows:
        payload = _serialize_modpack_base(row, votes_count=vote_counts.get(int(row.id), 0))

        if "short_description" not in include_set:
            payload.pop("short_description", None)
        if "description" not in include_set:
            payload.pop("description", None)
        if "dates" not in include_set:
            payload.pop("created_at", None)
            payload.pop("updated_at", None)

        if "game" in include_set:
            game_id = int(getattr(row, "game", 0) or 0) if getattr(row, "game", None) is not None else None
            if game_id is not None and game_id in games_by_id:
                payload["game"] = games_by_id[game_id]
            else:
                payload.pop("game", None)
        else:
            payload.pop("game", None)

        if "tags" in include_set:
            payload["tags"] = tags.get(int(row.id))
        else:
            payload.pop("tags", None)

        if "authors" in include_set:
            payload["authors"] = authors.get(int(row.id))
        else:
            payload.pop("authors", None)

        if "resources" in include_set:
            payload["resources"] = resources.get(int(row.id))
        else:
            payload.pop("resources", None)

        items.append(
            ModpackRead.model_validate(payload).model_dump(mode="json", exclude_none=True)
        )
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Get modpack",
    description=(
        "Returns a modpack by ID, including its authors, tags, resources, and current vote state "
        "when available."
    ),
    status_code=200,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Modpack resource.",
    responses={404: MODPACK_NOT_FOUND_RESPONSE},
)
async def get_modpack(
    request: Request,
    modpack_id: int,
) -> ModpackRead:
    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        if row.public > 0 or int(getattr(row, "condition", 0) or 0) != 0:
            await tools.access_modpacks(request=request, modpack_ids=[modpack_id])

        authors = await _load_modpack_authors(session, [modpack_id])
        tags = await _load_modpack_tags(session, [modpack_id])
        resources = await _load_modpack_resources(session, [modpack_id])

    current_vote, votes_count = await _load_modpack_vote_state(request, modpack_id)
    return _serialize_modpack(
        row,
        authors=authors.get(modpack_id),
        tags=tags.get(modpack_id),
        resources=resources.get(modpack_id),
        current_vote=current_vote,
        votes_count=votes_count,
    )


@router.get(
    "/modpacks/{modpack_id}/mods",
    tags=["Modpack", "Build"],
    summary="Get modpack mods",
    description="Returns the list of mods stored in the modpack, including auto-added flags.",
    status_code=200,
    response_model=ModpackModsRead,
    response_model_exclude_none=True,
    response_description="Stored modpack mods.",
    responses={404: MODPACK_NOT_FOUND_RESPONSE},
)
async def get_modpack_mods(request: Request, modpack_id: int) -> ModpackModsRead:
    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        if row.public > 0 or int(getattr(row, "condition", 0) or 0) != 0:
            await tools.access_modpacks(request=request, modpack_ids=[modpack_id])

        mods = await _load_modpack_mods(session, [modpack_id])

    return ModpackModsRead(modpack_id=modpack_id, items=mods.get(modpack_id, []))


@router.get(
    "/modpacks/{modpack_id}/tags",
    tags=["Modpack", "Tag"],
    summary="List modpack tags",
    description="Returns all tags attached to a modpack.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Stored modpack tags.",
    responses={404: MODPACK_NOT_FOUND_RESPONSE},
)
async def get_modpack_tags(request: Request, modpack_id: int) -> dict[str, object]:
    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        if row.public > 0 or int(getattr(row, "condition", 0) or 0) != 0:
            await tools.access_modpacks(request=request, modpack_ids=[modpack_id])

        tags = await _load_modpack_tags(session, [modpack_id])

    items = [tag.model_dump(mode="json", exclude_none=True) for tag in tags.get(modpack_id, [])]
    return make_list_response(items, page=0, page_size=max(len(items), 1), total=len(items))


@router.post(
    "/modpacks/{modpack_id}/tags/{tag_id}",
    tags=["Modpack", "Tag"],
    summary="Add modpack tag",
    description="Associates a tag with a modpack.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_TAGS_NOT_FOUND_RESPONSE,
        409: MODPACK_TAGS_CONFLICT_RESPONSE,
    },
)
async def add_modpack_tag(request: Request, modpack_id: int, tag_id: int):
    await tools.access_modpacks(request=request, modpack_ids=[modpack_id], edit=True)

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)
        await _ensure_tags_exist(request, session, [tag_id])

        exists = await session.execute(
            select(catalog.modpacks_tags).where(
                catalog.modpacks_tags.c.modpack_id == modpack_id,
                catalog.modpacks_tags.c.tag_id == tag_id,
            )
        )
        if exists.first() is not None:
            raise standarts.StandardAPIError(
                status_code=409,
                title="Conflict",
                detail="The association is already present.",
                code="ASSOCIATION_ALREADY_EXISTS",
                instance=str(request.url),
            )

        await session.execute(
            insert(catalog.modpacks_tags).values(modpack_id=modpack_id, tag_id=tag_id)
        )
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/modpacks/{modpack_id}/tags/{tag_id}",
    tags=["Modpack", "Tag"],
    summary="Remove modpack tag",
    description="Removes a tag association from a modpack.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_TAGS_NOT_FOUND_RESPONSE,
    },
)
async def delete_modpack_tag(request: Request, modpack_id: int, tag_id: int):
    await tools.access_modpacks(request=request, modpack_ids=[modpack_id], edit=True)

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)
        await _ensure_tags_exist(request, session, [tag_id])

        await session.execute(
            delete(catalog.modpacks_tags).where(
                catalog.modpacks_tags.c.modpack_id == modpack_id,
                catalog.modpacks_tags.c.tag_id == tag_id,
            )
        )
        await session.commit()

    return Response(status_code=204)


@router.put(
    "/modpacks/{modpack_id}/mods",
    tags=["Modpack", "Build"],
    summary="Replace modpack mods",
    description="Replaces the stored mod list for a modpack.",
    status_code=200,
    response_model=ModpackModsRead,
    response_model_exclude_none=True,
    response_description="Updated modpack mods.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_MODS_NOT_FOUND_RESPONSE,
    },
)
async def put_modpack_mods(
    request: Request,
    modpack_id: int,
    payload: ModpackModsUpsert,
) -> ModpackModsRead:
    await tools.access_modpacks(request=request, modpack_ids=[modpack_id], edit=True)

    normalized_items = _normalize_modpack_mods(list(payload.items or []))
    mod_ids = [item.mod_id for item in normalized_items]

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        await _ensure_mods_exist(request, session, mod_ids)
        if mod_ids:
            await tools.access_mods(request=request, mods_ids=mod_ids)

        await _store_modpack_mods(session, modpack_id, normalized_items)
        await session.commit()
        mods = await _load_modpack_mods(session, [modpack_id])

    return ModpackModsRead(modpack_id=modpack_id, items=mods.get(modpack_id, []))


@router.put(
    "/modpacks/{modpack_id}/rating",
    tags=["Modpack"],
    summary="Rate modpack",
    description=(
        "Sets the current user's vote for a modpack. Votes update the stored approval "
        "percentage in the database."
    ),
    status_code=200,
    response_model=ModpackRatingRead,
    response_model_exclude_none=True,
    response_description="Updated modpack rating.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
    },
)
async def put_modpack_rating(
    request: Request,
    modpack_id: int,
    payload: RatingVoteUpsert,
) -> ModpackRatingRead:
    vote_access = await tools.access_vote_for_reputation(request=request)
    if not vote_access.vote_for_reputation.value:
        _raise_vote_right_denied(request, vote_access.vote_for_reputation)

    async with account.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

        await tools.access_modpacks(request=request, modpack_ids=[modpack_id], catalog=True)

        summary = await reputation.apply_modpack_vote(
            session,
            voter_id=int(vote_access.owner_id),
            modpack=modpack,
            value=int(payload.value),
        )
        await session.commit()
        return ModpackRatingRead(
            modpack_id=modpack_id,
            rating=summary.rating,
            votes_count=summary.votes_count,
        )


@router.post(
    "/modpacks",
    tags=["Modpack"],
    summary="Create modpack",
    description="Creates a new modpack draft or published entry, returning its tags and resources collections.",
    status_code=201,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Created modpack resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: GAME_NOT_FOUND_RESPONSE,
        409: MODPACK_CONFLICT_RESPONSE,
    },
)
async def create_modpack(
    response: Response,
    request: Request,
    payload: ModpackCreate,
) -> ModpackRead:
    access_result = await tools.access_modpack_add(request=request)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    required_right = access_result.anonymous_add if payload.without_author else access_result.add
    if not required_right.value:
        raise standarts.ForbiddenError(
            detail=required_right.reason,
            instance=str(request.url),
            context={"reason_code": required_right.reason_code},
        )

    candidate_source_id = _normalize_source_id(payload.source_id)
    if payload.game_id is not None and not await tools.check_game_exists(int(payload.game_id)):
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Game not found.",
            code="GAME_NOT_FOUND",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        if candidate_source_id is not None and payload.source != "local":
            existing = await session.scalar(
                select(catalog.Modpack.id).where(
                    catalog.Modpack.source == payload.source,
                    catalog.Modpack.source_id == candidate_source_id,
                    catalog.Modpack.condition == 0,
                )
            )
            if existing is not None:
                raise standarts.StandardAPIError(
                    status_code=409,
                    title="Conflict",
                    detail="Modpack source already exists.",
                    code="MODPACK_SOURCE_ALREADY_EXISTS",
                    instance=str(request.url),
                    context={"source": payload.source, "source_id": candidate_source_id},
                )

        modpack = catalog.Modpack(
            name=payload.name,
            short_description=payload.short_description,
            description=payload.description,
            condition=0,
            public=payload.public,
            adult=payload.adult,
            rating=0,
            downloads=0,
            date_creation=datetime.datetime.now(),
            date_edit=datetime.datetime.now(),
            source=payload.source,
            source_id=candidate_source_id,
            game=payload.game_id,
        )
        session.add(modpack)
        await session.flush()

        authors: dict[int, dict[str, bool]] | None = None
        if not payload.without_author and access_result.owner_id >= 0:
            await session.execute(
                insert(account.modpack_and_author).values(
                    modpack_id=modpack.id,
                    user_id=access_result.owner_id,
                    owner=True,
                )
            )
            authors = {int(access_result.owner_id): {"owner": True}}

        await session.commit()
        response.headers["Location"] = f"/modpacks/{modpack.id}"
        return _serialize_modpack(modpack, authors=authors, tags=[], resources=[])


@router.patch(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Update modpack",
    description="Updates an existing modpack and returns its tags and resources collections.",
    status_code=200,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Updated modpack resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
        409: MODPACK_CONFLICT_RESPONSE,
    },
)
async def patch_modpack(
    request: Request,
    modpack_id: int,
    payload: ModpackPatch,
) -> ModpackRead:
    await tools.access_modpacks(request=request, modpack_ids=[modpack_id], edit=True)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name", "source", "public", "adult"),
        detail="Modpack patch fields cannot be null.",
    )

    if "name" in data:
        if len(str(data["name"])) > LIMITS.mod.name_max:
            raise standarts.PayloadTooLargeError(
                detail="Name is too long.",
                instance=str(request.url),
            )
        if len(str(data["name"])) < LIMITS.mod.name_min:
            raise standarts.PreconditionRequiredError(
                detail="Name is too short.",
                instance=str(request.url),
            )
    if "short_description" in data and len(re.sub(r"\s+", " ", str(data["short_description"]))) > LIMITS.mod.short_desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Short description is too long.",
            instance=str(request.url),
        )
    if "description" in data and len(re.sub(r"\s+", " ", str(data["description"]))) > LIMITS.mod.desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Description is too long.",
            instance=str(request.url),
        )

    if "game_id" in data and data["game_id"] is not None and not await tools.check_game_exists(int(data["game_id"])):
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Game not found.",
            code="GAME_NOT_FOUND",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        current_source = str(getattr(row, "source", "local") or "local")
        current_source_id = _normalize_source_id(getattr(row, "source_id", None))
        if "source" in data or "source_id" in data:
            candidate_source = str(data.get("source", current_source))
            candidate_source_id = _normalize_source_id(data.get("source_id", current_source_id))
            if candidate_source_id is not None and candidate_source != "local":
                existing = await session.scalar(
                    select(catalog.Modpack.id).where(
                        catalog.Modpack.id != modpack_id,
                        catalog.Modpack.source == candidate_source,
                        catalog.Modpack.source_id == candidate_source_id,
                        catalog.Modpack.condition == 0,
                    )
                )
                if existing is not None:
                    raise standarts.StandardAPIError(
                        status_code=409,
                        title="Conflict",
                        detail="Modpack source already exists.",
                        code="MODPACK_SOURCE_ALREADY_EXISTS",
                        instance=str(request.url),
                        context={"source": candidate_source, "source_id": candidate_source_id},
                    )
            row.source = candidate_source
            row.source_id = candidate_source_id

        for key, value in data.items():
            if key == "game_id":
                row.game = int(value) if value is not None else None
            elif key == "public":
                row.public = int(value)
            elif key == "adult":
                row.adult = bool(value)
            elif key == "name":
                row.name = str(value)
            elif key == "short_description":
                row.short_description = value if value is None else str(value)
            elif key == "description":
                row.description = value if value is None else str(value)

        row.date_edit = datetime.datetime.now()
        authors = await _load_modpack_authors(session, [modpack_id])
        tags = await _load_modpack_tags(session, [modpack_id])
        resources = await _load_modpack_resources(session, [modpack_id])
        await session.commit()
        return _serialize_modpack(
            row,
            authors=authors.get(modpack_id),
            tags=tags.get(modpack_id),
            resources=resources.get(modpack_id),
        )


@router.delete(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Delete modpack",
    description="Deletes a modpack and its author links.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
    },
)
async def delete_modpack(request: Request, modpack_id: int) -> Response:
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.delete.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.delete.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.delete.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        if not await tools.delete_resources(owner_type="modpacks", owner_id=modpack_id):
            raise standarts.InternalServerError(
                detail="Failed to delete modpack resources.",
                instance=str(request.url),
                code="RESOURCE_DELETE_FAILED",
            )
        await session.execute(
            delete(account.modpack_and_author).where(
                account.modpack_and_author.c.modpack_id == modpack_id
            )
        )
        await session.execute(
            delete(catalog.modpacks_tags).where(
                catalog.modpacks_tags.c.modpack_id == modpack_id
            )
        )
        await session.execute(delete(catalog.Modpack).where(catalog.Modpack.id == modpack_id))
        await session.commit()

    return Response(status_code=204)


@router.put(
    "/modpacks/{modpack_id}/authors/{author_id}",
    tags=["Modpack", "Author"],
    summary="Set modpack author",
    description="Creates or updates a modpack author assignment.",
    status_code=204,
)
async def put_modpack_author(request: Request, modpack_id: int, author_id: int, payload: ModAuthorUpsert):
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
        author_id=author_id,
        mode=payload.owner,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.edit.authors.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.edit.authors.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.edit.authors.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.modpack_and_author.c.owner).where(
                account.modpack_and_author.c.modpack_id == modpack_id,
                account.modpack_and_author.c.user_id == author_id,
            )
        )

        if payload.owner:
            await session.execute(
                update(account.modpack_and_author)
                .where(account.modpack_and_author.c.modpack_id == modpack_id)
                .where(account.modpack_and_author.c.user_id != author_id)
                .values(owner=False)
            )

        if relation_owner is None:
            await session.execute(
                insert(account.modpack_and_author).values(
                    modpack_id=modpack_id,
                    user_id=author_id,
                    owner=bool(payload.owner),
                )
            )
        else:
            await session.execute(
                update(account.modpack_and_author)
                .where(account.modpack_and_author.c.modpack_id == modpack_id)
                .where(account.modpack_and_author.c.user_id == author_id)
                .values(owner=bool(payload.owner))
            )

        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/modpacks/{modpack_id}/authors/{author_id}",
    tags=["Modpack", "Author"],
    summary="Remove modpack author",
    description="Removes a modpack author assignment.",
    status_code=204,
)
async def delete_modpack_author(request: Request, modpack_id: int, author_id: int):
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
        author_id=author_id,
        mode=False,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.edit.authors.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.edit.authors.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.edit.authors.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.modpack_and_author.c.owner).where(
                account.modpack_and_author.c.modpack_id == modpack_id,
                account.modpack_and_author.c.user_id == author_id,
            )
        )

        if relation_owner is not None:
            await session.execute(
                delete(account.modpack_and_author).where(
                    account.modpack_and_author.c.modpack_id == modpack_id,
                    account.modpack_and_author.c.user_id == author_id,
                )
            )

        await session.commit()

    return Response(status_code=204)
