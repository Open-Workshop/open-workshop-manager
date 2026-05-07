"""Tag group REST routes."""

from __future__ import annotations

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
    TagGroupCreate,
    TagGroupListResponse,
    TagGroupPatch,
    TagGroupRead,
    TagListResponse,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import serialize_tag, serialize_tag_group
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

TAG_GROUP_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Tag group not found.",
        code="TAG_GROUP_NOT_FOUND",
    ),
    "Tag group not found.",
)

TAG_GROUP_NOT_EMPTY_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="Tag group contains tags.",
        code="TAG_GROUP_NOT_EMPTY",
    ),
    "Tag group contains tags.",
)


def _raise_tag_group_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Tag group not found.",
        code="TAG_GROUP_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_tag_group_not_empty(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=409,
        title="Conflict",
        detail="Tag group contains tags.",
        code="TAG_GROUP_NOT_EMPTY",
        instance=str(request.url),
    )


def _game_group_exists_condition(game_id: int):
    return (
        select(1)
        .select_from(
            catalog.Tag.__table__.join(
                catalog.allowed_mods_tags,
                catalog.allowed_mods_tags.c.tag_id == catalog.Tag.id,
            )
        )
        .where(
            catalog.Tag.group_id == catalog.TagGroup.id,
            catalog.allowed_mods_tags.c.game_id == game_id,
        )
        .exists()
    )


def _tag_group_is_orphan_condition():
    return ~select(1).select_from(catalog.Tag).where(catalog.Tag.group_id == catalog.TagGroup.id).exists()


