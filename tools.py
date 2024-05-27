from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
import ow_config as config
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from sqlalchemy import desc
import aiohttp
import datetime
import json
import bcrypt


async def check_token(token_name: str, token: str) -> bool:
    # Получаем значение хеша токена из config по имени token_name
    stored_token_hash = getattr(config, token_name, None)
    
    if stored_token_hash is None:
        print(f"Токен `{token_name}` не найден в config!")
        return False
    
    # Хеш из config должен быть строкой, конвертируем в байты
    stored_token_hash = stored_token_hash.encode()
    
    # Хешируем переданный токен с использованием bcrypt и проверяем соответствие
    return bcrypt.checkpw(token.encode(), stored_token_hash)

async def access_admin(response: Response, request: Request) -> JSONResponse:
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


def str_to_list(string: str):
    try:
        string = json.loads(string)
        if type(string) is not list:
            string = []
    except:
        string = []
    return string

async def anonymous_access_mods(user_id: int, mods_ids: list[int], edit: bool = False, check_mode: bool = False):
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

async def access_mods(response: Response, request: Request, mods_ids: list[int], edit: bool = False, check_mode: bool = False):
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
    session = sessionmaker(bind=catalog.engine)()

    result = session.query(catalog.Game).filter_by(id=game_id).first()

    session.close()
    return bool(result)

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
