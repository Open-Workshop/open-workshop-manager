from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import JSONResponse
import tools
import json
import aiohttp
from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
from sqlalchemy.orm import sessionmaker
from ow_config import MAIN_URL, SERVER_ADDRESS
import ow_config as config


router = APIRouter()


@router.get("/list/resources/{resources_list_id}")
async def list_resources(response: Response, request: Request, resources_list_id):
    """
    Возвращает список ресурсов по их id. Список в размере не должен быть > 80!
    Если в переданном списке ресурсов есть ID привязанное к непубличному моду, то будет отказано в доступе!
    """
    resources_list_id = tools.str_to_list(resources_list_id)

    if len(resources_list_id) > 80:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Resource)
    query = query.filter(catalog.Resource.id.in_(resources_list_id))

    resources_count = query.count()
    resources = query.all()

    # Проверка правомерности
    if resources_count > 0:
        query = query.filter_by(owner_type='mod')

        mods_ids_check = []
        for i in query.all():
            mods_ids_check.append(i.owner_id)

        if len(mods_ids_check) > 0:
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

@router.get(MAIN_URL+"/list/resources/mods/{mods_ids_list}", tags=["Resource"])
async def list_resources_for_mods(response: Response, request: Request, mods_ids_list, page_size: int = 10,
                                  page: int = 0, types_resources=[]):
    """
    Тестовая функция
    """
    # TODO работа с микросервисом напрямую

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

    async with aiohttp.ClientSession() as NETsession:
        async with NETsession.get(url=SERVER_ADDRESS+f'/public/mod/{str(mods_ids_list)}') as ioresponse:
            result = json.loads(await ioresponse.text())

            l = []
            for i in mods_ids_list:
                if i not in result:
                    l.append(i)

            if len(l) > 0:
                access_result = await account.check_access(request=request, response=response)

                if access_result and access_result.get("owner_id", -1) >= 0:
                    # Создание сессии
                    Session = sessionmaker(bind=account.engine)
                    session = Session()

                    row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1)).first()

                    rowT = session.query(account.mod_and_author).filter_by(user_id=access_result.get("owner_id", -1))
                    rowT = rowT.filter(account.mod_and_author.c.mod_id.in_(l))

                    if rowT.count() != len(l) and not row.admin:
                        session.close()
                        return JSONResponse(status_code=403, content="Доступ воспрещен!")
                    session.close()
                else:
                    return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

            async with aiohttp.ClientSession() as NETsession:
                url = SERVER_ADDRESS+f'/list/resources_mods/{str(mods_ids_list)}?token={config.token_info_mod}'
                if page_size is not None: url+=f'&page_size={page_size}'
                if page is not None: url+=f'&page={page}'
                if types_resources is not None: url+=f'&types_resources={types_resources}'

                async with NETsession.get(url=url) as aioresponse:
                    return json.loads(await aioresponse.text())

# TODO /list/resources/games/{mods_ids_list}


@router.post(MAIN_URL+"/add/resource", tags=["Resource"])
async def add_resource(response: Response, request: Request, resource_type_name: str = Form(...),
                       resource_url: str = Form(...), resource_owner_id: int = Form(...)):
    """
    Тестовая функция
    """
    # TODO Работа с микросервисом напрямую
    # TODO Возможность добавлять ресурс на статик сервер (файл передаём сюда)

    url = SERVER_ADDRESS + f'/account/add/resource?token={config.token_add_resource}'
    result_req = await tools.mod_to_backend(response=response, request=request, mod_id=resource_owner_id, url=url, body={
        "resource_type_name": resource_type_name,
        "resource_url": resource_url,
        "resource_owner_id": resource_owner_id
    })
    return result_req[2]

@router.post(MAIN_URL+"/edit/resource", tags=["Resource"])
async def edit_resource(response: Response, request: Request, resource_id: int, resource_type: str = Form(None),
                        resource_url: str = Form(None), resource_owner_id: int = Form(None)):
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

@router.delete(MAIN_URL+"/delete/resource", tags=["Resource"])
async def delete_resource(response: Response, request: Request, resource_id: int):
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
