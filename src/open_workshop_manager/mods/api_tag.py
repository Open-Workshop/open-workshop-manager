"""Tag REST routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import joinedload

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import TagCreate, TagListResponse, TagPatch, TagRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.mods.tag_serialization import serialize_tag
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

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


def _tag_is_orphan_condition():
    return and_(
        ~select(1).select_from(catalog.mods_tags).where(catalog.mods_tags.c.tag_id == catalog.Tag.id).exists(),
        ~select(1)
        .select_from(catalog.modpacks_tags)
        .where(catalog.modpacks_tags.c.tag_id == catalog.Tag.id)
        .exists(),
        ~select(1)
        .select_from(catalog.allowed_mods_tags)
        .where(catalog.allowed_mods_tags.c.tag_id == catalog.Tag.id)
        .exists(),
    )


@router.get(
    "/tags",
    tags=["Tag"],
    summary="List tags",
    description="Returns a paginated list of tags with optional name, ID, and game filters.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated tag list.",
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
    ids: list[int] = Query(default_factory=list, description="Limit results to these tag IDs."),
    game_id: int | None = Query(default=None, ge=1, description="Filter by game ID."),
):
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Tag).where(catalog.Tag.group_id.is_(None))
        list_stmt = select(catalog.Tag).where(catalog.Tag.group_id.is_(None))

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
        rows = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

    items = [_serialize_tag(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/tags/orphaned",
    tags=["Tag"],
    summary="List orphaned tags",
    description="Returns tags that are not attached to any game, mod, or modpack. Admin privileges are required.",
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
    response_description="Paginated orphan tag list.",
    responses={403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC},
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
    ids: list[int] = Query(default_factory=list, description="Limit results to these tag IDs."),
):
    await tools.access_admin(request=request)

    orphan_condition = _tag_is_orphan_condition()
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Tag).where(orphan_condition)
        list_stmt = select(catalog.Tag).where(orphan_condition)

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
            await session.execute(
                list_stmt.order_by(catalog.Tag.name, catalog.Tag.id).offset(offset).limit(page_size)
            )
        ).scalars().all()

    items = [_serialize_tag(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/tags/{tag_id}",
    tags=["Tag"],
    summary="Get tag",
    description="Returns a single tag by ID.",
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Tag resource.",
    responses={404: TAG_NOT_FOUND_RESPONSE},
)
async def get_tag(request: Request, tag_id: int) -> TagRead:
    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(
            catalog.Tag,
            tag_id,
            options=(joinedload(catalog.Tag.group),),
        )

    if tag is None:
        _raise_tag_not_found(request)

    return _serialize_tag(tag)


@router.post(
    "/tags",
    tags=["Tag"],
    summary="Create tag",
    description="Creates a new tag. Admin privileges are required.",
    status_code=201,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Created tag resource.",
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: TAG_GROUP_NOT_FOUND_RESPONSE,
    },
)
async def create_tag(response: Response, request: Request, payload: TagCreate) -> TagRead:
    await tools.access_admin(request=request)

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
    description="Updates the tag name. Admin privileges are required.",
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
    response_description="Updated tag resource.",
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: TAG_NOT_FOUND_RESPONSE,
    },
)
async def patch_tag(
    request: Request,
    tag_id: int,
    payload: TagPatch,
) -> TagRead:
    await tools.access_admin(request=request)

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
    description="Deletes a tag and detaches it from all games, mods, and modpacks. Admin privileges are required.",
    status_code=204,
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: TAG_NOT_FOUND_RESPONSE,
    },
)
async def delete_tag(request: Request, tag_id: int) -> Response:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(catalog.Tag, tag_id)
        if tag is None:
            _raise_tag_not_found(request)

        await session.execute(catalog.mods_tags.delete().where(catalog.mods_tags.c.tag_id == tag_id))
        await session.execute(
            catalog.allowed_mods_tags.delete().where(catalog.allowed_mods_tags.c.tag_id == tag_id)
        )
        await session.execute(
            catalog.modpacks_tags.delete().where(catalog.modpacks_tags.c.tag_id == tag_id)
        )
        await session.execute(delete(catalog.Tag).where(catalog.Tag.id == tag_id))
        await session.commit()

    return Response(status_code=204)
