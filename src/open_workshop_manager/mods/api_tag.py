"""Tag REST routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import and_, delete, func, insert, literal, select
from sqlalchemy.orm import joinedload

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    TagCreate,
    TagListResponse,
    TagMerge,
    TagPatch,
    TagRead,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import (
    serialize_tag,
    serialize_tag_group,
)
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

TagIncludeField = Literal["orphaned", "group", "games"]

TAG_INCLUDE_FIELDS = {"orphaned", "group", "games"}

TAG_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The tag request contains invalid filters or include fields.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

TAG_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Tag not found.",
        code="TAG_NOT_FOUND",
    ),
    "Tag not found.",
)


TAG_GROUP_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Tag group not found.",
        code="TAG_GROUP_NOT_FOUND",
    ),
    "Tag group not found.",
)


def _serialize_tag(tag: catalog.Tag) -> TagRead:
    return serialize_tag(tag)


def _raise_tag_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Tag not found.",
        code="TAG_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_tag_group_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Tag group not found.",
        code="TAG_GROUP_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_unsupported_include(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported include field.",
        code="UNSUPPORTED_INCLUDE_FIELD",
        instance=str(request.url),
        context={"field": field, "allowed": sorted(TAG_INCLUDE_FIELDS)},
    )


def _normalize_include(request: Request, include: list[str]) -> set[str]:
    normalized = {item.strip() for item in include if item and item.strip()}
    unknown = normalized.difference(TAG_INCLUDE_FIELDS)
    if unknown:
        _raise_unsupported_include(request, sorted(unknown)[0])
    return normalized


def _tag_is_orphan_condition():
    return and_(
        ~select(1)
        .select_from(catalog.mods_tags)
        .where(catalog.mods_tags.c.tag_id == catalog.Tag.id)
        .exists(),
        ~select(1)
        .select_from(catalog.modpacks_tags)
        .where(catalog.modpacks_tags.c.tag_id == catalog.Tag.id)
        .exists(),
        ~select(1)
        .select_from(catalog.allowed_mods_tags)
        .where(catalog.allowed_mods_tags.c.tag_id == catalog.Tag.id)
        .exists(),
    )


def _serialize_tag_base(tag: catalog.Tag) -> dict[str, object]:
    return {
        "id": int(tag.id),
        "name": str(tag.name),
    }


async def _load_tag_games_map(session, tag_ids: list[int]) -> dict[int, list[int]]:
    if not tag_ids:
        return {}

    rows = (
        await session.execute(
            select(
                catalog.allowed_mods_tags.c.tag_id, catalog.allowed_mods_tags.c.game_id
            )
            .where(catalog.allowed_mods_tags.c.tag_id.in_(tag_ids))
            .order_by(
                catalog.allowed_mods_tags.c.tag_id, catalog.allowed_mods_tags.c.game_id
            )
        )
    ).all()
    games_by_tag: dict[int, list[int]] = {int(tag_id): [] for tag_id in tag_ids}
    for tag_id, game_id in rows:
        games_by_tag.setdefault(int(tag_id), []).append(int(game_id))
    return games_by_tag


async def _load_orphaned_tag_ids(session, tag_ids: list[int]) -> set[int]:
    if not tag_ids:
        return set()

    rows = (
        (
            await session.execute(
                select(catalog.Tag.id)
                .where(catalog.Tag.id.in_(tag_ids))
                .where(_tag_is_orphan_condition())
                .order_by(catalog.Tag.id)
            )
        )
        .scalars()
        .all()
    )
    return {int(tag_id) for tag_id in rows}


async def _serialize_tag_with_includes(
    session,
    tag: catalog.Tag,
    include: set[str],
    *,
    orphaned: bool | None = None,
) -> TagRead:
    payload = _serialize_tag_base(tag)

    if "group" in include:
        group = getattr(tag, "group", None)
        if group is not None:
            payload["group"] = serialize_tag_group(group).model_dump(
                mode="json", exclude_none=True
            )

    if "games" in include:
        game_ids = (
            (
                await session.execute(
                    select(catalog.allowed_mods_tags.c.game_id)
                    .where(catalog.allowed_mods_tags.c.tag_id == tag.id)
                    .order_by(catalog.allowed_mods_tags.c.game_id)
                )
            )
            .scalars()
            .all()
        )
        payload["games"] = [int(game_id) for game_id in game_ids]

    if "orphaned" in include:
        if orphaned is None:
            orphaned = bool(
                await session.scalar(
                    select(_tag_is_orphan_condition()).where(catalog.Tag.id == tag.id)
                )
            )
        payload["orphaned"] = bool(orphaned)

    return TagRead.model_validate(payload)


async def _serialize_tags_with_includes(
    session,
    tags: list[catalog.Tag],
    include: set[str],
    *,
    orphaned: bool | None = None,
) -> list[TagRead]:
    tag_ids = [int(tag.id) for tag in tags]
    games_by_tag = (
        await _load_tag_games_map(session, tag_ids) if "games" in include else {}
    )
    orphaned_ids = (
        await _load_orphaned_tag_ids(session, tag_ids)
        if "orphaned" in include and orphaned is None
        else set()
    )

    items: list[TagRead] = []
    for tag in tags:
        payload = _serialize_tag_base(tag)

        if "group" in include:
            group = getattr(tag, "group", None)
            if group is not None:
                payload["group"] = serialize_tag_group(group).model_dump(
                    mode="json", exclude_none=True
                )

        if "games" in include:
            payload["games"] = games_by_tag.get(int(tag.id), [])

        if "orphaned" in include:
            payload["orphaned"] = bool(
                orphaned if orphaned is not None else int(tag.id) in orphaned_ids
            )

        items.append(TagRead.model_validate(payload))

    return items


async def _ensure_tag_crud_access(request: Request, *right_names: str) -> None:
    access_result = await tools.access_tags(request=request)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    for right_name in right_names:
        right = getattr(access_result, right_name, None)
        if not getattr(right, "value", False):
            raise standarts.ForbiddenError(
                detail=getattr(right, "reason", "Forbidden"),
                instance=str(request.url),
                context={"reason_code": getattr(right, "reason_code", "forbidden")},
            )


async def _copy_tag_associations(
    session,
    table,
    owner_column,
    source_tag_ids: list[int],
    target_tag_id: int,
) -> None:
    rows = (
        select(owner_column, literal(target_tag_id))
        .where(table.c.tag_id.in_(source_tag_ids))
        .distinct()
    )
    await session.execute(
        insert(table).from_select(
            [owner_column.name, table.c.tag_id.name],
            rows,
        )
    )


@router.get(
    "/tags",
    tags=["Tag"],
    summary="List tags",
    description=(
        "Returns a paginated list of tags with optional name, ID, and game filters.\n\n"
        "Use `include` to opt into `orphaned`, `group`, and `games`."
    ),
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag list.",
    responses={400: TAG_BAD_REQUEST_RESPONSE},
)
async def list_tags(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of tags to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.tag.name_max,
        description="Case-insensitive substring filter for the tag name.",
    ),
    ids: list[int] = Query(
        default_factory=list, description="Limit results to these tag IDs."
    ),
    game_id: int | None = Query(default=None, ge=1, description="Filter by game ID."),
    include: list[TagIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in each tag object.",
    ),
):
    include_set = _normalize_include(request, include)
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = (
            select(func.count())
            .select_from(catalog.Tag)
            .where(catalog.Tag.group_id.is_(None))
        )
        list_stmt = select(catalog.Tag).where(catalog.Tag.group_id.is_(None))
        if "group" in include_set:
            list_stmt = list_stmt.options(joinedload(catalog.Tag.group))

        if name:
            condition = catalog.Tag.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if ids:
            count_stmt = count_stmt.where(catalog.Tag.id.in_(ids))
            list_stmt = list_stmt.where(catalog.Tag.id.in_(ids))

        if game_id:
            condition = catalog.Tag.associated_games.any(catalog.Game.id == game_id)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (
            (await session.execute(list_stmt.offset(offset).limit(page_size)))
            .scalars()
            .all()
        )
        items = await _serialize_tags_with_includes(session, rows, include_set)

    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/tags/orphaned",
    tags=["Tag"],
    summary="List orphaned tags",
    description=(
        "Returns tags that are not attached to any game, mod, or modpack. Admin privileges are required.\n\n"
        "Use `include` to opt into `orphaned`, `group`, and `games`."
    ),
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated orphan tag list.",
    responses={
        400: TAG_BAD_REQUEST_RESPONSE,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def list_orphaned_tags(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of tags to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.tag.name_max,
        description="Case-insensitive substring filter for the tag name.",
    ),
    ids: list[int] = Query(
        default_factory=list, description="Limit results to these tag IDs."
    ),
    include: list[TagIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in each tag object.",
    ),
):
    await tools.access_admin(request=request)
    include_set = _normalize_include(request, include)

    orphan_condition = _tag_is_orphan_condition()
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = (
            select(func.count()).select_from(catalog.Tag).where(orphan_condition)
        )
        list_stmt = select(catalog.Tag).where(orphan_condition)
        if "group" in include_set:
            list_stmt = list_stmt.options(joinedload(catalog.Tag.group))

        if name:
            condition = catalog.Tag.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if ids:
            count_stmt = count_stmt.where(catalog.Tag.id.in_(ids))
            list_stmt = list_stmt.where(catalog.Tag.id.in_(ids))

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (
            (
                await session.execute(
                    list_stmt.order_by(catalog.Tag.name, catalog.Tag.id)
                    .offset(offset)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        items = await _serialize_tags_with_includes(
            session, rows, include_set, orphaned=True
        )

    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.post(
    "/tags/merge",
    tags=["Tag"],
    summary="Merge tags",
    description=(
        "Creates a new tag from several existing tags, moves all game, mod, and modpack "
        "associations to it, then deletes the source tags. Tag add and delete privileges are required."
    ),
    status_code=201,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Created merged tag resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        400: TAG_BAD_REQUEST_RESPONSE,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: TAG_NOT_FOUND_RESPONSE,
    },
)
async def merge_tags(
    response: Response, request: Request, payload: TagMerge
) -> TagRead:
    await _ensure_tag_crud_access(request, "delete", "add")

    source_tag_ids = list(dict.fromkeys(int(tag_id) for tag_id in payload.tags))
    if len(source_tag_ids) < 2:
        raise standarts.StandardAPIError(
            status_code=400,
            title="Bad Request",
            detail="At least two distinct tags are required for merge.",
            code="TAG_MERGE_TOO_SMALL",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        group = None
        if payload.group_id is not None:
            group = await session.get(catalog.TagGroup, payload.group_id)
            if group is None:
                _raise_tag_group_not_found(request)

        rows = (
            (
                await session.execute(
                    select(catalog.Tag)
                    .where(catalog.Tag.id.in_(source_tag_ids))
                    .options(joinedload(catalog.Tag.group))
                )
            )
            .scalars()
            .all()
        )
        tags_by_id = {int(tag.id): tag for tag in rows}
        missing_ids = [tag_id for tag_id in source_tag_ids if tag_id not in tags_by_id]
        if missing_ids:
            raise standarts.StandardAPIError(
                status_code=404,
                title="Not Found",
                detail="One or more tags not found.",
                code="TAG_NOT_FOUND",
                instance=str(request.url),
                context={"missing_ids": missing_ids},
            )

        source_tags = [tags_by_id[tag_id] for tag_id in source_tag_ids]
        tag = catalog.Tag(name=payload.title or str(source_tags[0].name), group=group)
        session.add(tag)
        await session.flush()

        await _copy_tag_associations(
            session,
            catalog.mods_tags,
            catalog.mods_tags.c.mod_id,
            source_tag_ids,
            int(tag.id),
        )
        await _copy_tag_associations(
            session,
            catalog.allowed_mods_tags,
            catalog.allowed_mods_tags.c.game_id,
            source_tag_ids,
            int(tag.id),
        )
        await _copy_tag_associations(
            session,
            catalog.modpacks_tags,
            catalog.modpacks_tags.c.modpack_id,
            source_tag_ids,
            int(tag.id),
        )
        await session.execute(
            delete(catalog.mods_tags).where(
                catalog.mods_tags.c.tag_id.in_(source_tag_ids)
            )
        )
        await session.execute(
            delete(catalog.allowed_mods_tags).where(
                catalog.allowed_mods_tags.c.tag_id.in_(source_tag_ids)
            )
        )
        await session.execute(
            delete(catalog.modpacks_tags).where(
                catalog.modpacks_tags.c.tag_id.in_(source_tag_ids)
            )
        )
        await session.execute(
            delete(catalog.Tag).where(catalog.Tag.id.in_(source_tag_ids))
        )
        await session.commit()

        response.headers["Location"] = f"/tags/{tag.id}"
        return _serialize_tag(tag)


@router.get(
    "/tags/{tag_id}",
    tags=["Tag"],
    summary="Get tag",
    description="Returns a single tag by ID. Use `include` to opt into `orphaned`, `group`, and `games`.",
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Tag resource.",
    responses={400: TAG_BAD_REQUEST_RESPONSE, 404: TAG_NOT_FOUND_RESPONSE},
)
async def get_tag(
    request: Request,
    tag_id: int,
    include: list[TagIncludeField] = Query(
        default_factory=list,
        description="Additional fields to include in the tag object.",
    ),
) -> TagRead:
    include_set = _normalize_include(request, include)
    async with catalog.AsyncSessionLocal() as session:
        options = (joinedload(catalog.Tag.group),) if "group" in include_set else ()
        tag = await session.get(catalog.Tag, tag_id, options=options)

        if tag is None:
            _raise_tag_not_found(request)

        return await _serialize_tag_with_includes(session, tag, include_set)


@router.post(
    "/tags",
    tags=["Tag"],
    summary="Create tag",
    description="Creates a new tag. Tag add privileges are required.",
    status_code=201,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Created tag resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: TAG_GROUP_NOT_FOUND_RESPONSE,
    },
)
async def create_tag(
    response: Response, request: Request, payload: TagCreate
) -> TagRead:
    await _ensure_tag_crud_access(request, "add")

    async with catalog.AsyncSessionLocal() as session:
        group = None
        if payload.group_id is not None:
            group = await session.get(catalog.TagGroup, payload.group_id)
            if group is None:
                _raise_tag_group_not_found(request)

        tag = catalog.Tag(name=payload.name, group=group)
        session.add(tag)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/tags/{tag.id}"
        return _serialize_tag(tag)


@router.patch(
    "/tags/{tag_id}",
    tags=["Tag"],
    summary="Update tag",
    description="Updates the tag name or group. Tag edit privileges are required.",
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Updated tag resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: TAG_NOT_FOUND_RESPONSE,
    },
)
async def patch_tag(
    request: Request,
    tag_id: int,
    payload: TagPatch,
) -> TagRead:
    await _ensure_tag_crud_access(request, "edit")

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name",),
        detail="Tag name cannot be null.",
    )

    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(
            catalog.Tag,
            tag_id,
            options=(joinedload(catalog.Tag.group),),
        )
        if tag is None:
            _raise_tag_not_found(request)

        if "group_id" in data:
            group_id = data.pop("group_id")
            if group_id is None:
                tag.group = None
                tag.group_id = None
            else:
                group = await session.get(catalog.TagGroup, group_id)
                if group is None:
                    _raise_tag_group_not_found(request)
                tag.group = group

        for key, value in data.items():
            setattr(tag, key, value)
        await session.commit()
        return _serialize_tag(tag)


@router.delete(
    "/tags/{tag_id}",
    tags=["Tag"],
    summary="Delete tag",
    description="Deletes a tag and detaches it from all games, mods, and modpacks. Tag delete privileges are required.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: TAG_NOT_FOUND_RESPONSE,
    },
)
async def delete_tag(request: Request, tag_id: int) -> Response:
    await _ensure_tag_crud_access(request, "delete")

    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(catalog.Tag, tag_id)
        if tag is None:
            _raise_tag_not_found(request)

        await session.execute(
            catalog.mods_tags.delete().where(catalog.mods_tags.c.tag_id == tag_id)
        )
        await session.execute(
            catalog.allowed_mods_tags.delete().where(
                catalog.allowed_mods_tags.c.tag_id == tag_id
            )
        )
        await session.execute(
            catalog.modpacks_tags.delete().where(
                catalog.modpacks_tags.c.tag_id == tag_id
            )
        )
        await session.execute(delete(catalog.Tag).where(catalog.Tag.id == tag_id))
        await session.commit()

    return Response(status_code=204)
