from fastapi import APIRouter, Request, Response, Form, Path, Query, File, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sql_logic import sql_account as account
import tools
import re
import io
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, func
from sql_logic import sql_catalog as catalog
from sql_logic import sql_statistics as statistics
from ow_config import MAIN_URL
import ow_config as config


router = APIRouter()


@router.get(
    MAIN_URL+"/download/{mod_id}",
    tags=["Mod"],
    summary="Скачивание мода",
    status_code=307,
    responses={
        307: {
            "description": "Перенаправление на фактический адрес скачивания мода",
        }
    }
)
async def download_mod(
    mod_id: int = Path(description="ID мода"),
):
    """
    Функция скачивания мода и учета количества скачиваний.

    Не рекомендую на уровне пользователя использовать фактический адрес, т.к. он может менятся, и данная функци доп. уровень абстракции.
    """
    statistics.update("mod", mod_id, "download")
    return RedirectResponse(url=F'{config.STORAGE_URL}/download/archive/mods/{mod_id}/main.zip')

@router.get(
    MAIN_URL+"/list/mods/access/{ids_array}",
    tags=["Mod"],
    summary="Проверка прав доступа к модам",
    status_code=200,
    responses={
        200: {
            "description": "Массив ID модов",
            "content": {
                "application/json": {
                    "example": [1, 2, 3]
                }
            }
        },
        403: {
            "description": "Нет доступа (не админ И не передан правильный токен)",
            "content": {
                "text/plain": {
                    "example": "Access denied"
                }
            }
        }
    }
)
async def access_to_mods(
    response: Response, 
    request: Request, 
    ids_array = Path(description="Массив ID модов"), 
    edit: bool = Query(False, description="Фильтр на edit доступ"),
    user: int = Query(-1, description="ID пользователя"),
    token: str = Query("none", description="Токен для проверки прав других пользователей, аналог токена - админские права просящего")
):
    """
    Принимает массив ID модов, возвращает этот же массив в котором ID модов к которым есть read (или выше) доступ.

    Используется в Storage для проверки правомерности доступа к архиву мода.
    """
    ids_array = tools.str_to_list(ids_array)
    if user >= 0:
        if user == 0:  # Проверка неавторизованного доступа
            if edit: return [] # Неавторизованные пользователи не имеют edit прав, нет нужды обращаться к базе
            
            session = sessionmaker(bind=catalog.engine)()

            # Выполнение запроса
            mods = session.query(catalog.Mod.id, catalog.Mod.public).filter(catalog.Mod.id.in_(ids_array))
            mods = mods.filter(catalog.Mod.public <= 1).all()

            mods_ids = [ i.id for i in mods ]

            session.close()
            return mods_ids
        elif tools.check_token(token_name="access_mods_check_anonymous", token=token) or tools.access_admin(response=response, request=request):
            return tools.anonymous_access_mods(user_id=user, mods_ids=ids_array, edit=edit, check_mode=True)
        else:
            return PlainTextResponse(status_code=403, content="Access denied")
    else:
        return tools.access_mods(response=response, request=request, mods_ids=ids_array, edit=edit, check_mode=True)

@router.get(
    MAIN_URL+"/list/mods/public/{ids_array}",
    tags=["Mod"],
    summary="Возвращает список публичных модов",
    status_code=200,
    responses={
        200: {
            "description": "Массив ID модов",
            "content": {
                "application/json": {
                    "example": [1, 2, 3]
                }
            }
        },
        413: {
            "description": "Слишком большой массив ID модов",
            "content": {
                "text/plain": {
                    "example": "the size of the array is not correct"
                }
            }
        }
    }
)
async def public_mods(
    ids_array = Path(description="Массив ID модов (максимум 50 штук)"),
    in_catalog:bool = Query(False, description="Возвращает только полностью публичные моды")
):
    ids_array = tools.str_to_list(ids_array)

    if len(ids_array) < 1 or len(ids_array) > 50:
        return PlainTextResponse(status_code=413, content="the size of the array is not correct")

    output = []

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod)
    if in_catalog:
        query = query.filter(catalog.Mod.public == 0)
    else:
        query = query.filter(catalog.Mod.public <= 1)

    query = query.filter(catalog.Mod.id.in_(ids_array))
    for i in query:
        output.append(i.id)

    session.close()
    return output

