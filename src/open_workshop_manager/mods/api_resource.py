"""Resource management routes."""

import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Form, Path, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import delete, func, select

from open_workshop_manager import settings as config
from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


def _transfer_init_response(
    request: Request,
    job_id: str,
    token: str,
    extra: dict[str, object] | None = None,
):
    transfer_url = f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    ws_url = f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}"
    payload: dict[str, object] = {
        "job_id": job_id,
        "transfer_url": transfer_url,
        "ws_url": ws_url,
    }
    if extra:
        payload.update(extra)

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept", "") or "")
    )
    if wants_json:
        return JSONResponse(status_code=200, content=payload)

    out = RedirectResponse(url=transfer_url, status_code=307)
    out.headers["X-Upload-Job"] = job_id
    out.headers["X-Progress-WS"] = f"{config.STORAGE_URL}/transfer/ws/{job_id}"
    return out


@router.get(
    MAIN_URL + "/resources",
    tags=["Resource", "Game", "Mod", "Association"],
    status_code=200,
    summary="Список ресурсов",
    responses={
        200: {"description": "Обычный ответ."},
        400: {"description": "Не переданы `owner_ids` или `owner_id`."},
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        405: {"description": "Неизвестный `owner_type`."},
        413: {
            "description": "Неккоректный диапазон параметров *(размеров)*.",
            "content": {
                "application/json": {
                    "example": {"message": "incorrect page size", "error_id": 2}
                }
            },
        },
    },
)
async def list_resources_rest(
    response: Response,
    request: Request,
    owner_type: str = Query(
        ...,
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    owner_ids=Query(
        None,
        description="Список ID-владельцев в формате JSON списка.",
        examples=["[1, 2, 3]"],
    ),
    owner_id: int | None = Query(
        None, description="ID владельца (альтернатива owner_ids)."
    ),
    resources_list_id=Query([], description="Список ID-ресурсов.", examples=["[1, 2, 3]"]),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        examples=['["logo", "screenshot"]'],
    ),
    only_urls: bool = Query(
        False, description="Возвращать только ссылки или полную информацию."
    ),
):
    owner_ids_value = owner_ids
    if owner_ids_value is None and owner_id is not None:
        owner_ids_value = f"[{owner_id}]"

    if owner_ids_value is None:
        raise standarts.BadRequestError(
            detail="owner_ids is required",
            instance=str(request.url),
        )

    return await list_resources(
        response=response,
        request=request,
        owner_type=owner_type,
        owner_ids=owner_ids_value,
        resources_list_id=resources_list_id,
        page_size=page_size,
        page=page,
        types_resources=types_resources,
        only_urls=only_urls,
    )


