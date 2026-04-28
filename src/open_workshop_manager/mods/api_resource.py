"""Resource REST routes."""

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
from open_workshop_manager.api_models import ResourceCreate, ResourceListResponse, ResourcePatch, ResourceRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

ALLOWED_OWNER_TYPES = {"mods", "games"}

RESOURCE_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The resource request contains invalid owner data or URL.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

RESOURCE_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Resource not found.",
        code="RESOURCE_NOT_FOUND",
    ),
    "Resource not found.",
)


def _raise_resource_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Resource not found.",
        code="RESOURCE_NOT_FOUND",
        instance=str(request.url),
    )


def _serialize_resource(resource: catalog.Resource) -> ResourceRead:
    real_url = getattr(resource, "real_url", getattr(resource, "url", ""))
    size_value = getattr(resource, "size", None)
    return ResourceRead(
        id=int(resource.id),
        owner_type=str(getattr(resource, "owner_type", "")),
        owner_id=int(getattr(resource, "owner_id", 0)),
        type=str(getattr(resource, "type", "")),
        url=real_url,
        size=int(size_value) if size_value is not None else None,
        created_at=getattr(resource, "date_event", None),
        updated_at=getattr(resource, "date_event", None),
    )


def _ensure_owner_type(request: Request, owner_type: str) -> None:
    if owner_type not in ALLOWED_OWNER_TYPES:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))


async def _require_mod_access(request: Request, mod_id: int, *, edit: bool) -> None:
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=edit)


async def _require_owner_access(request: Request, owner_type: str, owner_id: int, *, edit: bool) -> None:
    if owner_type == "mods":
        await _require_mod_access(request, owner_id, edit=edit)
        return
    await tools.access_admin(request=request)


@router.get(
    "/resources",
    tags=["Resource"],
    summary="List resources",
    description=(
        "Returns a paginated list of resources for one owner type.\n\n"
        "Use `only_urls=true` when the UI only needs the raw URLs."
    ),
    status_code=200,
    response_model=ResourceListResponse,
    response_model_exclude_none=True,
    response_description="Paginated resource list.",
    responses={400: RESOURCE_BAD_REQUEST_RESPONSE},
)
async def list_resources(
    request: Request,
    owner_type: str = Query(
        ...,
        max_length=LIMITS.resource.owner_type_max,
        description="Owner type to filter by (`mods` or `games`).",
    ),
    owner_id: int | None = Query(default=None, ge=1, description="Convenience filter for one owner ID."),
    owner_ids: list[int] = Query(default_factory=list, description="Owner IDs to include."),
    resource_ids: list[int] = Query(default_factory=list, description="Resource IDs to include."),
    types: list[str] = Query(default_factory=list, description="Resource types to include."),
    only_urls: bool = Query(default=False, description="Return only resource URLs."),
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of resources to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
):
    _ensure_owner_type(request, owner_type)

    if owner_id is not None and not owner_ids:
        owner_ids = [owner_id]

    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Resource).where(
            catalog.Resource.owner_type == owner_type,
        )
        list_stmt = select(catalog.Resource).where(
            catalog.Resource.owner_type == owner_type,
        )

        if owner_ids:
            count_stmt = count_stmt.where(catalog.Resource.owner_id.in_(owner_ids))
            list_stmt = list_stmt.where(catalog.Resource.owner_id.in_(owner_ids))

        if resource_ids:
            count_stmt = count_stmt.where(catalog.Resource.id.in_(resource_ids))
            list_stmt = list_stmt.where(catalog.Resource.id.in_(resource_ids))

        if types:
            count_stmt = count_stmt.where(catalog.Resource.type.in_(types))
            list_stmt = list_stmt.where(catalog.Resource.type.in_(types))

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

    if owner_type == "mods" and owner_ids and rows:
        mod_ids = [int(row.owner_id) for row in rows]
        allowed_ids = await tools.access_mods(request=request, mods_ids=mod_ids, check_mode=True)
        if len(allowed_ids) != len(mod_ids):
            raise standarts.ForbiddenError(
                detail="Access denied.",
                instance=str(request.url),
                code="FORBIDDEN",
            )

    items: list[dict[str, object] | str] = []
    for row in rows:
        serialized = _serialize_resource(row)
        if only_urls:
            items.append(serialized.url)
        else:
            items.append(serialized.model_dump(mode="json", exclude_none=True))

    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/resources/{resource_id}",
    tags=["Resource"],
    summary="Get resource",
    description="Returns a single resource by ID.",
    status_code=200,
    response_model=ResourceRead,
    response_model_exclude_none=True,
    response_description="Resource object.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: RESOURCE_NOT_FOUND_RESPONSE,
    },
)
async def get_resource(request: Request, resource_id: int) -> ResourceRead:
    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id)

    if resource is None:
        _raise_resource_not_found(request)

    if resource.owner_type == "mods":
        await tools.access_mods(request=request, mods_ids=[resource.owner_id])

    return _serialize_resource(resource)