@router.get(
    MAIN_URL+"/list/mods/",
    tags=["Mod"],
    summary="Возвращает список модов",
    status_code=200,
    responses={
        200: {
            "description": "Массив словарей с информацией о модах",
            "content": {
                "application/json": {
                    "example": {
                        "database_size": 123, 
                        "offset": 123, 
                        "results": [
                            {
                                "id": 1,
                                "name": "name",
                                "date_creation": "1984-01-01 00:00:00",
                                "date_update": "1984-01-01 00:00:00"
                            },
                            "Access denied (hide info)",
                            {
                                "id": 3,
                                "name": "name",
                                "date_creation": "1984-01-01 00:00:00",
                                "date_update": "1984-01-01 00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        413: {
            "description": "Слишком сложный запрос ИЛИ page_size вне диапазона.",
        }
    }
)
async def mod_list(
    response: Response, 
    request: Request, 
    page_size: int = Query(10, description="Размер 1 страницы. Диапазон - 1...50 элементов."), 
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    sort: str = Query("DOWNLOADS", description="Сортировка. Подробнее в полном описании функции."),
    tags = Query([], description="Массив ID тегов", example="[1, 2, 3]"),
    game: int = Query(-1, description="ID игры."),
    allowed_ids = Query([], description="Массив ID разрешенных модов.", example="[1, 2, 3]"),
    independents: bool = Query(False, description="Не передавать моды с зависимостями."),
    primary_sources = Query([], description="Массив разрешенных источников.", example="['local', 'steam']"),
    name: str = Query("", description="Поиск по названию."),
    user: int = Query(0, description="Фильтрация по модам определенного автора, 0 <= не фильтровать."),
    user_owner: int = Query(-1, description="Фильтрация по роли пользователя в разработке модов (работает если активен user параметр). -1 <= не фильтровать, 0 - владелец, 1 - разработчик"),
    user_catalog: bool = Query(True, description="Включать только публичные моды пользователя*"),
    short_description: bool = Query(False, description="Включать ли в ответ короткое описание модов."),
    description: bool = Query(False, description="Включать ли в ответ полное описание модов."),
    dates: bool = Query(False, description="Включать ли в ответ даты создания и обновления модов."),
    general: bool = Query(True, description="Включать ли в ответ общую информацию о моде (название, размер, источник, кол-во скачиваний).")
):
    """
    Возвращает список модов с возможностью многочисленных опциональных фильтров и настрое.
    Не до конца провалидированные моды и не полностью публичные моды* в список не попадают.

    **Если идет фильтрация по пользователю и запрошены не только моды в каталоге, то будут возвращены моды с любой публичностью, но если запрашивающий
    пользователь не имеет доступа к конкретному моду, вместо словаря с информацией о нем, будет заглушка "Access denied (hide info)"*

    О сортировке:
    Префикс `i` указывает что сортировка должна быть инвертированной.
    По умолчанию от меньшего к большему, с `i` от большего к меньшему.
    1. NAME - сортировка по имени.
    2. SIZE - сортировка по размеру.
    3. CREATION_DATE - сортировка по дате создания.
    4. UPDATE_DATE - сортировка по дате обновления.
    5. REQUEST_DATE - сортировка по дате последнего запроса.
    6. SOURCE - сортировка по источнику.
    7. MOD_DOWNLOADS *(по умолчанию)* - сортировка по количеству загрузок.
    """
    tags = tools.str_to_list(tags)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)

    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})
    elif (len(tags) + len(primary_sources) + len(allowed_ids)) > 90:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 90 elements in sum",
                                     "error_id": 2})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod.id)
    if description:
        query = query.add_columns(catalog.Mod.description)
    if short_description:
        query = query.add_column(catalog.Mod.short_description)
    if dates:
        query = query.add_columns(catalog.Mod.date_update_file, catalog.Mod.date_creation)
    if general:
        query = query.add_columns(catalog.Mod.name, catalog.Mod.size, catalog.Mod.source, catalog.Mod.downloads)

    query = query.order_by(tools.sort_mods(sort))
    query = query.filter(catalog.Mod.condition == 0)
    only_publics = user_catalog or user == 0
    if only_publics:
        query = query.filter(catalog.Mod.public == 0)

    # Фильтрация по конкретным ID
    if len(allowed_ids) > 0:
        query = query.filter(catalog.Mod.id.in_(allowed_ids))

    # Фильтрация по играм
    if game > 0:
        query = query.filter(catalog.Mod.game == game)

    # Фильтрация по первоисточникам
    if len(primary_sources) > 0:
        query = query.filter(catalog.Mod.source.in_(primary_sources))

    if independents:
        query = query.outerjoin(catalog.mods_dependencies, catalog.Mod.id == catalog.mods_dependencies.c.mod_id).filter(
            catalog.mods_dependencies.c.mod_id == None)

    # Фильтрация по имени
    if len(name) > 0:
        print(len(name))
        query = query.filter(catalog.Mod.name.ilike(f'%{name}%'))

    # Фильтрация по тегам
    if len(tags) > 0:
        for tag in tags:
            query = query.filter(catalog.Mod.tags.any(catalog.Tag.id == tag))

    # Сортировка по пользователю
    if user > 0:
        query = query.join(account.mod_and_author, account.mod_and_author.c.mod_id == catalog.Mod.id)
        query = query.filter(account.mod_and_author.c.user_id == user)

        if user_owner in [0, 1]:
            query = query.filter(account.mod_and_author.c.owner == (user_owner == 0))


    mods_count = query.count()

    offset = page_size * page
    mods = query.offset(offset).limit(page_size).all()

    session.close()

    result_access_mods = []
    if not only_publics:
        result_access_mods = await tools.access_mods(response=response, request=request, mods_ids=[mod.id for mod in mods], check_mode=True)

    output_mods = []
    for mod in mods:
        def append_mod():
            out = {"id": mod.id}
            if description:
                out["description"] = mod.description
            if short_description:
                out["short_description"] = mod.short_description
            if dates:
                out["date_update_file"] = mod.date_update_file
                out["date_creation"] = mod.date_creation
            if general:
                out["name"] = mod.name
                out["size"] = mod.size
                out["source"] = mod.source
                out["downloads"] = mod.downloads

            output_mods.append(out)

        if only_publics:
            append_mod()
        else:
            if mod.id in result_access_mods:
                append_mod()
            else:
                output_mods.append("Access denied (hide info)")
                mods_count -= 1

    # Вывод результатов
    return {"database_size": mods_count, "offset": offset, "results": output_mods}


