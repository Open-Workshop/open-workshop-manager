from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
import ow_config as config
from io import BytesIO
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from sqlalchemy import desc
import aiohttp
import datetime
import json
import bcrypt


async def check_token(token_name: str, token: str) -> bool:
    """
    Check if the provided token matches the stored token hash for the given token name.

    Args:
        token_name (str): The name of the token to check.
        token (str): The token to compare with the stored token hash.

    Returns:
        bool: True if the provided token matches the stored token hash, False otherwise.
    """
    # Получаем значение хеша токена из config по имени token_name
    stored_token_hash = getattr(config, token_name, None)
    
    if stored_token_hash is None:
        print(f"Токен `{token_name}` не найден в config!")
        return False
    
    # Хеш из config должен быть строкой, конвертируем в байты
    stored_token_hash = stored_token_hash.encode()
    
    # Хешируем переданный токен с использованием bcrypt и проверяем соответствие
    return bcrypt.checkpw(token.encode(), stored_token_hash)

async def access_admin(response: Response, request: Request) -> JSONResponse | bool:
    """
    Asynchronously checks if the user has admin access.

    Args:
        response (Response): The response object.
        request (Request): The request object.

    Returns:
        JSONResponse: If the user has admin access, returns True.
                      If the user does not have admin access, returns a JSONResponse object with status code 403 and content "Вы не админ!".
                      If the session key is invalid, returns a JSONResponse object with status code 401 and content "Недействительный ключ сессии!".
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Выполнение запроса
        session = sessionmaker(bind=account.engine)()
        row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1))
        row_result = row.first()

        if row_result.admin:
            return True
        else:
            return JSONResponse(status_code=403, content="Вы не админ!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")


def str_to_list(string: str | list) -> list:
    """
    Convert a string representation of a list to an actual list.

    Parameters:
        string (str): The string representation of the list.

    Returns:
        list: The converted list. If the conversion fails, an empty list is returned.
    """
    try:
        string = json.loads(string)
        if type(string) is not list:
            string = []
    except:
        string = []
    return string


async def resources_serialize(resources:list[catalog.Resource], only_urls:bool = False) -> list[dict] | list[str]:
    """
    Serializes a list of `catalog.Resource` objects into a list of dictionaries or a list of strings.
    
    Args:
        resources (list[catalog.Resource]): A list of `catalog.Resource` objects to be serialized.
        only_urls (bool, optional): If set to `True`, only the `real_url` attribute of each resource will be included in the serialized list. Defaults to `False`.
    
    Returns:
        list[dict] | list[str]: A list of dictionaries containing the serialized resource information, or a list of strings if `only_urls` is `True`.
    """
    real_resources = []
    for resource in resources:
        if only_urls:
            real_resources.append(resource.real_url)
        else:
            real_resources.append({
                "id": resource.id,
                "type": resource.type,
                "url": resource.real_url,
                "owner_id": resource.owner_id,
                "owner_type": resource.owner_type,
                "date_event": resource.date_event
            })
    return real_resources


async def anonymous_access_mods(user_id: int, mods_ids: list[int], edit: bool = False, check_mode: bool = False) -> bool | list[int]:
    """
    Asynchronously checks if the given user has access to modify the specified mods.

    Parameters:
        user_id (int): The ID of the user.
        mods_ids (list[int]): A list of mod IDs.
        edit (bool, optional): Whether the user is allowed to edit the mods. Defaults to False.
        check_mode (bool, optional): Whether to return a list of mod IDs that the user has access to. Defaults to False.

    Returns:
        bool or list[int]: If check_mode is True, returns a list of mod IDs that the user has access to. Otherwise, returns True if the user has access, False otherwise.
    """
    if isinstance(mods_ids, int): mods_ids = [mods_ids]

    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    # Выполнение запроса
    user_req = session.query(account.Account).filter_by(id=user_id).first()

    async def mini():
        if user_req.admin:
            return True
        else:
            if edit and (user_req.mute_until and user_req.mute_until > datetime.datetime.now()):
                return False

            mods_to_user = session.query(account.mod_and_author).filter_by(user_id=user_id)
            mods_to_user = mods_to_user.filter(account.mod_and_author.c.mod_id.in_(mods_ids))

            mods_to_user = {mod.mod_id: mod.owner for mod in mods_to_user.all()}

            session_catalog = sessionmaker(bind=account.engine)()
            mods = session_catalog.query(catalog.Mod.id, catalog.Mod.public)
            mods = mods.filter(catalog.Mod.id.in_(mods_ids)).all()

            output_check = []

            for mod in mods:
                output_check.append(mod.id)

                if mod.id in mods_to_user:
                    if edit:
                        if not user_req.change_self_mods or not mods_to_user.get(mod.id, False):
                            if check_mode:
                                output_check.remove(mod.id)
                            else:
                                return False
                elif mod.public <= 1:
                    if edit and not user_req.change_mods:
                        if check_mode:
                            output_check.remove(mod.id)
                        else:
                            return False
                else:
                    if check_mode:
                        output_check.remove(mod.id)
                    else:
                        return False
            else:
                if check_mode:
                    return output_check
                else:
                    return True
    # АДМИН
    # или
    # ВЛАДЕЛЕЦ МОДА и НЕ В МУТЕ и ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ СВОИХ МОДОВ
    # или
    # УЧАСТНИК и НЕ В МУТЕ и ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ СВОИХ МОДОВ и ДЕЙСТВИЕ НЕ ЗАПРЕЩЕНО УЧАСТНИКАМ
    # или
    # НЕ В МУТЕ И ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ ЧУЖИХ МОДОВ

    #т.е.:
    #АДМИН или (НЕ В МУТЕ и ((в числе участников И имеет право на редактирование своих модов И (владелец ИЛИ действие не запрещено участникам)) ИЛИ не участник И имеет право на редактирование чужих модов))

    mini_result = await mini()
    
    session.close()
    return mini_result

async def access_mods(response: Response, request: Request, mods_ids: list[int] | int, edit: bool = False, check_mode: bool = False) -> JSONResponse | list[int]:
    """
    Asynchronously checks the access permissions for a set of mods.

    Args:
        response (Response): The response object.
        request (Request): The request object.
        mods_ids (list[int]): The list of mod IDs to check access for.
        edit (bool, optional): Whether to check for edit access. Defaults to False (read access).
        check_mode (bool, optional): Whether to check in check mode. Defaults to False.

    Returns:
        If check_mode is True:
            - If access is granted: Returns a list of mod IDs that the user has access to.
            - If access is denied: Returns a JSONResponse object with status code 403 and content "Заблокировано!".
            - If the session key is invalid: Returns a JSONResponse object with status code 401 and content "Недействительный ключ сессии!".
        If check_mode is False:
            - If access is granted: Returns True.
            - If access is denied: Returns a JSONResponse object with status code 403 and content "Заблокировано!".
            - If the session key is invalid: Returns a JSONResponse object with status code 401 and content "Недействительный ключ сессии!".
    """
    if isinstance(mods_ids, int): mods_ids = [mods_ids]

    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        mini_result = await anonymous_access_mods(user_id=access_result.get("owner_id", -1), mods_ids=mods_ids, edit=edit, check_mode=check_mode)

        if mini_result != False:
            return mini_result
        else:
            return JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

async def check_game_exists(game_id:int) -> bool:
    """
    Asynchronously checks if a game with the given ID exists in the catalog.

    Parameters:
        game_id (int): The ID of the game to check.

    Returns:
        bool: True if a game with the given ID exists, False otherwise.
    """
    session = sessionmaker(bind=catalog.engine)()

    result = session.query(catalog.Game).filter_by(id=game_id).first()

    session.close()
    return bool(result)

async def storage_file_upload(type: str, path: str, file: BytesIO) -> bool | str:
    """
    Uploads a file to the storage service.

    Args:
        type (str): The type of the file.
        path (str): Path of the file to be uploaded.
        file (BytesIO): The file content to be uploaded.

    Returns:
        bool | str: False if the file upload failed.
                    If the file was uploaded successfully, the response body is returned as a path to the uploaded file.
    """
    
    real_url = f'{config.STORAGE_URL}/upload?token={config.storage_upload_token}'

    async with aiohttp.ClientSession() as session:
        async with session.put(real_url, data={
                                            'file': file,
                                            'type': type,
                                            'path': path}
                                ) as resp:
            if resp.status != 201:
                return False
            else:
                return str(await resp.read()) # Возвращаем итоговый url
            
async def storage_file_delete(type: str, path: str) -> bool:
    """
    Deletes a file from the storage.

    Args:
        type (str): The type of the file.
        path (str): Path to the file to be deleted.

    Returns:
        bool: True if the file was successfully deleted, False otherwise.
    """

    real_url = f'{config.STORAGE_URL}/delete?token={config.storage_delete_token}'

    async with aiohttp.ClientSession() as session:
        async with session.delete(real_url, data={'type': type, 'path': path}) as resp:
            return resp.status != 200


async def delete_resources(owner_type:str, resources_ids:list[int] = [], owner_id: int = -1) -> bool:
    """
    Deletes resources based on the owner type and resource IDs or owner ID.
    If resources_ids is not empty, the resources with the specified IDs will be deleted. If owner_id is not -1, the resources of the specified owner will be deleted.
    If both resources_ids and owner_id are empty, return False (call error).

    Args:
        owner_type (str): The type of the owner.
        resources_ids (list[int], optional): A list of resource IDs to delete. Defaults to an empty list.
        owner_id (int, optional): The ID of the owner. Defaults to -1.

    Returns:
        bool: True if the resources are successfully deleted, False otherwise.
    """
    #Нужно обязательно передать либо resources_ids либо owner_id (сами фильтры не противоречат друг другу, но не рекомендую использовать одновременно).
    #Если resources_ids будут удаляться конкретные ресурсы, а если owner_id, то ресурсы овнера (если без переданного списка, то все).
    
    if len(resources_ids) <= 0 and owner_id <= 0:
        return False

    Session = sessionmaker(bind=catalog.engine)

    session = Session()
    query = session.query(catalog.Resource).filter_by(owner_type=owner_type)

    if owner_id > 0: query = query.filter_by(owner_id=owner_id)
    if len(resources_ids) > 0: query = query.filter(catalog.Resource.id.in_(resources_ids))

    resources = { i.id: i.url for i in query.all() }
    session.close()

    deleted = []
    for resource in resources.keys():
        url = resources[resource]
        if url.startswith("local/"):
            delete_result = await storage_file_delete(type="resource", path=url.replace("local/", ""))

            if delete_result: deleted.append(resource)
            else: print(f"Delete Resources: Error: resource not deleted ({resource})")
        else:
            deleted.append(resource)

    if len(deleted) > 0:
        session = Session()
        session.query(catalog.Resource).filter(catalog.Resource.id.in_(deleted)).delete(synchronize_session=False)
        session.commit()
        session.close()
    else:
        print("Delete Resources: No resources deleted")

    return True


def sort_mods(sort_by: str): 
    match sort_by:
        case 'NAME':
            return catalog.Mod.name
        case 'iNAME':
            return desc(catalog.Mod.name)
        case 'SIZE':
            return catalog.Mod.size
        case 'iSIZE':
            return desc(catalog.Mod.size)
        case 'CREATION_DATE':
            return catalog.Mod.date_creation
        case 'iCREATION_DATE':
            return desc(catalog.Mod.date_creation)
        case 'UPDATE_DATE':
            return catalog.Mod.date_update
        case 'iUPDATE_DATE':
            return desc(catalog.Mod.date_update)
        case 'REQUEST_DATE':
            return catalog.Mod.date_request
        case 'iREQUEST_DATE':
            return desc(catalog.Mod.date_request)
        case 'SOURCE':
            return catalog.Mod.source
        case 'iSOURCE':
            return desc(catalog.Mod.source)
        case 'iMOD_DOWNLOADS':
            return desc(catalog.Mod.downloads)
        case _:
            return catalog.Mod.downloads  # По умолчанию сортируем по загрузкам


def sort_games(sort_by: str):
    match sort_by:
        case 'NAME':
            return catalog.Game.name
        case 'iNAME':
            return desc(catalog.Game.name)
        case 'TYPE':
            return catalog.Game.type
        case 'iTYPE':
            return desc(catalog.Game.type)
        case 'CREATION_DATE':
            return catalog.Game.creation_date
        case 'iCREATION_DATE':
            return desc(catalog.Game.creation_date)
        case 'SOURCE':
            return catalog.Game.source
        case 'iSOURCE':
            return desc(catalog.Game.source)
        case 'MODS_COUNT':
            return catalog.Game.mods_count
        case 'iMODS_COUNT':
            return desc(catalog.Game.mods_count)
        case 'MOD_DOWNLOADS':
            return catalog.Game.mods_downloads
        case _:
            return desc(catalog.Game.mods_downloads)
