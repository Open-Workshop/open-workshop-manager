"""Tag REST routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import ensure_non_empty_patch, make_list_response
from open_workshop_manager.api_models import TagCreate, TagListResponse, TagPatch, TagRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


def _serialize_tag(tag: catalog.Tag) -> TagRead:
    return TagRead(id=int(tag.id), name=str(tag.name))


def _raise_tag_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Tag not found.",
        code="TAG_NOT_FOUND",
        instance=str(request.url),
    )


@router.get(
    "/tags",
    tags=["Tag"],
    status_code=200,
    response_model=TagListResponse,
    response_model_exclude_none=True,
)
async def list_tags(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
    ),
    page: int = Query(0, ge=0),
    name: str | None = Query(default=None, max_length=LIMITS.tag.name_max),
    ids: list[int] = Query(default_factory=list),
    game_id: int | None = Query(default=None, ge=1),
):
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Tag)
        list_stmt = select(catalog.Tag)

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
    "/tags/{tag_id}",
    tags=["Tag"],
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
)
async def get_tag(request: Request, tag_id: int) -> TagRead:
    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(catalog.Tag, tag_id)

    if tag is None:
        _raise_tag_not_found(request)

    return _serialize_tag(tag)


@router.post(
    "/tags",
    tags=["Tag"],
    status_code=201,
    response_model=TagRead,
    response_model_exclude_none=True,
)
async def create_tag(response: Response, request: Request, payload: TagCreate) -> TagRead:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        tag = catalog.Tag(name=payload.name)
        session.add(tag)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/tags/{tag.id}"
        return _serialize_tag(tag)


@router.patch(
    "/tags/{tag_id}",
    tags=["Tag"],
    status_code=200,
    response_model=TagRead,
    response_model_exclude_none=True,
)
async def patch_tag(
    request: Request,
    tag_id: int,
    payload: TagPatch,
) -> TagRead:
    await tools.access_admin(request=request)

    data = payload.model_dump(exclude_none=True)
    ensure_non_empty_patch(data)

    async with catalog.AsyncSessionLocal() as session:
        tag = await session.get(catalog.Tag, tag_id)
        if tag is None:
            _raise_tag_not_found(request)

        for key, value in data.items():
            setattr(tag, key, value)
        await session.commit()
        return _serialize_tag(tag)


@router.delete(
    "/tags/{tag_id}",
    tags=["Tag"],
    status_code=204,
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
        await session.execute(delete(catalog.Tag).where(catalog.Tag.id == tag_id))
        await session.commit()

    return Response(status_code=204)