@router.get(MAIN_URL+"/info/mod/{mod_id}", tags=["Mod"])
async def info_mod(response: Response, request: Request, mod_id: int, dependencies: bool = None,
                   short_description: bool = None, description: bool = None, dates: bool = None,
                   general: bool = True, game: bool = None, authors: bool = None):
    """
    Тестовая функция
    """
    output = {}

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod.condition)
    if description:
        query = query.add_columns(catalog.Mod.description)
    if short_description:
        query = query.add_column(catalog.Mod.short_description)
    if dates:
        query = query.add_columns(catalog.Mod.date_update_file, catalog.Mod.date_creation, catalog.Mod.date_edit)
    if general:
        query = query.add_columns(catalog.Mod.name, catalog.Mod.size, catalog.Mod.source, catalog.Mod.downloads)
    if game:
        query = query.add_columns(catalog.Mod.game)

    query = query.add_columns(catalog.Mod.public)
    query = query.filter(catalog.Mod.id == mod_id)
    output["pre_result"] = query.first()

    if not output["pre_result"]:
        return JSONResponse(status_code=404, content="Mod not found.")

    if output["pre_result"].public >= 2:
        result_access = await tools.access_mods(response=response, request=request, mods_ids=mod_id, edit=False)
        if result_access != True:
            return result_access

    if dependencies:
        query = session.query(catalog.mods_dependencies.c.dependence)
        query = query.filter(catalog.mods_dependencies.c.mod_id == mod_id)

        count = query.count()
        result = query.limit(100).all()
        output["dependencies"] = [row[0] for row in result]
        output["dependencies_count"] = count

    if game:
        result = session.query(catalog.Game.name).filter_by(id=output["pre_result"].game).first()

        output["game"] = {"id": output["pre_result"].game, "name": result.name}

    # Закрытие сессии
    session.close()

    output["result"] = {"condition": output["pre_result"].condition}
    if description:
        output["result"]["description"] = output["pre_result"].description
    if short_description:
        output["result"]["short_description"] = output["pre_result"].short_description
    if dates:
        output["result"]["date_update_file"] = output["pre_result"].date_update_file
        output["result"]["date_edit"] = output["pre_result"].date_edit
        output["result"]["date_creation"] = output["pre_result"].date_creation
    if general:
        output["result"]["name"] = output["pre_result"].name
        output["result"]["size"] = output["pre_result"].size
        output["result"]["source"] = output["pre_result"].source
        output["result"]["downloads"] = output["pre_result"].downloads
        output["result"]["public"] = output["pre_result"].public
    if game:
        output["result"]["game"] = output["game"]
        del output["game"]
    del output["pre_result"]


    if authors:
        # Создание сессии
        session_account = sessionmaker(bind=account.engine)()

        # Исполнение
        row = session_account.query(account.mod_and_author).filter_by(mod_id=mod_id)
        row = row.limit(100)

        row_results = row.all()

        output["authors"] = []
        for i in row_results:
            output["authors"].append({"user": i.user_id, "owner": i.owner})

        session_account.close()

    statistics.update("mod", mod_id, "page_view")
    return JSONResponse(status_code=200, content=output)


