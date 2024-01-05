import account_sql as account
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
import aiohttp
import json


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

async def mod_to_backend(response: Response, request: Request, url:str, body:dict = {}):
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)

        # Выполнение запроса
        session = Session()
        row = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1))
        row_result = row.first()

        #TODO тут нужна детальная проверка правомерности: чей мод, в каком статусе если в числе авторов и в этом контексте есть ли права на его редактирование
        if row_result.admin:
            async with aiohttp.ClientSession() as session:
                async with session.post(url=url, data=body) as response:
                    result = await response.text()
                    if response.status >= 200 and response.status < 300:
                        result = json.loads(result)

                    return response.status, result, JSONResponse(status_code=200, content=result)
        else:
            return -2, '', JSONResponse(status_code=403, content="Вы не админ!")
    else:
        return -1, '', JSONResponse(status_code=401, content="Недействительный ключ сессии!")
