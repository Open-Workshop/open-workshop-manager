from fastapi import APIRouter, Request, Response, Form, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse
import tools
import io
from sql_logic import sql_catalog as catalog
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from ow_config import MAIN_URL
from datetime import datetime


router = APIRouter()


@router.get("/list/resources/{owner_type}/{resources_list_id}", tags=["Resource"])
async def list_resources(response: Response, request: Request, owner_type: str, resources_list_id, only_urls: bool = False):
    """
    Возвращает список ресурсов по их id. Список в размере не должен быть > 80!
    Если в переданном списке ресурсов есть ID привязанное к непубличному моду, то будет отказано в доступе!
    """
    resources_list_id = tools.str_to_list(resources_list_id)

    if owner_type not in ['mods', 'games']:
        return JSONResponse(status_code=400, content={"message": "unknown owner_type", "error_id": 5})

    if len(resources_list_id) > 80:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Resource)
    query = query.filter_by(owner_type=owner_type)
    query = query.filter(catalog.Resource.id.in_(resources_list_id))

    resources_count = query.count()
    resources = query.all()

    # Проверка правомерности
    if resources_count > 0:
        mods_ids_check = [ i.owner_id for i in resources ]

        query = session.query(catalog.Mod.id)
        query = query.filter(catalog.Mod.id.in_(mods_ids_check))
        ids_mods = [mod.id for mod in query.all()]

        if len(ids_mods) > 0:
            ids_access = await tools.access_mods(response=response, request=request, mods_ids=ids_mods, check_mode=True)
            if len(ids_access) != len(ids_mods):
                session.close()
                return JSONResponse(status_code=403, content="Access denied.")

    real_resources = await tools.resources_serialize(resources=resources, only_urls=only_urls)

    # Возврат успешного результата
    session.close()
    return {"database_size": resources_count, "results": real_resources}

@router.get(MAIN_URL+"/list/resources/{owner_type}/{mods_ids_list}", tags=["Resource"])
async def list_resources_for_elements(response: Response, request: Request, owner_type: str, mods_ids_list,
                                      page_size: int = 10, page: int = 0, types_resources=[], 
                                      only_urls: bool = False):
    """
    Тестовая функция
    """
    if owner_type not in ['mods', 'games']:
        return JSONResponse(status_code=400, content={"message": "unknown owner_type", "error_id": 5})

    mods_ids_list = tools.str_to_list(mods_ids_list)
    types_resources = tools.str_to_list(types_resources)
    if len(mods_ids_list) < 1 or len(mods_ids_list) > 50:
        return JSONResponse(status_code=413, content={"message": "the size of the array is not correct", "error_id": 1})
    if len(types_resources) + len(mods_ids_list) > 80:
        return JSONResponse(status_code=413, content={"message": "the maximum complexity of filters is 80 elements in sum", "error_id": 2})
    elif page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 3})
    elif page < 0:
        return JSONResponse(status_code=413, content={"message": "incorrect page", "error_id": 4})

    access_result = owner_type != "mods"
    if not access_result:
        access_result = await tools.access_mods(response=response, request=request, mods_ids=mods_ids_list)

    if access_result == True:
        # Создание сессии
        session = sessionmaker(bind=catalog.engine)()

        # Выполнение запроса
        query = session.query(catalog.Resource)
        query = query.filter_by(owner_type=owner_type)
        query = query.filter(catalog.Resource.id.in_(mods_ids_list))

        resources_count = query.count()
        resources = query.all()

        real_resources = await tools.resources_serialize(resources=resources, only_urls=only_urls)

        # Возврат успешного результата
        session.close()
        return {"database_size": resources_count, "results": real_resources}
    else:
        return access_result


@router.post(MAIN_URL+"/add/resource/{owner_type}", tags=["Resource"])
async def add_resource(response: Response, request: Request, owner_type: str, resource_type_name: str = Form(...),
                       resource_url: str = Form(...), resource_owner_id: int = Form(...),
                       resource_file: UploadFile = File(...)):
    """
    resource_url не учитывается если передан resource_file
    """
    if owner_type not in ['mods', 'games']:
        return PlainTextResponse(status_code=400, content="unknown owner_type")
    elif owner_type == 'mods':
        access_result = await tools.access_mods(response=response, request=request, mods_ids=[resource_owner_id], edit=True)
    else:
        access_result = await tools.access_admin(response=response, request=request)


    if access_result == True:
        real_url = resource_url

        if resource_file:
            real_file = io.BytesIO(await resource_file.read())
            real_path = f'{owner_type}/{resource_owner_id}/{resource_file.filename}'

            result_upload = await tools.storage_file_upload(type="resource", path=real_path, file=real_file)
            if not result_upload:
                return JSONResponse(status_code=500, content='Upload error')
            else:
                real_url = f'local/{result_upload}'

        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Resource).values(
            type=resource_type_name,
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

@router.post(MAIN_URL+"/edit/resource", tags=["Resource"])
async def edit_resource(response: Response, request: Request, resource_id: int, resource_type: str = Form(None),
                        resource_url: str = Form(None), resource_file: UploadFile = File(...)):
    """
    Тестовая функция
    """
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
            if resource.url.startswith("local/") and \
                    not await tools.storage_file_delete(type="resource", path=resource.url.replace("local/", "")):
                return JSONResponse(status_code=500, content="delete old file error")

            if resource_file:
                real_file = io.BytesIO(await resource_file.read())
                real_path = f'{got_resource.owner_type}/{got_resource.owner_id}/{resource_file.filename}'

                result_upload = await tools.storage_file_upload(type="resource", path=real_path, file=real_file)
                if not result_upload:
                    return JSONResponse(status_code=500, content='Upload error')
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

@router.delete(MAIN_URL+"/delete/resource/{owner_type}", tags=["Resource"])
async def delete_resource(response: Response, request: Request, owner_type: str, resource_id: int):
    """
    Тестовая функция
    """
    if owner_type not in ['mods', 'games']:
        return PlainTextResponse(status_code=400, content="unknown owner_type")
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