@router.post(MAIN_URL+"/add/mod", tags=["Mod"])
async def add_mod(response: Response, request: Request, mod_id: int = -1, without_author: bool = False,
                  mod_name: str = Form(...), mod_short_description: str = Form(''), mod_description: str = Form(''),
                  mod_source: str = Form(...), mod_game: int = Form(...), mod_public: int = Form(...),
                  mod_file: UploadFile = File(...)):
    """
    Тестовая функция
    """
    access_result = await account.check_access(request=request, response=response)
    user_id = access_result.get("owner_id", -1)

    if access_result and user_id >= 0:
        print(mod_short_description)
        if len(re.sub(r'\s+', ' ', mod_short_description)) > 256:
            return JSONResponse(status_code=413, content="Короткое описание слишком длинное!")
        elif len(re.sub(r'\s+', ' ', mod_description)) > 10000:
            return JSONResponse(status_code=413, content="Описание слишком длинное!")
        elif len(mod_name) > 60:
            return JSONResponse(status_code=413, content="Название слишком длинное!")
        elif len(mod_name) < 1:
            return JSONResponse(status_code=411, content="Название слишком короткое!")
        elif not await tools.check_game_exists(mod_game):
            return JSONResponse(status_code=412, content="Такой игры не существует!")

        # Выполнение запроса
        session = sessionmaker(bind=account.engine)()
        user_req = session.query(account.Account).filter_by(id=user_id).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if mod_id > 0 or without_author:
                    return False
                elif user_req.mute_until and user_req.mute_until > datetime.now():
                    return False
                elif user_req.publish_mods:
                    return True
            return False

        if await mini():
            session.close()

            if mod_file.size >= 838860800:
                return JSONResponse(status_code=413, content="The file is too large.")

            Session = sessionmaker(bind=catalog.engine)

            session = Session()
            if mod_id > 0:
                if session.query(catalog.Mod).filter_by(id=mod_id).first():
                    return JSONResponse(status_code=412, content="Мод с таким ID уже существует!")
            session.close()

            real_mod_file = io.BytesIO(await mod_file.read())
            real_mod_file.name = mod_file.filename

            if mod_public not in [0, 1, 2]:
                mod_public = 0

            session = Session()
            # Create the insert statement
            insert_statement = insert(catalog.Mod)
            insert_statement = insert_statement.values(
                name=mod_name,
                short_description=mod_short_description,
                description=mod_description,
                size=mod_file.size,
                condition=1,
                public=mod_public,
                date_creation=datetime.now(),
                date_update_file=datetime.now(),
                date_edit=datetime.now(),
                source=mod_source,
                downloads=0,
                game=mod_game
            )

            # If mod_id is given, update the insert statement
            if mod_id > 0:
                insert_statement = insert_statement.values(id=mod_id)

            result = session.execute(insert_statement)
            id = result.lastrowid  # Получаем ID последней вставленной строки

            session.commit()

            # Указываем авторство, если пользователь не запросил обратного
            if not without_author:
                session = sessionmaker(bind=account.engine)()
                session.add(account.mod_and_author(mod_id=id, user_id=user_id, owner=True))
                session.commit()

            session.close()

            file_ext = mod_file.filename.split(".")[-1]
            result_upload = await tools.storage_file_upload(type="archive", path=f"mods/{id}/main.{file_ext}", file=real_mod_file)

            session = Session()
            if result_upload:
                session.query(catalog.Mod).filter_by(id=id).update({"condition": 0})
                session.query(catalog.Game).filter_by(id=mod_game).update({
                    catalog.Game.mod_count: func.coalesce(catalog.Game.mod_count, 0) + 1
                })
                session.commit()

                session.close()
                return JSONResponse(status_code=201, content=id)  # Возвращаем значение `id`
            else:
                session.query(catalog.Mod).filter_by(id=id).delete()
                session.commit()
                session.close()

                session = sessionmaker(bind=account.engine)()
                session.query(account.mod_and_author).filter_by(mod_id=id).delete()
                session.commit()
                session.close()

                return JSONResponse(status_code=500, content="Не удалось загрузить файл!")
        else:
            session.close()
            return JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

