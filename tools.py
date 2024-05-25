from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from sqlalchemy import desc
import aiohttp
import datetime
import json


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

async def access_mod(response: Response, request: Request, mod_id: int, edit: bool = False):
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        session = sessionmaker(bind=account.engine)()

        # Выполнение запроса
        user_req = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1)).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if edit and (user_req.mute_until and user_req.mute_until > datetime.datetime.now()):
                    return False

                in_mod = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=access_result.get("owner_id", -1)).first()

                if in_mod:
                    if not edit: return True

                    if user_req.change_self_mods:
                        if in_mod.owner:
                            return True
                elif edit and user_req.change_mods:
                    return True
            return False
        # АДМИН
        # или
        # ВЛАДЕЛЕЦ МОДА и НЕ В МУТЕ и ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ СВОИХ МОДОВ
        # или
        # УЧАСТНИК и НЕ В МУТЕ и ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ СВОИХ МОДОВ и ДЕЙСТВИЕ НЕ ЗАПРЕЩЕНО УЧАСТНИКАМ
        # или
        # НЕ В МУТЕ И ИМЕЕТ ПРАВО НА РЕДАКТИРОВАНИЕ ЧУЖИХ МОДОВ

        #т.е.:
        #АДМИН или (НЕ В МУТЕ и ((в числе участников И имеет право на редактирование своих модов И (владелец ИЛИ действие не запрещено участникам)) ИЛИ не участник И имеет право на редактирование чужих модов))

        if await mini():
            session.close()
            return True
        else:
            session.close()
            return JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

async def check_game_exists(game_id:int) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://api.openworkshop.su/info/game/{game_id}') as response:
            result = json.loads(await response.text())

            return bool(type(result['result']) is dict and len(result['result']) > 0)

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
