from fastapi import APIRouter, Request, Response, Form, Query, Path
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
import tools
import uuid
from urllib.parse import quote
from sql_logic import sql_catalog as catalog
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from ow_config import MAIN_URL
import ow_config as config
from limits import LIMITS
from datetime import datetime
import standarts

router = APIRouter()


def _transfer_init_response(
    request: Request,
    job_id: str,
    token: str,
    extra: dict[str, object] | None = None,
):
    transfer_url = f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    ws_url = f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}"
    payload = {
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
        403: standarts.responses["non-admin"][403],
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
        example="[1, 2, 3]",
    ),
    owner_id: int | None = Query(
        None, description="ID владельца (альтернатива owner_ids)."
    ),
    resources_list_id=Query([], description="Список ID-ресурсов.", example="[1, 2, 3]"),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        example='["logo", "screenshot"]',
    ),
    only_urls: bool = Query(
        False, description="Возвращать только ссылки или полную информацию."
    ),
):
    owner_ids_value = owner_ids
    if owner_ids_value is None and owner_id is not None:
        owner_ids_value = f"[{owner_id}]"

    if owner_ids_value is None:
        return PlainTextResponse(status_code=400, content="owner_ids is required")

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
        return PlainTextResponse(status_code=405, content="unknown owner_type")
    elif owner_type == "mods":
        access_result = await tools.access_mods(
            response=response, request=request, mods_ids=[resource_owner_id], edit=True
        )
    else:
        access_result = await tools.access_admin(response=response, request=request)
    if access_result is not True:
        return access_result

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        return PlainTextResponse(status_code=500, content="JWT secret missing")

    session = sessionmaker(bind=catalog.engine)()
    insert_statement = insert(catalog.Resource).values(
        type=resource_type,
        url="",
        date_event=datetime.now(),
        owner_type=owner_type,
        owner_id=resource_owner_id,
    )
    result = session.execute(insert_statement)
    resource_id = int(result.lastrowid)
    session.commit()
    session.close()

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
        session = sessionmaker(bind=catalog.engine)()
        session.query(catalog.Resource).filter_by(id=resource_id).delete()
        session.commit()
        session.close()
        return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    session = sessionmaker(bind=catalog.engine)()
    resource_query = session.query(catalog.Resource).filter_by(id=resource_id)
    resource = resource_query.first()
    if not resource:
        session.close()
        return PlainTextResponse(status_code=404, content="not found")

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
        session.close()
        return access_result

    if resource_type:
        resource_query.update({"type": resource_type})
        session.commit()

    owner_type = str(resource.owner_type)
    owner_id = int(resource.owner_id)
    session.close()

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    session = sessionmaker(bind=catalog.engine)()
    resource = session.query(catalog.Resource).filter_by(id=resource_id).first()
    session.close()

    if not resource:
        return PlainTextResponse(status_code=404, content="not found")

    if resource.owner_type not in ["mods", "games"]:
        return PlainTextResponse(status_code=405, content="unknown owner_type")

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
    return PlainTextResponse(status_code=500, content="Unknown error")


async def list_resources(
    response: Response,
    request: Request,
    owner_type: str = Path(
        description="Тип ресурса-владельца.",
        examples=["mods", "games"],
        max_length=LIMITS.resource.owner_type_max,
    ),
    owner_ids=Path(description="Список ID-владельцев.", example="[1, 2, 3]"),
    resources_list_id=Query([], description="Список ID-ресурсов.", example="[1, 2, 3]"),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        example='["logo", "screenshot"]',
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
        return PlainTextResponse(status_code=405, content="unknown owner_type")

    if (
        len(types_resources) + len(resources_list_id) + len(owner_ids)
        > LIMITS.resource.filters_max
    ):
        return JSONResponse(
            status_code=413,
            content={
                "message": "the maximum complexity of filters is 120 elements in sum",
                "error_id": 1,
            },
        )
    elif page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        return JSONResponse(
            status_code=413, content={"message": "incorrect page size", "error_id": 2}
        )
    elif page < 0:
        return JSONResponse(
            status_code=413, content={"message": "incorrect page", "error_id": 3}
        )

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Resource)
    query = query.filter_by(owner_type=owner_type)
    query = query.filter(catalog.Resource.owner_id.in_(owner_ids))
    if len(resources_list_id) > 0:
        query = query.filter(catalog.Resource.id.in_(resources_list_id))
    if len(types_resources) > 0:
        query = query.filter(catalog.Resource.type.in_(types_resources))

    resources_count = query.count()
    offset = page_size * page
    resources = query.offset(offset).limit(page_size).all()

    # Проверка правомерности
    if resources_count > 0:
        mods_ids_check = [i.owner_id for i in resources]

        query = session.query(catalog.Mod.id)
        query = query.filter(catalog.Mod.id.in_(mods_ids_check))
        ids_mods = [mod.id for mod in query.all()]

        if len(ids_mods) > 0:
            if not await tools.access_mods(
                response=response, request=request, mods_ids=ids_mods, check_mode=True
            ):
                session.close()
                return PlainTextResponse(status_code=403, content="Access denied.")

    real_resources = await tools.resources_serialize(
        resources=resources, only_urls=only_urls
    )

    # Возврат успешного результата
    session.close()
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
        return PlainTextResponse(status_code=405, content="unknown owner_type")
    elif owner_type == "mods":
        access_result = await tools.access_mods(
            response=response, request=request, mods_ids=[resource_owner_id], edit=True
        )
    else:
        access_result = await tools.access_admin(response=response, request=request)

    if access_result is True:
        if len(resource_url) > LIMITS.resource.url_max or not resource_url.startswith("http"):
            return PlainTextResponse(status_code=400, content="Incorrect URL")

        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Resource).values(
            type=resource_type,
            url=resource_url,
            date_event=datetime.now(),
            owner_type=owner_type,
            owner_id=resource_owner_id,
        )

        result = session.execute(insert_statement)
        id = result.lastrowid  # Получаем ID последней вставленной строки

        session.commit()
        session.close()

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
    session = sessionmaker(bind=catalog.engine)()

    resource = session.query(catalog.Resource).filter_by(id=resource_id)
    got_resource = resource.first()
    if not got_resource:
        return JSONResponse(status_code=404, content="The element does not exist.")

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
        # Подготавливаем данные
        data_edit: dict[str, object] = {}
        if resource_type:
            data_edit["type"] = resource_type

        if resource_url:
            if (
                len(resource_url) < LIMITS.resource.url_min
                or len(resource_url) > LIMITS.resource.url_max
                or not resource_url.startswith("http")
            ):
                return PlainTextResponse(status_code=400, content="Incorrect URL")
            if got_resource.url.startswith(
                "local/"
            ) and not await tools.storage_file_delete(
                type="resource", path=got_resource.url.replace("local/", "")
            ):
                return JSONResponse(status_code=500, content="delete old file error")
            data_edit["url"] = resource_url

        if len(data_edit) <= 0:
            return JSONResponse(status_code=418, content="The request is empty")

        data_edit["date_event"] = datetime.now()

        # Меняем данные в БД
        resource.update(data_edit)
        session.commit()

        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        session.close()
        return access_result