@router.post(MAIN_URL+"/edit/mod", tags=["Mod"])
async def edit_mod(response: Response, request: Request, mod_id: int, mod_name: str = Form(None),
                   mod_short_description: str = Form(None), mod_description: str = Form(None),
                   mod_source: str = Form(None), mod_game: int = Form(None), mod_public: int = Form(None),
                   mod_file: UploadFile = File(None)):
    """
    Тестовая функция
    """
    access_result = await tools.access_mods(response=response, request=request, mods_ids=mod_id, edit=True)
    if access_result == True:
        body = {}
        if mod_name is not None:
            if len(mod_name) > 60:
                return JSONResponse(status_code=413, content="Название слишком длинное!")
            elif len(mod_name) < 1:
                return JSONResponse(status_code=411, content="Название слишком короткое!")
            body["mod_name"] = mod_name
        if mod_short_description is not None:
            if len(re.sub(r'\s+', ' ', mod_short_description)) > 256:
                return JSONResponse(status_code=413, content="Короткое описание слишком длинное!")
            body["mod_short_description"] = mod_short_description
        if mod_description is not None:
            if len(re.sub(r'\s+', ' ', mod_description)) > 10000:
                return JSONResponse(status_code=413, content="Описание слишком длинное!")
            body["mod_description"] = mod_description
        if mod_source is not None:
            body["mod_source"] = mod_source
        if mod_game is not None:
            if not await tools.check_game_exists(mod_game):
                return JSONResponse(status_code=412, content="Такой игры не существует!")
            body["mod_game"] = mod_game
        if mod_public is not None:
            if mod_public in [0, 1, 2]:
                body["mod_public"] = mod_public

        if len(body) <= 0 and mod_file is None:
            return JSONResponse(status_code=411, content="Ничего не было изменено!")

        if len(body) > 0:
            body["date_edit"] = datetime.now()

        if mod_file:
            real_mod_file = io.BytesIO(await mod_file.read())
            real_mod_file.name = mod_file.filename
            url = f"mods/{mod_id}/main.{mod_file.filename.split('.')[-1]}"

            body["date_update_file"] = datetime.now()

            result_file_update = await tools.storage_file_upload(type="archive", path=url, file=real_mod_file)
            if not result_file_update:
                return JSONResponse(status_code=500, content="Не удалось обновить файл!")
                
        session = sessionmaker(bind=catalog.engine)()
        session.query(catalog.Mod).filter_by(id=mod_id).update(body)
        session.commit()
        session.close()
        return JSONResponse(status_code=201, content="OK")
    else:
        return access_result

