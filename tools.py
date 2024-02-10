import account_sql as account
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
import aiohttp
import datetime
import json

def str_to_list(string: str):
    try:
        string = json.loads(string)
        if type(string) is not list:
            string = []
    except:
        string = []
    return string

async def to_backend(response: Response, request: Request, url:str, body:dict = {}) -> JSONResponse:
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)

        # Выполнение запроса
        session = Session()
        row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1))
        row_result = row.first()

        if row_result.admin:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=body) as response:
                    result = await response.text()

                    return JSONResponse(status_code=response.status, content=json.loads(result))
        else:
            return JSONResponse(status_code=403, content="Вы не админ!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

async def mod_to_backend(response: Response, request: Request, url:str, mod_id:int, body:dict = {}):
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)

        # Выполнение запроса
        session = Session()
        user_req = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1)).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if user_req.mute_until and user_req.mute_until > datetime.datetime.now():
                    return False

                in_mod = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=access_result.get("owner_id", -1)).first()

                if in_mod:
                    if user_req.change_self_mods:
                        if in_mod.owner:
                            return True
                elif user_req.change_mods:
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
            async with aiohttp.ClientSession() as NETsession:
                async with NETsession.post(url=url, data=body) as response:
                    result = await response.text()
                    if response.status >= 200 and response.status < 300:
                        result = json.loads(result)

                    session.close()
                    return response.status, result, JSONResponse(status_code=response.status, content=result)
        else:
            session.close()
            return -2, '', JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return -1, '', JSONResponse(status_code=401, content="Недействительный ключ сессии!")

async def check_game_exists(game_id:int) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://api.openworkshop.su/info/game/{game_id}') as response:
            result = json.loads(await response.text())

            return bool(type(result['result']) is dict and len(result['result']) > 0)
