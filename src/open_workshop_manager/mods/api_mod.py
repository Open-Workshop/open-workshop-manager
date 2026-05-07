"""Mod REST routes."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.orm import aliased, joinedload

from open_workshop_manager import mod_events, reputation, standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    GameRead,
    IntCollectionRead,
    ModCreate,
    ModFeedRead,
    ModDownloadUrlRead,
    ModListResponse,
    ModPatch,
    ModRead,
    ModRatingRead,
    ModDependencyCollectionRead,
    ModDependencyRead,
    RatingVoteUpsert,
    TagListResponse,
    stringify_source_id,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import serialize_tag, serialize_tag_group
from open_workshop_manager.settings import STORAGE_URL
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

ModIncludeField = Literal[
    "short_description",
    "description",
    "dates",
    "game",
    "tags",
    "dependencies",
    "conflicts",
    "authors",
    "resources",
]

DependencyFilterMode = Literal["any", "required", "optional"]
ConflictScope = Literal["outgoing", "incoming", "all"]

MOD_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The mod request contains invalid filters, include fields, or payload values.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

MOD_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Mod not found.",
        code="MOD_NOT_FOUND",
    ),
    "Mod not found.",
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

MOD_TARGET_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Referenced mod or game was not found.",
        code="NOT_FOUND",
    ),
    "Referenced mod or game not found.",
)

MOD_CONFLICT_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="Mod source already exists.",
        code="MOD_SOURCE_ALREADY_EXISTS",
    ),
    "Mod source already exists.",
)

MOD_INCLUDE_FIELDS = {
    "short_description",
    "description",
    "dates",
    "game",
    "tags",
    "dependencies",
    "conflicts",
    "authors",
    "resources",
}


def _raise_mod_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Mod not found.",
        code="MOD_NOT_FOUND",
        instance=str(request.url),
    )


async def _load_mod_vote_state(request: Request, mod_id: int) -> tuple[int | None, int]:
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
                        target_type="mod",
                        target_id=int(mod_id),
                    )

            vote_counts = await reputation.count_vote_counts(
                session,
                target_type="mod",
                target_ids=[mod_id],
            )
        return current_vote, int(vote_counts.get(int(mod_id), 0))
    except Exception:
        return None, 0


async def _load_mod_vote_counts(mod_ids: list[int]) -> dict[int, int]:
    if not mod_ids:
        return {}

    try:
        async with account.AsyncSessionLocal() as session:
            return await reputation.count_vote_counts(
                session,
                target_type="mod",
                target_ids=mod_ids,
            )
    except Exception:
        return {}


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


def _raise_unsupported_include(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported include field.",
        code="UNSUPPORTED_INCLUDE_FIELD",
        instance=str(request.url),
        context={"field": field, "allowed": sorted(MOD_INCLUDE_FIELDS)},
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
                "size",
                "created_at",
                "file_updated_at",
                "updated_at",
                "source",
                "downloads",
                "rating",
                "dependents_count",
                "public",
                "adult",
                "game_id",
            ],
        },
    )


def _normalize_include(request: Request, include: list[str]) -> set[str]:
    normalized = {item.strip() for item in include if item and item.strip()}
    unknown = normalized.difference(MOD_INCLUDE_FIELDS)
    if unknown:
        _raise_unsupported_include(request, sorted(unknown)[0])
    return normalized


def _raise_invalid_dependency_filter(
    request: Request,
    *,
    field: str,
    value: str,
    detail: str,
    mod_id: int | None = None,
) -> None:
    context: dict[str, object] = {"field": field, "value": value}
    if mod_id is not None:
        context["mod_id"] = mod_id
    raise standarts.BadRequestError(
        detail=detail,
        instance=str(request.url),
        code="INVALID_DEPENDENCY_FILTER",
        context=context,
    )


def _parse_dependency_filter_token(
    request: Request,
    *,
    field: str,
    token: str,
) -> tuple[int, DependencyFilterMode]:
    raw = str(token).strip()
    if not raw:
        _raise_invalid_dependency_filter(
            request,
            field=field,
            value=token,
            detail="Dependency filter cannot be empty.",
        )

    if ":" in raw:
        mod_text, mode_text = raw.split(":", 1)
    elif "|" in raw:
        mod_text, mode_text = raw.split("|", 1)
    else:
        mod_text, mode_text = raw, None

    try:
        mod_id = int(mod_text)
    except ValueError:
        _raise_invalid_dependency_filter(
            request,
            field=field,
            value=token,
            detail="Dependency filter must start with a numeric mod ID.",
        )

    if mode_text is None:
        return mod_id, "any"

    mode = mode_text.strip().lower()
    if mode in {"", "any"}:
        return mod_id, "any"
    if mode in {"required", "req"}:
        return mod_id, "required"
    if mode in {"optional", "opt"}:
        return mod_id, "optional"

    _raise_invalid_dependency_filter(
        request,
        field=field,
        value=token,
        detail="Unsupported dependency filter mode.",
        mod_id=mod_id,
    )


def _merge_dependency_modes(existing: DependencyFilterMode, incoming: DependencyFilterMode) -> DependencyFilterMode | None:
    if existing == incoming:
        return existing
    if existing == "any":
        return incoming
    if incoming == "any":
        return existing
    return None


def _collect_dependency_filter_groups(
    request: Request,
    *,
    field: str,
    values: list[str],
) -> dict[DependencyFilterMode, set[int]]:
    modes_by_mod_id: dict[int, DependencyFilterMode] = {}
    for token in values:
        mod_id, mode = _parse_dependency_filter_token(request, field=field, token=token)
        current_mode = modes_by_mod_id.get(mod_id)
        if current_mode is None:
            modes_by_mod_id[mod_id] = mode
            continue
        merged_mode = _merge_dependency_modes(current_mode, mode)
        if merged_mode is None:
            _raise_invalid_dependency_filter(
                request,
                field=field,
                value=token,
                detail="Conflicting dependency filter modes were supplied for the same mod ID.",
                mod_id=mod_id,
            )
        modes_by_mod_id[mod_id] = merged_mode

    grouped: dict[DependencyFilterMode, set[int]] = {
        "any": set(),
        "required": set(),
        "optional": set(),
    }
    for mod_id, mode in modes_by_mod_id.items():
        grouped[mode].add(mod_id)
    return grouped


def _join_dependency_requirement(
    stmt,
    *,
    dependency_ids: set[int],
    mode: DependencyFilterMode,
):
    if not dependency_ids:
        return stmt

    dependency_conditions = [catalog.mods_dependencies.c.dependence.in_(sorted(dependency_ids))]
    if mode == "required":
        dependency_conditions.append(catalog.mods_dependencies.c.optional.is_(False))
    elif mode == "optional":
        dependency_conditions.append(catalog.mods_dependencies.c.optional.is_(True))

    mods_with_dependencies = (
        select(catalog.mods_dependencies.c.mod_id)
        .where(*dependency_conditions)
        .group_by(catalog.mods_dependencies.c.mod_id)
        .having(
            func.count(func.distinct(catalog.mods_dependencies.c.dependence))
            == len(dependency_ids)
        )
        .subquery()
    )
    return stmt.join(
        mods_with_dependencies,
        catalog.Mod.id == mods_with_dependencies.c.mod_id,
    )


def _exclude_dependency_requirement(
    stmt,
    *,
    dependency_ids: set[int],
    mode: DependencyFilterMode,
):
    if not dependency_ids:
        return stmt

    dependency_conditions = [
        catalog.mods_dependencies.c.mod_id == catalog.Mod.id,
        catalog.mods_dependencies.c.dependence.in_(sorted(dependency_ids)),
    ]
    if mode == "required":
        dependency_conditions.append(catalog.mods_dependencies.c.optional.is_(False))
    elif mode == "optional":
        dependency_conditions.append(catalog.mods_dependencies.c.optional.is_(True))

    return stmt.where(
        ~select(1)
        .where(*dependency_conditions)
        .exists()
    )


async def _load_mod_feed_tag_groups(session, game: int) -> list[dict[str, object]]:
    allowed_tag_exists = (
        select(1)
        .select_from(
            catalog.Tag.__table__.join(
                catalog.allowed_mods_tags,
                catalog.allowed_mods_tags.c.tag_id == catalog.Tag.id,
            )
        )
        .where(catalog.Tag.group_id == catalog.TagGroup.id)
    )
    if game > 0:
        allowed_tag_exists = allowed_tag_exists.where(catalog.allowed_mods_tags.c.game_id == game)

    groups = (
        await session.execute(
            select(catalog.TagGroup)
            .where(allowed_tag_exists.exists())
            .order_by(catalog.TagGroup.name, catalog.TagGroup.id)
        )
    ).scalars().all()
    return [serialize_tag_group(group).model_dump(mode="json", exclude_none=True) for group in groups]


def _serialize_mod_base(row: catalog.Mod) -> dict[str, object]:
    game_id = getattr(row, "game", None)
    return {
        "id": int(row.id),
        "name": str(getattr(row, "name", "")),
        "short_description": getattr(row, "short_description", None),
        "description": getattr(row, "description", None),
        "source": str(getattr(row, "source", "local")),
        "source_id": stringify_source_id(getattr(row, "source_id", None)),
        "git_url": getattr(row, "git_url", None),
        "game_id": int(game_id) if game_id is not None else None,
        "public": int(getattr(row, "public", 0) or 0),
        "adult": bool(getattr(row, "adult", False)),
        "condition": "draft" if int(getattr(row, "condition", 0) or 0) != 0 else "published",
        "downloads": int(getattr(row, "downloads", 0) or 0),
        "rating": int(getattr(row, "rating", 0) or 0),
        "votes_count": int(getattr(row, "votes_count", 0) or 0),
        "size": int(getattr(row, "size", 0) or 0),
        "size_unpacked": (
            int(getattr(row, "size_unpacked", 0))
            if getattr(row, "size_unpacked", None) is not None
            else None
        ),
        "created_at": getattr(row, "date_creation", None),
        "file_updated_at": getattr(row, "date_update_file", None),
        "updated_at": getattr(row, "date_edit", None),
        "file": None,
    }


def _serialize_dependency_row(row: object) -> dict[str, object]:
    dependency_id = getattr(row, "dependence", getattr(row, "mod_id", row))
    optional = bool(getattr(row, "optional", False))
    return ModDependencyRead(
        mod_id=int(dependency_id),
        optional=optional,
    ).model_dump(mode="json", exclude_none=True)


def _serialize_conflict_row(row: object) -> int:
    conflict_id = getattr(row, "conflict", getattr(row, "mod_id", row))
    return int(conflict_id)


def _build_conflict_ids_stmt(mod_id: int, scope: ConflictScope):
    if scope == "outgoing":
        return (
            select(catalog.mods_conflicts.c.conflict.label("mod_id"))
            .where(catalog.mods_conflicts.c.mod_id == mod_id)
            .order_by(catalog.mods_conflicts.c.conflict)
        )
    if scope == "incoming":
        return (
            select(catalog.mods_conflicts.c.mod_id.label("mod_id"))
            .where(catalog.mods_conflicts.c.conflict == mod_id)
            .order_by(catalog.mods_conflicts.c.mod_id)
        )

    conflict_mod_id = case(
        (catalog.mods_conflicts.c.mod_id == mod_id, catalog.mods_conflicts.c.conflict),
        else_=catalog.mods_conflicts.c.mod_id,
    ).label("mod_id")
    return (
        select(conflict_mod_id)
        .where(
            or_(
                catalog.mods_conflicts.c.mod_id == mod_id,
                catalog.mods_conflicts.c.conflict == mod_id,
            )
        )
        .distinct()
        .order_by(conflict_mod_id)
    )


async def _serialize_mod_with_includes(
    session,
    request: Request,
    row: catalog.Mod,
    include: set[str],
    conflicts_scope: ConflictScope,
    *,
    current_vote: int | None = None,
    votes_count: int = 0,
) -> ModRead:
    payload = _serialize_mod_base(row)
    if current_vote is not None:
        payload["current_vote"] = current_vote
    payload["votes_count"] = int(votes_count)
    game_id = getattr(row, "game", None)

    if "short_description" not in include:
        payload.pop("short_description", None)
    if "description" not in include:
        payload.pop("description", None)
    if "dates" not in include:
        payload.pop("created_at", None)
        payload.pop("file_updated_at", None)
        payload.pop("updated_at", None)

    if "game" in include and game_id is not None:
        game = await session.get(catalog.Game, game_id)
        if game is not None:
            payload["game"] = GameRead(
                id=int(getattr(game, "id", game_id)),
                name=str(getattr(game, "name", "")),
                short_description=getattr(game, "short_description", None),
                description=getattr(game, "description", None),
                type=str(getattr(game, "type", "game")),
                source=str(getattr(game, "source", "local")),
                source_id=stringify_source_id(getattr(game, "source_id", None)),
                mods_count=
                int(getattr(game, "mods_count", 0))
                if getattr(game, "mods_count", None) is not None
                else None,
                mods_downloads=
                int(getattr(game, "mods_downloads", 0))
                if getattr(game, "mods_downloads", None) is not None
                else None,
                created_at=getattr(game, "creation_date", None),
            ).model_dump(mode="json", exclude_none=True)

    if "tags" in include:
        tags = (
            await session.execute(
                select(catalog.Tag)
                .join(catalog.mods_tags)
                .where(catalog.mods_tags.c.mod_id == row.id)
                .options(joinedload(catalog.Tag.group))
                .order_by(catalog.Tag.name)
            )
        ).scalars().all()
        payload["tags"] = [serialize_tag(tag).model_dump(mode="json", exclude_none=True) for tag in tags]

    if "dependencies" in include:
        dependencies = (
            await session.execute(
                select(
                    catalog.mods_dependencies.c.dependence,
                    catalog.mods_dependencies.c.optional,
                )
                .where(
                    catalog.mods_dependencies.c.mod_id == row.id
                )
                .order_by(catalog.mods_dependencies.c.dependence)
            )
        ).all()
        payload["dependencies"] = {
            "count": len(dependencies),
            "items": [_serialize_dependency_row(dep) for dep in dependencies],
        }

    if "conflicts" in include:
        conflicts = (
            await session.execute(_build_conflict_ids_stmt(row.id, conflicts_scope))
        ).scalars().all()
        payload["conflicts"] = {
            "count": len(conflicts),
            "items": [_serialize_conflict_row(conflict) for conflict in conflicts],
        }

    if "authors" in include:
        row_results = (
            await session.execute(
                select(account.mod_and_author.c.user_id, account.mod_and_author.c.owner).where(
                    account.mod_and_author.c.mod_id == row.id
                )
            )
        ).all()
        payload["authors"] = {
            int(user_id): {"owner": bool(owner)}
            for user_id, owner in row_results
        }

    if "resources" in include:
        resources = (
            await session.execute(
                select(catalog.Resource)
                .where(
                    catalog.Resource.owner_type == "mods",
                    catalog.Resource.owner_id == row.id,
                )
                .order_by(catalog.Resource.sort_order, catalog.Resource.id)
            )
        ).scalars().all()
        payload["resources"] = await tools.resources_serialize(resources)

    return ModRead.model_validate(payload)


def _sanitize_filename(name: str, mod_id: int) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    safe_chars: list[str] = []
    for ch in name:
        if ch in allowed:
            safe_chars.append(ch)
        elif ch.isspace():
            safe_chars.append("_")
    safe_name = "".join(safe_chars).strip("_")
    return safe_name or f"mod_{mod_id}"


def _download_url(mod_id: int) -> str:
    return f"{STORAGE_URL}/download/archive/mods/{mod_id}/main.zip"


async def _update_game_mod_count(session, game_id: int, delta: int) -> None:
    if delta == 0:
        return

    count_expr = func.coalesce(catalog.Game.mods_count, 0)
    if delta > 0:
        count_expr = count_expr + delta
    else:
        count_expr = count_expr - abs(delta)

    await session.execute(
        update(catalog.Game)
        .where(catalog.Game.id == game_id)
        .values({catalog.Game.mods_count: count_expr})
    )


@router.get(
    "/mods",
    tags=["Mod"],
    summary="List mods",
    description=(
        "Returns a paginated list of public mods by default.\n\n"
        "Set `show_not_public=true` together with `author_id` or `user` to include "
        "non-public mods for that author when access allows it and the mod can still "
        "be shown in the catalog.\n\n"
        "Use filters for IDs, tags, dependency rules, conflict exclusions, source fields, "
        "game, size ranges, and `include` to opt into extra fields such as `description`, `dates`, `game`, "
        "`tags`, `dependencies`, `conflicts`, `authors`, and `resources`.\n\n"
        "Sorting also supports `rating`, which uses the approval percentage stored in the database.\n\n"
        "When `include=conflicts` is requested, `scope` controls whether the response includes "
        "outgoing conflicts, incoming conflicts, or both directions merged together.\n\n"
        "Dependency filters accept bare mod IDs as `any`, or explicit rules such as "
        "`123:required`, `123:optional`, and `123:any` so each mod can be configured independently."
    ),
    status_code=200,
    response_model=ModListResponse,
    response_model_exclude_none=True,
    response_description="Paginated mod list.",
    responses={400: MOD_BAD_REQUEST_RESPONSE},
)
async def list_mods(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of mods to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    sort: str = Query(
        default="-downloads",
        description="Sort field, optionally prefixed with `-` for descending order.",
    ),
    ids: list[int] = Query(default_factory=list, description="Limit results to these mod IDs."),
    tags: list[int] = Query(default_factory=list, description="Require all of these tag IDs."),
    excluded_tags: list[int] = Query(default_factory=list, description="Exclude any mod that has one of these tags."),
    dependencies: list[str] = Query(
        default_factory=list,
        description=(
            "Dependency filters. Use bare mod IDs as `any`, or explicit rules like "
            "`123:required`, `123:optional`, or `123:any`."
        ),
    ),
    excluded_dependencies: list[str] = Query(
        default_factory=list,
        description=(
            "Excluded dependency filters. Use bare mod IDs as `any`, or explicit rules like "
            "`123:required`, `123:optional`, or `123:any`."
        ),
    ),
    excluded_conflicts: list[int] = Query(
        default_factory=list,
        description="Exclude any mod that conflicts with one of these mod IDs.",
    ),
    game_id: int | None = Query(default=None, ge=1, description="Filter by game ID."),
    adult: int = Query(default=-1, ge=-1, le=1, description="Adult content filter: -1 any, 0 false, 1 true."),
    sources: list[str] = Query(default_factory=list, description="Source names to filter by."),
    source_ids: list[str] = Query(default_factory=list, description="Source-specific IDs to filter by."),
    author_id: int | None = Query(default=None, ge=1, description="Filter by author user ID."),
    user: int | None = Query(default=None, ge=1, description="Backward-compatible alias for `author_id`."),
    show_not_public: bool = Query(
        default=False,
        description=(
            "Include non-public mods for the selected author when access allows it "
            "and the mod remains catalog-visible."
        ),
    ),
    size_min: int | None = Query(default=None, ge=0, description="Minimum archive size in bytes."),
    size_max: int | None = Query(default=None, ge=0, description="Maximum archive size in bytes."),
    size_unpacked_min: int | None = Query(default=None, ge=0, description="Minimum unpacked size in bytes."),
    size_unpacked_max: int | None = Query(default=None, ge=0, description="Maximum unpacked size in bytes."),
    name: str | None = Query(default=None, max_length=LIMITS.mod.name_max, description="Case-insensitive substring filter for the mod name."),
    conflicts_scope: ConflictScope = Query(
        default="all",
        alias="scope",
        description=(
            "Controls which conflict directions are returned when `include=conflicts` is used: "
            "outgoing, incoming, or the merged union of both."
        ),
    ),
    include: list[ModIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in each mod object.",
    ),
):
    include_set = _normalize_include(request, include)
    source_ids = [item for item in (stringify_source_id(value) for value in source_ids) if item is not None]
    if size_min is not None and size_max is not None and size_min > size_max:
        raise standarts.BadRequestError(
            detail="Minimum size cannot exceed maximum size.",
            instance=str(request.url),
            code="INVALID_SIZE_RANGE",
        )
    if (
        size_unpacked_min is not None
        and size_unpacked_max is not None
        and size_unpacked_min > size_unpacked_max
    ):
        raise standarts.BadRequestError(
            detail="Minimum unpacked size cannot exceed maximum unpacked size.",
            instance=str(request.url),
            code="INVALID_SIZE_RANGE",
        )
    if author_id is None:
        author_id = user
    show_not_public = bool(show_not_public and author_id is not None)

    dependent_mod = aliased(catalog.Mod)
    dependents_count_stmt = (
        select(func.count(func.distinct(catalog.mods_dependencies.c.mod_id)))
        .select_from(
            catalog.mods_dependencies.join(
                dependent_mod, dependent_mod.id == catalog.mods_dependencies.c.mod_id
            )
        )
        .where(
            catalog.mods_dependencies.c.dependence == catalog.Mod.id,
            dependent_mod.condition == 0,
            dependent_mod.public == 0,
        )
        .correlate(catalog.Mod)
        .scalar_subquery()
    )

    try:
        sort_clause = tools.sort_mods(sort, dependents_count_stmt)
    except KeyError as exc:
        _raise_unsupported_sort(request, exc.args[0] if exc.args else str(exc))

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Mod).where(catalog.Mod.condition == 0)
        if author_id is None:
            stmt = stmt.where(catalog.Mod.public == 0)
        if ids:
            stmt = stmt.where(catalog.Mod.id.in_(ids))
        if game_id is not None:
            stmt = stmt.where(catalog.Mod.game == game_id)
        if adult in (0, 1):
            stmt = stmt.where(catalog.Mod.adult == bool(adult))
        if sources:
            stmt = stmt.where(catalog.Mod.source.in_(sources))
        if source_ids:
            stmt = stmt.where(catalog.Mod.source_id.in_(source_ids))
        if author_id is not None:
            stmt = stmt.where(
                catalog.Mod.id.in_(
                    select(account.mod_and_author.c.mod_id).where(
                        account.mod_and_author.c.user_id == author_id
                    )
                )
            )
        if name:
            stmt = stmt.where(catalog.Mod.name.ilike(f"%{name}%"))
        if size_min is not None:
            stmt = stmt.where(catalog.Mod.size >= size_min)
        if size_max is not None:
            stmt = stmt.where(catalog.Mod.size <= size_max)
        if size_unpacked_min is not None:
            stmt = stmt.where(catalog.Mod.size_unpacked >= size_unpacked_min)
        if size_unpacked_max is not None:
            stmt = stmt.where(catalog.Mod.size_unpacked <= size_unpacked_max)
        if tags:
            for tag_id in tags:
                stmt = stmt.where(catalog.Mod.tags.any(catalog.Tag.id == tag_id))
        if excluded_tags:
            stmt = stmt.where(
                ~select(1)
                .where(
                    catalog.mods_tags.c.mod_id == catalog.Mod.id,
                    catalog.mods_tags.c.tag_id.in_(excluded_tags),
                )
                .exists()
            )
        dependency_groups = _collect_dependency_filter_groups(
            request,
            field="dependencies",
            values=dependencies,
        )
        for mode, dependency_ids in dependency_groups.items():
            stmt = _join_dependency_requirement(
                stmt,
                dependency_ids=dependency_ids,
                mode=mode,
            )

        excluded_dependency_groups = _collect_dependency_filter_groups(
            request,
            field="excluded_dependencies",
            values=excluded_dependencies,
        )
        for mode, dependency_ids in excluded_dependency_groups.items():
            stmt = _exclude_dependency_requirement(
                stmt,
                dependency_ids=dependency_ids,
                mode=mode,
            )
        if excluded_conflicts:
            stmt = stmt.where(
                ~select(1)
                .where(
                    or_(
                        and_(
                            catalog.mods_conflicts.c.mod_id == catalog.Mod.id,
                            catalog.mods_conflicts.c.conflict.in_(excluded_conflicts),
                        ),
                        and_(
                            catalog.mods_conflicts.c.conflict == catalog.Mod.id,
                            catalog.mods_conflicts.c.mod_id.in_(excluded_conflicts),
                        ),
                    )
                )
                .exists()
            )
        if show_not_public:
            candidate_ids = [
                int(mod_id)
                for mod_id in (
                    await session.execute(
                        stmt.with_only_columns(catalog.Mod.id).order_by(None)
                    )
                ).scalars().all()
            ]
            if not candidate_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            allowed_ids = await tools.access_mods(
                request=request,
                mods_ids=candidate_ids,
                author_id=author_id,
                catalog=True,
                check_mode=True,
            )
            if not allowed_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            stmt = stmt.where(catalog.Mod.id.in_(allowed_ids))
        else:
            stmt = stmt.where(catalog.Mod.public == 0)

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (await session.execute(stmt.order_by(sort_clause).offset(offset).limit(page_size))).scalars().all()
        mod_ids = [int(row.id) for row in rows]
        vote_counts = await _load_mod_vote_counts(mod_ids)

        items: list[dict[str, object]] = []
        for row in rows:
            row_vote_count = vote_counts.get(int(row.id), 0)
            if include_set:
                items.append(
                    (
                        await _serialize_mod_with_includes(
                            session,
                            request,
                            row,
                            include_set,
                            conflicts_scope,
                            votes_count=row_vote_count,
                        )
                    ).model_dump(mode="json", exclude_none=True)
                )
            else:
                payload = _serialize_mod_base(row)
                payload["votes_count"] = row_vote_count
                payload.pop("short_description", None)
                payload.pop("description", None)
                payload.pop("created_at", None)
                payload.pop("file_updated_at", None)
                payload.pop("updated_at", None)
                items.append(payload)

    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/mods/feed",
    tags=["Mod"],
    summary="Contextual size hints for the mod catalog",
    description=(
        "Returns contextual size hints for the public mod catalog.\n\n"
        "The UI uses this to configure range sliders without loading the full list.\n\n"
        "When `show_not_public=true` is combined with an author filter, the feed "
        "matches the visibility rules used by `/mods`."
    ),
    status_code=200,
    response_model=ModFeedRead,
    response_model_exclude_none=True,
    response_description="Catalog size hints.",
)
async def get_mod_feed(
    request: Request,
    game: int = Query(-1, description="Optional game ID to scope the size hints."),
    author_id: int | None = Query(default=None, ge=1, description="Filter by author user ID."),
    user: int | None = Query(default=None, ge=1, description="Backward-compatible alias for `author_id`."),
    show_not_public: bool = Query(
        default=False,
        description=(
            "Include non-public mods for the selected author when access allows it "
            "and the mod remains catalog-visible."
        ),
    ),
):
    if author_id is None:
        author_id = user
    show_not_public = bool(show_not_public and author_id is not None)

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Mod).where(catalog.Mod.condition == 0)

        if author_id is not None:
            stmt = stmt.where(
                catalog.Mod.id.in_(
                    select(account.mod_and_author.c.mod_id).where(
                        account.mod_and_author.c.user_id == author_id
                    )
                )
            )

        if game > 0:
            stmt = stmt.where(catalog.Mod.game == game)

        tag_groups = await _load_mod_feed_tag_groups(session, game)

        if show_not_public:
            candidate_ids = [
                int(mod_id)
                for mod_id in (
                    await session.execute(
                        stmt.with_only_columns(catalog.Mod.id).order_by(None)
                    )
                ).scalars().all()
            ]
            if not candidate_ids:
                return {
                    "count": 0,
                    "size": {"min": None, "max": None},
                    "size_unpacked": {"min": None, "max": None},
                    "tag_groups": tag_groups,
                }

            allowed_ids = await tools.access_mods(
                request=request,
                mods_ids=candidate_ids,
                author_id=author_id,
                catalog=True,
                check_mode=True,
            )
            if not allowed_ids:
                return {
                    "count": 0,
                    "size": {"min": None, "max": None},
                    "size_unpacked": {"min": None, "max": None},
                    "tag_groups": tag_groups,
                }

            stmt = stmt.where(catalog.Mod.id.in_(allowed_ids))
        else:
            stmt = stmt.where(catalog.Mod.public == 0)

        filtered = stmt.order_by(None).subquery()
        count_stmt = select(func.count()).select_from(filtered)
        min_stmt = select(func.min(filtered.c.size))
        max_stmt = select(func.max(filtered.c.size))
        unpacked_min_stmt = select(func.min(filtered.c.size_unpacked))
        unpacked_max_stmt = select(func.max(filtered.c.size_unpacked))

        mods_count = int((await session.scalar(count_stmt)) or 0)
        size_min = await session.scalar(min_stmt)
        size_max = await session.scalar(max_stmt)
        size_unpacked_min = await session.scalar(unpacked_min_stmt)
        size_unpacked_max = await session.scalar(unpacked_max_stmt)

    return {
        "count": mods_count,
        "size": {
            "min": int(size_min) if size_min is not None else None,
            "max": int(size_max) if size_max is not None else None,
        },
        "size_unpacked": {
            "min": int(size_unpacked_min) if size_unpacked_min is not None else None,
            "max": int(size_unpacked_max) if size_unpacked_max is not None else None,
        },
        "tag_groups": tag_groups,
    }


@router.get(
    "/mods/{mod_id}",
    tags=["Mod"],
    summary="Get mod",
    description=(
        "Returns a mod by ID.\n\n"
        "Use `include` to opt into extra fields such as `description`, `dates`, "
        "`game`, `tags`, `dependencies`, `conflicts`, `authors`, and `resources`.\n\n"
        "When `include=conflicts` is used, `scope` controls whether the response includes "
        "outgoing conflicts, incoming conflicts, or both directions merged together."
    ),
    status_code=200,
    response_model=ModRead,
    response_model_exclude_none=True,
    response_description="Mod resource.",
    responses={400: MOD_BAD_REQUEST_RESPONSE, 404: MOD_NOT_FOUND_RESPONSE},
)
async def get_mod(
    request: Request,
    mod_id: int,
    conflicts_scope: ConflictScope = Query(
        default="all",
        alias="scope",
        description=(
            "Controls which conflict directions are returned when `include=conflicts` is used: "
            "outgoing, incoming, or the merged union of both."
        ),
    ),
    include: list[ModIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in the mod object.",
    ),
) -> ModRead:
    include_set = _normalize_include(request, include)

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Mod, mod_id)
        if row is None:
            _raise_mod_not_found(request)

        if row.public > 0 or row.condition != 0:
            await tools.access_mods(request=request, mods_ids=[mod_id])

        current_vote, votes_count = await _load_mod_vote_state(request, mod_id)

        if include_set:
            return await _serialize_mod_with_includes(
                session,
                request,
                row,
                include_set,
                conflicts_scope,
                current_vote=current_vote,
                votes_count=votes_count,
            )
        payload = _serialize_mod_base(row)
        if current_vote is not None:
            payload["current_vote"] = current_vote
        payload["votes_count"] = votes_count
        return ModRead.model_validate(payload)


@router.put(
    "/mods/{mod_id}/rating",
    tags=["Mod"],
    summary="Rate mod",
    description=(
        "Sets the current user's vote for a mod.\n\n"
        "Send `value=1` to upvote, `value=-1` to downvote, or `value=0` to clear "
        "the current vote. Mod ratings are stored as approval percentage in the "
        "database."
    ),
    status_code=200,
    response_model=ModRatingRead,
    response_model_exclude_none=True,
    response_description="Updated mod rating.",
    responses={401: standarts.UNAUTHORIZED_RESPONSE_SPEC, 403: standarts.FORBIDDEN_RESPONSE_SPEC, 404: MOD_NOT_FOUND_RESPONSE},
)
async def put_mod_rating(
    request: Request,
    mod_id: int,
    payload: RatingVoteUpsert,
) -> ModRatingRead:
    vote_access = await tools.access_vote_for_reputation(request=request)
    if not vote_access.vote_for_reputation.value:
        _raise_vote_right_denied(request, vote_access.vote_for_reputation)

    async with account.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)

        await tools.access_mods(request=request, mods_ids=[mod_id], catalog=True)

        summary = await reputation.apply_mod_vote(
            session,
            voter_id=int(vote_access.owner_id),
            mod=mod,
            value=int(payload.value),
        )
        await session.commit()
        await mod_events.publish_mod_event(
            mod_events.MOD_EVENT_RATED,
            mod_id,
            getattr(mod, "name", ""),
            getattr(mod, "description", None),
            getattr(mod, "public", 0),
            extra={
                "voter_id": int(vote_access.owner_id),
                "vote_value": int(payload.value),
                "rating": summary.rating,
                "votes_count": summary.votes_count,
            },
        )
        return ModRatingRead(
            mod_id=mod_id,
            rating=summary.rating,
            votes_count=summary.votes_count,
        )


@router.post(
    "/mods",
    tags=["Mod"],
    summary="Create mod",
    description="Creates a new draft mod. Authentication and add permissions are required.",
    status_code=201,
    response_model=ModRead,
    response_model_exclude_none=True,
    response_description="Created mod resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_TARGET_NOT_FOUND_RESPONSE,
        409: MOD_CONFLICT_RESPONSE,
    },
)
async def create_mod(
    response: Response,
    request: Request,
    payload: ModCreate,
) -> ModRead:
    access_result = await tools.access_mod_add(request=request)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    required_right = access_result.anonymous_add if payload.without_author else access_result.add
    if not required_right.value:
        raise standarts.ForbiddenError(
            detail=required_right.reason,
            instance=str(request.url),
            context={"reason_code": required_right.reason_code},
        )

    if not await tools.check_game_exists(payload.game_id):
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Game not found.",
            code="GAME_NOT_FOUND",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        candidate_source_id = stringify_source_id(payload.source_id)
        if candidate_source_id is not None and payload.source != "local":
            # Draft mods are allowed to coexist while they are still uploading.
            # Only a loaded mod should block a new source binding.
            existing = await session.scalar(
                select(catalog.Mod.id).where(
                    catalog.Mod.source == payload.source,
                    catalog.Mod.source_id == candidate_source_id,
                    catalog.Mod.condition == 0,
                )
            )
            if existing is not None:
                raise standarts.StandardAPIError(
                    status_code=409,
                    title="Conflict",
                    detail="Mod source already exists.",
                    code="MOD_SOURCE_ALREADY_EXISTS",
                    instance=str(request.url),
                    context={"source": payload.source, "source_id": candidate_source_id},
                )

        mod = catalog.Mod(
            name=payload.name,
            short_description=payload.short_description,
            description=payload.description,
            size=0,
            size_unpacked=None,
            condition=1,
            public=payload.public,
            date_creation=datetime.now(),
            date_update_file=datetime.now(),
            date_edit=datetime.now(),
            source=payload.source,
            source_id=candidate_source_id,
            git_url=payload.git_url,
            downloads=0,
            game=payload.game_id,
            adult=payload.adult,
        )
        session.add(mod)
        await session.flush()
        if not payload.without_author and access_result.owner_id >= 0:
            await session.execute(
                account.mod_and_author.insert().values(
                    mod_id=mod.id, user_id=access_result.owner_id, owner=True
                )
            )
        await session.commit()
        response.headers["Location"] = f"/mods/{mod.id}"
        return ModRead.model_validate(_serialize_mod_base(mod))


@router.patch(
    "/mods/{mod_id}",
    tags=["Mod"],
    summary="Update mod",
    description=(
        "Updates an existing mod.\n\n"
        "When `game_id` changes for a published mod, the game counters are updated "
        "to keep `mods_count` and `mods_downloads` consistent."
    ),
    status_code=200,
    response_model=ModRead,
    response_model_exclude_none=True,
    response_description="Updated mod resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_TARGET_NOT_FOUND_RESPONSE,
        409: MOD_CONFLICT_RESPONSE,
    },
)
async def patch_mod(
    request: Request,
    mod_id: int,
    payload: ModPatch,
) -> ModRead:
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name", "source", "public", "adult"),
        detail="Mod patch fields cannot be null.",
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

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Mod, mod_id)
        if row is None:
            _raise_mod_not_found(request)

        current_game_id = (
            int(getattr(row, "game", 0)) if getattr(row, "game", None) is not None else None
        )
        row_condition = int(getattr(row, "condition", 0) or 0)

        if "game_id" in data and data["game_id"] is not None and not await tools.check_game_exists(int(data["game_id"])):
            raise standarts.StandardAPIError(
                status_code=404,
                title="Not Found",
                detail="Game not found.",
                code="GAME_NOT_FOUND",
                instance=str(request.url),
            )

        if "source" in data or "source_id" in data:
            candidate_source = data.get("source", row.source)
            candidate_source_id = stringify_source_id(data.get("source_id", row.source_id))
            if candidate_source_id is not None and candidate_source != "local":
                # Keep uploading drafts flexible; loaded mods still remain unique per source.
                existing = await session.scalar(
                    select(catalog.Mod.id).where(
                        catalog.Mod.id != mod_id,
                        catalog.Mod.source == candidate_source,
                        catalog.Mod.source_id == candidate_source_id,
                        catalog.Mod.condition == 0,
                    )
                )
                if existing is not None:
                    raise standarts.StandardAPIError(
                        status_code=409,
                        title="Conflict",
                        detail="Mod source already exists.",
                        code="MOD_SOURCE_ALREADY_EXISTS",
                        instance=str(request.url),
                        context={"source": candidate_source, "source_id": candidate_source_id},
                    )
            row.source = candidate_source
            row.source_id = candidate_source_id
        if "git_url" in data:
            row.git_url = data["git_url"] if data["git_url"] is None else str(data["git_url"])

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

        if "game_id" in data and row_condition == 0:
            new_game_id = (
                int(data["game_id"]) if data["game_id"] is not None else None
            )
            if current_game_id != new_game_id:
                if current_game_id is not None:
                    await _update_game_mod_count(session, current_game_id, -1)
                if new_game_id is not None:
                    await _update_game_mod_count(session, new_game_id, 1)

        row.date_edit = datetime.now()
        await session.commit()
        return ModRead.model_validate(_serialize_mod_base(row))


@router.delete(
    "/mods/{mod_id}",
    tags=["Mod"],
    summary="Delete mod",
    description="Deletes a mod and all related storage resources and associations.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_NOT_FOUND_RESPONSE,
    },
)
async def delete_mod(request: Request, mod_id: int) -> Response:
    mod_access = await tools.access_mod_action(request=request, mod_id=mod_id)
    if not mod_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not mod_access.delete.value:
        raise standarts.ForbiddenError(
            detail=mod_access.delete.reason,
            instance=str(request.url),
            context={"reason_code": mod_access.delete.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)

        if not await tools.delete_resources(owner_type="mods", owner_id=mod_id):
            raise standarts.InternalServerError(
                detail="Failed to delete mod resources.",
                instance=str(request.url),
                code="STORAGE_DELETE_FAILED",
            )

        if not await tools.storage_file_delete(type="archive", path=f"mods/{mod_id}/main.zip"):
            raise standarts.InternalServerError(
                detail="Failed to delete mod archive.",
                instance=str(request.url),
                code="STORAGE_DELETE_FAILED",
            )

        await session.execute(
            delete(catalog.mods_dependencies).where(
                (catalog.mods_dependencies.c.mod_id == mod_id)
                | (catalog.mods_dependencies.c.dependence == mod_id)
            )
        )
        await session.execute(
            delete(catalog.mods_conflicts).where(
                (catalog.mods_conflicts.c.mod_id == mod_id)
                | (catalog.mods_conflicts.c.conflict == mod_id)
            )
        )
        await session.execute(delete(catalog.mods_tags).where(catalog.mods_tags.c.mod_id == mod_id))
        await session.execute(
            delete(account.mod_and_author).where(account.mod_and_author.c.mod_id == mod_id)
        )
        await session.execute(delete(catalog.Mod).where(catalog.Mod.id == mod_id))
        mod_game = getattr(mod, "game", None)
        if mod_game is not None:
            await session.execute(
                update(catalog.Game)
                .where(catalog.Game.id == mod_game)
                .values({catalog.Game.mods_count: func.coalesce(catalog.Game.mods_count, 0) - 1})
            )
        await session.commit()

    await mod_events.publish_mod_event(
        mod_events.MOD_EVENT_DELETED,
        mod_id,
        getattr(mod, "name", ""),
        getattr(mod, "description", None),
        getattr(mod, "public", 0),
    )
    return Response(status_code=204)


async def _register_download(request: Request, mod_id: int) -> dict[str, str]:
    await tools.access_mods(request=request, mods_ids=[mod_id])

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)

        await session.execute(
            update(catalog.Mod)
            .where(catalog.Mod.id == mod_id)
            .values({catalog.Mod.downloads: func.coalesce(catalog.Mod.downloads, 0) + 1})
        )
        mod_game = getattr(mod, "game", None)
        if mod_game is not None:
            await session.execute(
                update(catalog.Game)
                .where(catalog.Game.id == mod_game)
                .values({catalog.Game.mods_downloads: func.coalesce(catalog.Game.mods_downloads, 0) + 1})
            )
        await session.commit()

    await mod_events.publish_mod_event(
        mod_events.MOD_EVENT_CHANGED,
        mod_id,
        getattr(mod, "name", ""),
        getattr(mod, "description", None),
        getattr(mod, "public", 0),
    )

    filename = _sanitize_filename(getattr(mod, "name", "") or "", mod_id)
    return {
        "download_url": f"{_download_url(mod_id)}?filename={quote(filename)}",
        "filename": filename,
    }


@router.post(
    "/mods/{mod_id}/download-url",
    tags=["Mod"],
    summary="Get mod download URL",
    description="Registers a download event and returns a one-shot storage download URL for the mod archive.",
    status_code=201,
    response_model=ModDownloadUrlRead,
    response_model_exclude_none=True,
    response_description="Mod archive download URL.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_NOT_FOUND_RESPONSE,
    },
)
async def download_url(request: Request, mod_id: int) -> ModDownloadUrlRead:
    download = await _register_download(request, mod_id)
    return ModDownloadUrlRead(
        mod_id=mod_id,
        download_url=download["download_url"],
        filename=download["filename"],
        expires_at=None,
    )


@router.get(
    "/mods/{mod_id}/tags",
    tags=["Mod", "Tag"],
    summary="List mod tags",
    description="Returns all tags attached to a mod.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag list.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_NOT_FOUND_RESPONSE,
    },
)
async def get_mod_tags(request: Request, mod_id: int) -> dict[str, object]:
    await tools.access_mods(request=request, mods_ids=[mod_id])

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)
        rows = (
            await session.execute(
                select(catalog.Tag)
                .join(catalog.mods_tags)
                .where(catalog.mods_tags.c.mod_id == mod_id)
                .options(joinedload(catalog.Tag.group))
                .order_by(catalog.Tag.name)
            )
        ).scalars().all()

    items = [serialize_tag(tag).model_dump(mode="json", exclude_none=True) for tag in rows]
    return make_list_response(items, page=0, page_size=max(len(items), 1), total=len(items))


@router.get(
    "/mods/{mod_id}/dependencies",
    tags=["Mod"],
    summary="List mod dependencies",
    description="Returns all dependency relations attached to a mod, including optional ones.",
    status_code=200,
    response_model=ModDependencyCollectionRead,
    response_model_exclude_none=True,
    response_description="Dependency collection with optional flags.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_NOT_FOUND_RESPONSE,
    },
)
async def get_mod_dependencies(request: Request, mod_id: int) -> dict[str, object]:
    await tools.access_mods(request=request, mods_ids=[mod_id])

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)
        dependencies = (
            await session.execute(
                select(
                    catalog.mods_dependencies.c.dependence,
                    catalog.mods_dependencies.c.optional,
                )
                .where(
                    catalog.mods_dependencies.c.mod_id == mod_id
                )
                .order_by(catalog.mods_dependencies.c.dependence)
            )
        ).all()

    items = [_serialize_dependency_row(dep) for dep in dependencies]
    return {"count": len(items), "items": items}


@router.get(
    "/mods/{mod_id}/conflicts",
    tags=["Mod"],
    summary="List mod conflicts",
    description=(
        "Returns conflicting mod IDs attached to a mod.\n\n"
        "Use `scope` to choose outgoing conflicts, incoming conflicts, or both directions merged together."
    ),
    status_code=200,
    response_model=IntCollectionRead,
    response_model_exclude_none=True,
    response_description="Conflict collection.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MOD_NOT_FOUND_RESPONSE,
    },
)
async def get_mod_conflicts(
    request: Request,
    mod_id: int,
    conflicts_scope: ConflictScope = Query(
        default="all",
        alias="scope",
        description=(
            "Controls which conflict directions are returned: outgoing, incoming, or the merged union of both."
        ),
    ),
) -> dict[str, object]:
    await tools.access_mods(request=request, mods_ids=[mod_id])

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            _raise_mod_not_found(request)
        conflicts = (
            await session.execute(
                _build_conflict_ids_stmt(mod_id, conflicts_scope)
            )
        ).scalars().all()

    items = [_serialize_conflict_row(conflict) for conflict in conflicts]
    return {"count": len(items), "items": items}