@router.post(MAIN_URL+"/edit/mod/authors", tags=["Mod"])
async def edit_authors_mod(response: Response, request: Request, mod_id:int, mode:bool, author:int,
                           owner:bool = False):
    """
    Тестовая функция
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        req_user_id = access_result.get("owner_id", -1)
        user_req = session.query(account.Account).filter_by(id=req_user_id).first()
        user_add = session.query(account.Account).filter_by(id=author).first()

        async def mini():
            if not user_add:
                return False
            elif user_req.admin:
                return True
            else:
                if user_req.mute_until and user_req.mute_until > datetime.now():
                    return False

                in_mod = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=req_user_id).first()

                if in_mod:
                    if in_mod.owner:
                        if req_user_id == author and mode == False:
                            return False

                        return True
                    elif req_user_id == author and mode == False:
                        return True
                elif user_req.change_authorship_mods:
                    return True
            return False


        if await mini():
            if mode:
                has_owner = session.query(account.mod_and_author).filter_by(mod_id=mod_id, owner=True).first()
                if owner and has_owner:
                    session.query(account.mod_and_author).filter_by(mod_id=mod_id, owner=True).update({'owner': False})
                    session.commit()

                has_target = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=author).first()
                if has_target:
                    session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=author).update({'owner': owner})
                else:
                    insert_statement = insert(account.mod_and_author).values(
                        user_id=author,
                        owner=owner,
                        mod_id=mod_id
                    )
                    session.execute(insert_statement)
                session.commit()
            else:
                delete_member = account.mod_and_author.delete().where(account.mod_and_author.c.mod_id == mod_id,
                                                                      account.mod_and_author.c.user_id == author)
                # Выполнение операции DELETE
                session.execute(delete_member)
                session.commit()

            session.close()
            return JSONResponse(status_code=200, content="Выполнено")
        else:
            session.close()
            return JSONResponse(status_code=403, content="Операция заблокирована!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

@router.delete(MAIN_URL+"/delete/mod", tags=["Mod"])
async def delete_mod(response: Response, request: Request, mod_id: int):
    """
    Тестовая функция
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        # Выполнение запроса
        user_req = session.query(account.Account).filter_by(id=access_result.get("owner_id", -1)).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if user_req.mute_until and user_req.mute_until > datetime.now():
                    return False

                in_mod = session.query(account.mod_and_author).filter_by(mod_id=mod_id, user_id=access_result.get("owner_id", -1)).first()

                if in_mod:
                    if user_req.delete_self_mods and in_mod.owner:
                        return True
                elif user_req.delete_mods:
                    return True
            return False

        if await mini():
            session.close()
            
            resource_delete_result = await tools.delete_resources(owner_type="mods", owner_id=mod_id)
            if resource_delete_result and await tools.storage_file_delete(type="mod", path=f"mods/{mod_id}/main.zip"):
                session = Session()
                
                delete_mod = account.mod_and_author.delete().where(account.mod_and_author.c.mod_id == mod_id)
                session.execute(delete_mod)

                session.commit()
                session.close()

                session = sessionmaker(bind=catalog.engine)()

                session.query(catalog.Mod).filter_by(id=id).delete()
                session.query(catalog.mods_dependencies).filter_by(mod_id=id).delete()
                session.query(catalog.mods_tags).filter_by(mod_id=id).delete()

                session.commit()
                session.close()

                return JSONResponse(status_code=200, content="Удалено")
            else:
                session.close()
                return JSONResponse(status_code=500, content="Не удалось удалить мод!")
        else:
            session.close()
            return JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")