@router.get(
    "/tag-groups",
    tags=["Tag Group"],
    summary="List tag groups",
    description="Returns a paginated list of tag groups with optional name and game filters.",
    status_code=200,
    response_model=TagGroupListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag group list.",
)
async def list_tag_groups(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of tag groups to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.tag.name_max,
        description="Case-insensitive substring filter for the tag group name.",
    ),
    game_id: int | None = Query(default=None, ge=1, description="Filter by game ID."),
):
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.TagGroup)
        list_stmt = select(catalog.TagGroup)

        if name:
            condition = catalog.TagGroup.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if game_id:
            condition = _game_group_exists_condition(game_id)
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (
            await session.execute(
                list_stmt.order_by(catalog.TagGroup.name, catalog.TagGroup.id)
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()

    items = [serialize_tag_group(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/tag-groups/orphaned",
    tags=["Tag Group"],
    summary="List orphaned tag groups",
    description="Returns tag groups that do not contain any tags. Admin privileges are required.",
    status_code=200,
    response_model=TagGroupListResponse,
    response_model_exclude_none=True,
    response_description="Paginated orphan tag group list.",
    responses={403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC},
)
async def list_orphaned_tag_groups(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of tag groups to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.tag.name_max,
        description="Case-insensitive substring filter for the tag group name.",
    ),
    ids: list[int] = Query(default_factory=list, description="Limit results to these tag group IDs."),
):
    await tools.access_admin(request=request)

    orphan_condition = _tag_group_is_orphan_condition()
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.TagGroup).where(orphan_condition)
        list_stmt = select(catalog.TagGroup).where(orphan_condition)

        if name:
            condition = catalog.TagGroup.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if ids:
            count_stmt = count_stmt.where(catalog.TagGroup.id.in_(ids))
            list_stmt = list_stmt.where(catalog.TagGroup.id.in_(ids))

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (
            await session.execute(
                list_stmt.order_by(catalog.TagGroup.name, catalog.TagGroup.id).offset(offset).limit(page_size)
            )
        ).scalars().all()

    items = [serialize_tag_group(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/tag-groups/{group_id}",
    tags=["Tag Group"],
    summary="Get tag group",
    description="Returns a single tag group by ID.",
    status_code=200,
    response_model=TagGroupRead,
    response_model_exclude_none=True,
    response_description="Tag group resource.",
    responses={404: TAG_GROUP_NOT_FOUND_RESPONSE},
)
async def get_tag_group(request: Request, group_id: int) -> TagGroupRead:
    async with catalog.AsyncSessionLocal() as session:
        group = await session.get(catalog.TagGroup, group_id)

    if group is None:
        _raise_tag_group_not_found(request)

    return serialize_tag_group(group)


@router.get(
    "/tag-groups/{group_id}/tags",
    tags=["Tag Group", "Tag"],
    summary="List tag group tags",
    description="Returns a paginated list of tags in a tag group.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag list.",
    responses={404: TAG_GROUP_NOT_FOUND_RESPONSE},
)
async def list_tag_group_tags(
    request: Request,
    group_id: int,
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
    ids: list[int] = Query(default_factory=list, description="Limit results to these tag IDs."),
    game_id: int | None = Query(default=None, ge=1, description="Filter by game ID."),
):
    async with catalog.AsyncSessionLocal() as session:
        group = await session.get(catalog.TagGroup, group_id)
        if group is None:
            _raise_tag_group_not_found(request)

        count_stmt = select(func.count()).select_from(catalog.Tag).where(catalog.Tag.group_id == group_id)
        list_stmt = (
            select(catalog.Tag)
            .where(catalog.Tag.group_id == group_id)
            .options(joinedload(catalog.Tag.group))
        )

        if name:
            condition = catalog.Tag.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if ids:
            count_stmt = count_stmt.where(catalog.Tag.id.in_(ids))
            list_stmt = list_stmt.where(catalog.Tag.id.in_(ids))

        if game_id:
            condition = (
                select(1)
                .select_from(catalog.allowed_mods_tags)
                .where(
                    catalog.allowed_mods_tags.c.tag_id == catalog.Tag.id,
                    catalog.allowed_mods_tags.c.game_id == game_id,
                )
                .exists()
            )
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (
            await session.execute(
                list_stmt.order_by(catalog.Tag.name, catalog.Tag.id)
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()

    items = [serialize_tag(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.post(
    "/tag-groups",
    tags=["Tag Group"],
    summary="Create tag group",
    description="Creates a new tag group. Admin privileges are required.",
    status_code=201,
    response_model=TagGroupRead,
    response_model_exclude_none=True,
    response_description="Created tag group resource.",
    responses={403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC},
)
async def create_tag_group(
    response: Response,
    request: Request,
    payload: TagGroupCreate,
) -> TagGroupRead:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        group = catalog.TagGroup(name=payload.name)
        session.add(group)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/tag-groups/{group.id}"
        return serialize_tag_group(group)


@router.patch(
    "/tag-groups/{group_id}",
    tags=["Tag Group"],
    summary="Update tag group",
    description="Updates the tag group name. Admin privileges are required.",
    status_code=200,
    response_model=TagGroupRead,
    response_model_exclude_none=True,
    response_description="Updated tag group resource.",
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: TAG_GROUP_NOT_FOUND_RESPONSE,
    },
)
async def patch_tag_group(
    request: Request,
    group_id: int,
    payload: TagGroupPatch,
) -> TagGroupRead:
    await tools.access_admin(request=request)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name",),
        detail="Tag group name cannot be null.",
    )

    async with catalog.AsyncSessionLocal() as session:
        group = await session.get(catalog.TagGroup, group_id)
        if group is None:
            _raise_tag_group_not_found(request)

        for key, value in data.items():
            setattr(group, key, value)
        await session.commit()
        return serialize_tag_group(group)


@router.delete(
    "/tag-groups/{group_id}",
    tags=["Tag Group"],
    summary="Delete tag group",
    description="Deletes an empty tag group. Admin privileges are required.",
    status_code=204,
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: TAG_GROUP_NOT_FOUND_RESPONSE,
        409: TAG_GROUP_NOT_EMPTY_RESPONSE,
    },
)
async def delete_tag_group(request: Request, group_id: int) -> Response:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        group = await session.get(catalog.TagGroup, group_id)
        if group is None:
            _raise_tag_group_not_found(request)

        tag_id = await session.scalar(select(catalog.Tag.id).where(catalog.Tag.group_id == group_id).limit(1))
        if tag_id is not None:
            _raise_tag_group_not_empty(request)

        await session.execute(delete(catalog.TagGroup).where(catalog.TagGroup.id == group_id))
        await session.commit()

    return Response(status_code=204)