@router.post(
    MAIN_URL + "/resources",
    tags=["Resource"],
    summary="Добавление ресурса",
    status_code=202,
    responses={
        202: {
            "description": "Возвращает ID созданного ресурса.",
            "content": {"application/json": {"example": 1}},
        },
        400: {"description": "Передан некорректный `resource_url`."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        405: {"description": "Неизвестный тип ресурса-владельца."},
        500: {"description": "Произошла ошибка на стороне Storage сервера."},
    },
)
async def add_resource_rest(
    response: Response,
    request: Request,
    owner_type: str = Form(
        ...,
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    resource_type: str = Form(
        ...,
        description="Название типа ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
    resource_url: str = Form(
        "",
        description="URL ресурса.",
        min_length=LIMITS.resource.url_min_create,
        max_length=LIMITS.resource.url_max,
    ),
    resource_owner_id: int = Form(..., description="ID ресурса-владельца."),
):
    return await add_resource(
        response=response,
        request=request,
        owner_type=owner_type,
        resource_type=resource_type,
        resource_url=resource_url,
        resource_owner_id=resource_owner_id,
    )


@router.patch(
    MAIN_URL + "/resources/{resource_id}",
    tags=["Resource"],
    summary="Редактирование ресурса",
    status_code=202,
    responses={
        202: {"description": "Успешное редактирование"},
        400: {"description": "Передан неккоректный `resource_url`."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Ресурс не найден."},
        418: {"description": "Пустой запрос."},
        500: {"description": "Произошла ошибка на стороне Storage сервера."},
    },
)
async def edit_resource_rest(
    response: Response,
    request: Request,
    resource_id: int = Path(description="ID ресурса."),
    resource_type: str = Form(
        None,
        description="Тип ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
    resource_url: str = Form(
        None,
        description="URL ресурса.",
        min_length=LIMITS.resource.url_min,
        max_length=LIMITS.resource.url_max,
    ),
):
    return await edit_resource(
        response=response,
        request=request,
        resource_id=resource_id,
        resource_type=resource_type,
        resource_url=resource_url,
    )


@router.post(
    MAIN_URL + "/resources/upload-init",
    tags=["Resource"],
    summary="Инициализация загрузки файла ресурса напрямую на Storage",
    status_code=307,
    responses={
        200: {"description": "JSON с transfer_url/ws_url"},
        307: {"description": "Redirect на Storage transfer/upload"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        405: {"description": "Неизвестный тип ресурса-владельца."},
        500: {"description": "Не настроен JWT секрет."},
    },
)
async def add_resource_upload_init(
    response: Response,
    request: Request,
    owner_type: str = Form(
        ...,
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    resource_type: str = Form(
        ...,
        description="Название типа ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
    resource_owner_id: int = Form(..., description="ID ресурса-владельца."),
):
    if owner_type not in ["mods", "games"]:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))
    elif owner_type == "mods":
        access_result = await tools.access_mods(
            response=response, request=request, mods_ids=[resource_owner_id], edit=True
        )
    else:
        access_result = await tools.access_admin(response=response, request=request)
    if access_result is not True:
        return access_result

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        new_resource = catalog.Resource(
            type=resource_type,
            url="",
            size=None,
            date_event=datetime.now(),
            owner_type=owner_type,
            owner_id=resource_owner_id,
        )
        session.add(new_resource)
        await session.flush()
        resource_id = int(new_resource.id)
        await session.commit()

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900

    target_path = f"{owner_type}/{resource_owner_id}/{resource_id}.webp"
    payload = {
        "job_id": job_id,
        "transfer_kind": "img",
        "storage_type": "resource",
        "file_kind": "img",
        "callback_action": "resource_add",
        "callback_context": {"resource_id": resource_id},
        "target_path": target_path,
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        async with catalog.AsyncSessionLocal() as session:
            await session.execute(
                delete(catalog.Resource).where(
                    catalog.Resource.id == resource_id
                )
            )
            await session.commit()
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    return _transfer_init_response(
        request=request,
        job_id=job_id,
        token=token,
        extra={
            "resource_id": resource_id,
            "owner_type": owner_type,
            "owner_id": resource_owner_id,
        },
    )


@router.post(
    MAIN_URL + "/resources/{resource_id}/upload-init",
    tags=["Resource"],
    summary="Инициализация обновления файла ресурса напрямую на Storage",
    status_code=307,
    responses={
        200: {"description": "JSON с transfer_url/ws_url"},
        307: {"description": "Redirect на Storage transfer/upload"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Ресурс не найден."},
        500: {"description": "Не настроен JWT секрет."},
    },
)
async def edit_resource_upload_init(
    response: Response,
    request: Request,
    resource_id: int = Path(description="ID ресурса."),
    resource_type: str | None = Form(
        None,
        description="Тип ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
):
    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id)
        if not resource:
            raise standarts.NotFoundError(
                detail="not found",
                instance=str(request.url),
            )

        if resource.owner_type == "mods":
            access_result = await tools.access_mods(
                response=response,
                request=request,
                mods_ids=[resource.owner_id],
                edit=True,
            )
        else:
            access_result = await tools.access_admin(response=response, request=request)
        if access_result is not True:
            return access_result

        if resource_type:
            resource.type = resource_type
            await session.commit()

        owner_type = str(resource.owner_type)
        owner_id = int(resource.owner_id)

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900

    target_path = f"{owner_type}/{owner_id}/{resource_id}.webp"
    payload = {
        "job_id": job_id,
        "transfer_kind": "img",
        "storage_type": "resource",
        "file_kind": "img",
        "callback_action": "resource_edit",
        "callback_context": {"resource_id": resource_id},
        "target_path": target_path,
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    return _transfer_init_response(
        request=request,
        job_id=job_id,
        token=token,
        extra={"resource_id": resource_id, "owner_type": owner_type, "owner_id": owner_id},
    )


@router.delete(
    MAIN_URL + "/resources/{resource_id}",
    tags=["Resource"],
    summary="Удаление ресурса",
    status_code=200,
    responses={
        200: {"description": "Успешное удаление"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Ресурс не найден."},
        405: {
            "description": "Неккоректный `owner_type`. Доступные значения: `mods`, `games`."
        },
        500: {"description": "Произошла ошибка на стороне Storage сервера."},
    },
)
async def delete_resource_rest(
    response: Response,
    request: Request,
    resource_id: int = Path(description="ID ресурса для удаления."),
):
    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id)

    if not resource:
        raise standarts.NotFoundError(
            detail="not found",
            instance=str(request.url),
        )

    if resource.owner_type not in ["mods", "games"]:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))

    if resource.owner_type == "mods":
        access_result = await tools.access_mods(
            response=response,
            request=request,
            mods_ids=[resource.owner_id],
            edit=True,
        )
    else:
        access_result = await tools.access_admin(response=response, request=request)

    if access_result is not True:
        return access_result

    if await tools.delete_resources(
        owner_type=resource.owner_type, resources_ids=[resource_id]
    ):
        return PlainTextResponse(status_code=200, content="Complite!")
    raise standarts.InternalServerError(
        detail="Unknown error",
        instance=str(request.url),
    )


async def list_resources(
    response: Response,
    request: Request,
    owner_type: str = Path(
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    owner_ids=Path(description="Список ID-владельцев.", examples=["[1, 2, 3]"]),
    resources_list_id=Query([], description="Список ID-ресурсов.", examples=["[1, 2, 3]"]),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        examples=['["logo", "screenshot"]'],
    ),
    only_urls: bool = Query(
        False, description="Возвращать только ссылки или полную информацию."
    ),
):
    """
    Возвращает список ресурсов. Фильтрационные списки не должны быть суммарно > 120 элементов.

    Если в переданном списке ресурсов есть ID привязанное к непубличному моду, то будет отказано в доступе!
    """
    resources_list_id = tools.str_to_list(resources_list_id)
    types_resources = tools.str_to_list(types_resources)
    owner_ids = tools.str_to_list(owner_ids)

    if owner_type not in ["mods", "games"]:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))

    if (
        len(types_resources) + len(resources_list_id) + len(owner_ids)
        > LIMITS.resource.filters_max
    ):
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 120 elements in sum",
            instance=str(request.url),
            context={"error_id": 1},
        )
    elif page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 2},
        )
    elif page < 0:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page",
            instance=str(request.url),
            context={"error_id": 3},
        )

    # Создание сессии
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Resource).where(
            catalog.Resource.owner_type == owner_type,
            catalog.Resource.owner_id.in_(owner_ids),
        )
        list_stmt = select(catalog.Resource).where(
            catalog.Resource.owner_type == owner_type,
            catalog.Resource.owner_id.in_(owner_ids),
        )
        if len(resources_list_id) > 0:
            count_stmt = count_stmt.where(catalog.Resource.id.in_(resources_list_id))
            list_stmt = list_stmt.where(catalog.Resource.id.in_(resources_list_id))
        if len(types_resources) > 0:
            count_stmt = count_stmt.where(catalog.Resource.type.in_(types_resources))
            list_stmt = list_stmt.where(catalog.Resource.type.in_(types_resources))

        resources_count = int((await session.execute(count_stmt)).scalar_one())
        offset = page_size * page
        resources = (
            await session.execute(list_stmt.offset(offset).limit(page_size))
        ).scalars().all()

        if resources_count > 0:
            mods_ids_check = [i.owner_id for i in resources]

            result_mods = await session.execute(
                select(catalog.Mod.id).where(catalog.Mod.id.in_(mods_ids_check))
            )
            ids_mods = list(result_mods.scalars().all())

            if len(ids_mods) > 0:
                if not await tools.access_mods(
                    response=response, request=request, mods_ids=ids_mods, check_mode=True
                ):
                    raise standarts.ForbiddenError(
                        detail="Access denied.",
                        instance=str(request.url),
                    )

        real_resources = await tools.resources_serialize(
            resources=resources, only_urls=only_urls
        )

    return {
        "database_size": resources_count,
        "offset": offset,
        "results": real_resources,
    }


