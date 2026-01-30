from fastapi import APIRouter, Request, Response, Form, Query, Path, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse
import tools
import io
from sql_logic import sql_catalog as catalog
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from ow_config import MAIN_URL
from datetime import datetime
import standarts


router = APIRouter()


@router.get(
    MAIN_URL+"/list/resources/{owner_type}/{owner_ids}",
    tags=["Resource", "Game", "Mod", "Association"],
    status_code=200,
    summary="Список ресурсов",
    responses={
        200: {
            "description": "Обычный ответ",
            "content": {
                "application/json": {
                    "example": {
                        "database_size": 123,
                        "offset": 123,
                        "results": [
                            {
                                "id": 1,
                                "type": "logo",
                                "url": "https://example.com/logo.png",
                                "owner_id": 1,
                                "owner_type": "games",
                                "date_event": "2022-01-01 10:22:42"
                            },
                            {
                                "id": 2,
                                "type": "screenshot",
                                "url": "https://example.com/screenshot.jpg",
                                "owner_id": 1,
                                "owner_type": "games",
                                "date_event": "2022-02-01 11:41:28"
                            }
                        ]
                    }
                }
            }
        },
        403: standarts.responses["non-admin"][403],
        405: {"description": "Неизвестный `owner_type`."},
        413: {
            "description": "Неккоректный диапазон параметров *(размеров)*. Либо суммарно списковые фильтры > 120 элементов, либо неккоректный диапазон `page_size`/`page`",
            "content": {
                "application/json": {
                    "example": {
                        "message": "incorrect page size",
                        "error_id": 2
                    }
                }
            }
        },
    }
)
async def list_resources(
    response: Response,
    request: Request,
    owner_type: str = Path(description="Тип ресурса-владельца.", examples=["mods", "games"], max_length=64),
    owner_ids = Path(description="Список ID-владельцев.", example='[1, 2, 3]'),
    resources_list_id = Query([], description="Список ID-ресурсов.", example='[1, 2, 3]'),
    page_size: int = Query(10, description="Размер 1 страницы. Диапазон - 1...50 элементов."),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources = Query([], description="Фильтрация по типу ресурсов *(массив типов)*.", example='["logo", "screenshot"]'),
    only_urls: bool = Query(False, description="Возвращать только ссылки или полную информацию."),
):
    """
    Возвращает список ресурсов. Фильтрационные списки не должны быть суммарно > 120 элементов.

    Если в переданном списке ресурсов есть ID привязанное к непубличному моду, то будет отказано в доступе!
    """
    resources_list_id = tools.str_to_list(resources_list_id)
    types_resources = tools.str_to_list(types_resources)
    owner_ids = tools.str_to_list(owner_ids)

    if owner_type not in ['mods', 'games']:
        return PlainTextResponse(status_code=405, content="unknown owner_type")

    if len(types_resources) + len(resources_list_id) + len(owner_ids) > 120:
        return JSONResponse(status_code=413, content={"message": "the maximum complexity of filters is 120 elements in sum", "error_id": 1})
    elif page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 2})
    elif page < 0:
        return JSONResponse(status_code=413, content={"message": "incorrect page", "error_id": 3})

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
        mods_ids_check = [ i.owner_id for i in resources ]

        query = session.query(catalog.Mod.id)
        query = query.filter(catalog.Mod.id.in_(mods_ids_check))
        ids_mods = [mod.id for mod in query.all()]

        if len(ids_mods) > 0:
            if not await tools.access_mods(response=response, request=request, mods_ids=ids_mods, check_mode=True):
                session.close()
                return PlainTextResponse(status_code=403, content="Access denied.")

    real_resources = await tools.resources_serialize(resources=resources, only_urls=only_urls)

    # Возврат успешного результата
    session.close()
    return {"database_size": resources_count, "offset": offset, "results": real_resources}


