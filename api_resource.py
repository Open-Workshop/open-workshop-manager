from fastapi import APIRouter, Request, Response, Form, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse
import tools
import json
import io
import aiohttp
from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from ow_config import MAIN_URL, SERVER_ADDRESS
import ow_config as config
from datetime import datetime


router = APIRouter()


@router.get("/list/resources/{owner_type}/{resources_list_id}")
async def list_resources(response: Response, request: Request, owner_type: str, resources_list_id):
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

    # Возврат успешного результата
    session.close()
    return {"database_size": resources_count, "results": resources}

@router.get(MAIN_URL+"/list/resources/{owner_type}/{mods_ids_list}", tags=["Resource"])
async def list_resources_for_elements(response: Response, request: Request, owner_type: str, mods_ids_list,
                                      page_size: int = 10, page: int = 0, types_resources=[]):
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

        # Возврат успешного результата
        session.close()
        return {"database_size": resources_count, "results": resources}
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
        return PlainTextResponse(status_code=404, content="unknown owner_type")
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

@router.post(MAIN_URL+"/edit/resource/{owner_type}", tags=["Resource"])
async def edit_resource(response: Response, request: Request, owner_type: str, resource_id: int,
                        resource_type: str = Form(None), resource_url: str = Form(None),
                        resource_owner_id: int = Form(None)):
    """
    Тестовая функция
    """
    # TODO работа напрямую с базой
    # TODO возможность менять файл ресурса

    async with aiohttp.ClientSession() as NETsession:
        async with NETsession.get(url=SERVER_ADDRESS+f'/list/resources/%5B{resource_id}%5D?token={config.token_info_mod}') as aioresponse:
            data_res = json.loads(await aioresponse.text())

            if data_res["database_size"] <= 0:
                return JSONResponse(status_code=404, content="Ресурс не найден!")
            else:
                url = SERVER_ADDRESS + f'/account/edit/resource?token={config.token_edit_resource}&resource_id={resource_id}'
                body = {}
                if resource_type is not None: body["resource_type"] = resource_type
                if resource_url is not None: body["resource_url"] = resource_url
                if resource_owner_id is not None: body["resource_owner_id"] = resource_owner_id

                result_req = await tools.mod_to_backend(response=response, request=request, url=url, body=body, mod_id=data_res["results"][0]["owner_id"])
                return result_req[2]

@router.delete(MAIN_URL+"/delete/resource/{owner_type}", tags=["Resource"])
async def delete_resource(response: Response, request: Request, owner_type: str, resource_id: int):
    """
    Тестовая функция
    """
    # TODO работа напрямую с базой
    # TODO удаляем файл если он сохранен локально

    async with aiohttp.ClientSession() as NETsession:
        async with NETsession.get(url=SERVER_ADDRESS+f'/list/resources/%5B{resource_id}%5D?token={config.token_info_mod}') as aioresponse:
            data_res = json.loads(await aioresponse.text())

            if data_res["database_size"] <= 0:
                return JSONResponse(status_code=404, content="Ресурс не найден!")
            else:
                url = SERVER_ADDRESS + f'/account/delete/resource?token={config.token_delete_resource}&resource_id={resource_id}'

                result_req = await tools.mod_to_backend(response=response, request=request, url=url, mod_id=data_res["results"][0]["owner_id"])
                return result_req[2]