async def add_resource(
    response: Response,
    request: Request,
    owner_type: str = Path(
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    resource_type: str = Form(
        ...,
        description="Название типа ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
    resource_url: str = Form(
        "",
        description="URL ресурса.",
        min_length=LIMITS.resource.url_min_create,
        max_length=LIMITS.resource.url_max,
    ),
    resource_owner_id: int = Form(..., description="ID ресурса-владельца."),
):
    if owner_type not in ["mods", "games"]:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))
    elif owner_type == "mods":
        access_result = await tools.access_mods(
            response=response, request=request, mods_ids=[resource_owner_id], edit=True
        )
    else:
        access_result = await tools.access_admin(response=response, request=request)

    if access_result is True:
        if len(resource_url) > LIMITS.resource.url_max or not resource_url.startswith("http"):
            raise standarts.BadRequestError(
                detail="Incorrect URL",
                instance=str(request.url),
            )

        async with catalog.AsyncSessionLocal() as session:
            new_resource = catalog.Resource(
                type=resource_type,
                url=resource_url,
                size=None,
                date_event=datetime.now(),
                owner_type=owner_type,
                owner_id=resource_owner_id,
            )
            session.add(new_resource)
            await session.flush()
            id = int(new_resource.id)  # Получаем ID последней вставленной строки

            await session.commit()

        return JSONResponse(status_code=202, content=id)  # Возвращаем значение `id`
    else:
        return access_result