@router.post(
    "/resources",
    tags=["Resource"],
    summary="Create resource",
    description="Creates a new resource for a game or a mod owner.",
    status_code=201,
    response_model=ResourceRead,
    response_model_exclude_none=True,
    response_description="Created resource object.",
    responses={
        400: RESOURCE_BAD_REQUEST_RESPONSE,
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def create_resource(
    response: Response,
    request: Request,
    payload: ResourceCreate,
) -> ResourceRead:
    _ensure_owner_type(request, payload.owner_type)
    await _require_owner_access(request, payload.owner_type, payload.owner_id, edit=True)

    if not payload.url.startswith("http"):
        raise standarts.PayloadTooLargeError(
            detail="Incorrect URL.",
            instance=str(request.url),
            code="RESOURCE_URL_INVALID",
            context={"field": "url"},
        )

    async with catalog.AsyncSessionLocal() as session:
        resource = catalog.Resource(
            type=payload.type,
            url=payload.url,
            size=None,
            date_event=datetime.now(),
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
        )
        session.add(resource)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/resources/{resource.id}"
        return _serialize_resource(resource)


@router.patch(
    "/resources/{resource_id}",
    tags=["Resource"],
    summary="Update resource",
    description="Updates the resource URL or type.",
    status_code=200,
    response_model=ResourceRead,
    response_model_exclude_none=True,
    response_description="Updated resource object.",
    responses={
        400: RESOURCE_BAD_REQUEST_RESPONSE,
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: RESOURCE_NOT_FOUND_RESPONSE,
    },
)
async def patch_resource(
    request: Request,
    resource_id: int,
    payload: ResourcePatch,
) -> ResourceRead:
    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("type", "url"),
        detail="Resource patch fields cannot be null.",
    )

    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id)
        if resource is None:
            _raise_resource_not_found(request)

        await _require_owner_access(request, str(resource.owner_type), int(resource.owner_id), edit=True)

        if "url" in data:
            url = str(data["url"])
            if not url.startswith("http"):
                raise standarts.PayloadTooLargeError(
                    detail="Incorrect URL.",
                    instance=str(request.url),
                    code="RESOURCE_URL_INVALID",
                    context={"field": "url"},
                )
            if str(resource.url).startswith("local/") and not await tools.storage_file_delete(
                type="resource", path=str(resource.url).replace("local/", "")
            ):
                raise standarts.InternalServerError(
                    detail="Failed to delete old resource file.",
                    instance=str(request.url),
                    code="STORAGE_DELETE_FAILED",
                )
            resource.url = url
            resource.size = None

        if "type" in data:
            resource.type = str(data["type"])

        resource.date_event = datetime.now()
        await session.commit()
        return _serialize_resource(resource)


@router.delete(
    "/resources/{resource_id}",
    tags=["Resource"],
    summary="Delete resource",
    description="Deletes a resource and its local storage file, if any.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: RESOURCE_NOT_FOUND_RESPONSE,
    },
)
async def delete_resource(request: Request, resource_id: int) -> Response:
    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id)
        if resource is None:
            _raise_resource_not_found(request)

        await _require_owner_access(request, str(resource.owner_type), int(resource.owner_id), edit=True)

        if str(resource.url).startswith("local/"):
            if not await tools.storage_file_delete(
                type="resource", path=str(resource.url).replace("local/", "")
            ):
                raise standarts.InternalServerError(
                    detail="Failed to delete resource file.",
                    instance=str(request.url),
                    code="STORAGE_DELETE_FAILED",
                )

        await session.execute(delete(catalog.Resource).where(catalog.Resource.id == resource_id))
        await session.commit()

    return Response(status_code=204)