@router.post(
    MAIN_URL+"/add/resource/{owner_type}",
    tags=["Resource"],
    summary="Добавление ресурса",
    status_code=202,
    responses={
        202: {
            "description": "Возвращает ID созданного ресурса.",
            "content": {
                "application/json": {
                    "example": 1
                }
            }
        },
        400: {"description": "Не передан файл и при этом передан неккоректны `resource_url`."},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        405: {"description": "Неизвестный тип ресурса-владельца."},
        500: {"description": "Произошла ошибка на стороне Storage сервера."},
    }
)
async def add_resource(
    response: Response,
    request: Request,
    owner_type: str = Path(description="Тип ресурса-владельца.", examples=["mods", "games"], max_length=64),
    resource_type: str = Form(..., description="Название типа ресурса.", min_length=2, max_length=64),
    resource_url: str = Form("", description="URL ресурса *(если не передан файл)*.", min_length=7, max_length=256),
    resource_owner_id: int = Form(..., description="ID ресурса-владельца."),
    resource_file: UploadFile = File(None, description="Файл ресурса.")
):
    """
    `resource_url` не учитывается если передан `resource_file`
    """
    if owner_type not in ['mods', 'games']:
        return PlainTextResponse(status_code=405, content="unknown owner_type")
    elif owner_type == 'mods':
        access_result = await tools.access_mods(response=response, request=request, mods_ids=[resource_owner_id], edit=True)
    else:
        access_result = await tools.access_admin(response=response, request=request)


    if access_result == True:
        real_url = resource_url

        if resource_file:
            real_file = io.BytesIO(await resource_file.read())
            real_path = f'{owner_type}/{resource_owner_id}/{resource_file.filename}'

            result_code, result_upload, result_status = await tools.storage_file_upload(type="resource", path=real_path, file=real_file)
            if result_status == False:
                return PlainTextResponse(status_code=result_code, content=f'Upload error ({result_upload})')
            else:
                real_url = f'local/{result_upload}'
        elif len(resource_url) <= 6 or len(resource_url) > 256 or not resource_url.startswith('http'):
            return PlainTextResponse(status_code=400, content='Incorrect URL')

        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Resource).values(
            type=resource_type,
            url=real_url,
            date_event=datetime.now(),
            owner_type=owner_type,
            owner_id=resource_owner_id
        )

        result = session.execute(insert_statement)
        id = result.lastrowid  # Получаем ID последней вставленной строки

        session.commit()
        session.close()

        return JSONResponse(status_code=202, content=id)  # Возвращаем значение `id`
    else:
        return access_result

@router.post(
    MAIN_URL+"/edit/resource",
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
    }
)
async def edit_resource(
    response: Response,
    request: Request,
    resource_id: int = Form(..., description="ID ресурса."),
    resource_type: str = Form(None, description="Тип ресурса.", min_length=2, max_length=64),
    resource_url: str = Form(None, description="URL ресурса.", min_length=7, max_length=256),
    resource_file: UploadFile = File(None, description="Файл ресурса *(приоритетней `resource_url`)*.")
):
    session = sessionmaker(bind=catalog.engine)()

    resource = session.query(catalog.Resource).filter_by(id=resource_id)
    got_resource = resource.first()
    if not got_resource:
        return JSONResponse(status_code=404, content="The element does not exist.")

    if got_resource.owner_type == "mods":
        access_result = await tools.access_mods(response=response, request=request, mods_ids=[got_resource.owner_id], edit=True)
    else:
        access_result = await tools.access_admin(response=response, request=request)


    if access_result == True:
        # Подготавливаем данные
        data_edit = {}
        if resource_type:
            data_edit["type"] = resource_type

        if resource_file or resource_url:
            if not resource_file and resource_url:
                if len(resource_url) <= 6 or len(resource_url) > 256 or not resource_url.startswith('http'):
                    return PlainTextResponse(status_code=400, content='Incorrect URL')

            if got_resource.url.startswith("local/") and \
                    not await tools.storage_file_delete(type="resource", path=got_resource.url.replace("local/", "")):
                return JSONResponse(status_code=500, content="delete old file error")

            if resource_file:
                real_file = io.BytesIO(await resource_file.read())
                real_path = f'{got_resource.owner_type}/{got_resource.owner_id}/{resource_file.filename}'

                result_upload_code, result_upload, result_status = await tools.storage_file_upload(type="resource", path=real_path, file=real_file)
                if result_status == False:
                    return JSONResponse(status_code=result_upload_code, content=f'Upload error ({result_upload})')
                else:
                    data_edit["url"] = f'local/{result_upload}'
            else:
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

@router.delete(
    MAIN_URL+"/delete/resource/{owner_type}",
    tags=["Resource"],
    summary="Удаление ресурса",
    status_code=200,
    responses={
        200: {"description": "Успешное удаление"},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        404: {"description": "Ресурс не найден."},
        405: {"description": "Неккоректный `owner_type`. Доступные значения: `mods`, `games`."},
        500: {"description": "Произошла ошибка на стороне Storage сервера."}
    }   
)
async def delete_resource(
    response: Response,
    request: Request,
    owner_type: str = Path(description="Тип ресурса.", examples=["mods", "games"], max_length=64),
    resource_id: int = Form(..., description="ID ресурса для удаления."),
):
    if owner_type not in ['mods', 'games']:
        return PlainTextResponse(status_code=405, content="unknown owner_type")
    elif owner_type == 'mods':
        session = sessionmaker(bind=catalog.engine)()
        query = session.query(catalog.Resource)
        query = query.filter_by(owner_type=owner_type, owner_id=resource_id).first()
        session.close()

        if query:
            access_result = await tools.access_mods(response=response, request=request, mods_ids=[query.owner_id], edit=True)
        else:
            return PlainTextResponse(status_code=404, content="not found")
    else:
        access_result = await tools.access_admin(response=response, request=request)


    if access_result == True:
        if await tools.delete_resources(owner_type=owner_type, resources_ids=[resource_id]):
            return PlainTextResponse(status_code=200, content="Complite!")
        else:
            return PlainTextResponse(status_code=500, content="Unknown error")
    else:
        return access_result