async def edit_resource(
    response: Response,
    request: Request,
    resource_id: int = Form(..., description="ID ресурса."),
    resource_type: str = Form(
        None,
        description="Тип ресурса.",
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    ),
    resource_url: str = Form(
        None,
        description="URL ресурса.",
        min_length=LIMITS.resource.url_min,
        max_length=LIMITS.resource.url_max,
    ),
):
    async with catalog.AsyncSessionLocal() as session:
        got_resource = await session.get(catalog.Resource, resource_id)
        if not got_resource:
            raise standarts.NotFoundError(
                detail="The element does not exist.",
                instance=str(request.url),
            )

        if got_resource.owner_type == "mods":
            access_result = await tools.access_mods(
                response=response,
                request=request,
                mods_ids=[got_resource.owner_id],
                edit=True,
            )
        else:
            access_result = await tools.access_admin(response=response, request=request)

        if access_result is True:
            data_edit: dict[str, object] = {}
            if resource_type:
                data_edit["type"] = resource_type

            if resource_url:
                if (
                    len(resource_url) < LIMITS.resource.url_min
                    or len(resource_url) > LIMITS.resource.url_max
                    or not resource_url.startswith("http")
                ):
                    raise standarts.BadRequestError(
                        detail="Incorrect URL",
                        instance=str(request.url),
                    )
                if got_resource.url.startswith("local/") and not await tools.storage_file_delete(
                    type="resource", path=got_resource.url.replace("local/", "")
                ):
                    raise standarts.InternalServerError(
                        detail="delete old file error",
                        instance=str(request.url),
                    )
                data_edit["url"] = resource_url
                data_edit["size"] = None

            if len(data_edit) <= 0:
                raise standarts.RequestRejectedError(
                    detail="The request is empty",
                    instance=str(request.url),
                )

            data_edit["date_event"] = datetime.now()

            for key, value in data_edit.items():
                setattr(got_resource, key, value)
            await session.commit()

            return JSONResponse(status_code=202, content="Complite")
        else:
            return access_result
