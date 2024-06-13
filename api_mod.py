from fastapi import APIRouter, Request, Response, Form, File, UploadFile
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


@router.get(MAIN_URL+"/download/{mod_id}")
async def download_mod(mod_id: int):
    statistics.update("mod_download", mod_id)
    return RedirectResponse(url=F'{config.STORAGE_URL}/download/archive/mods/{mod_id}/main.zip')

@router.get(MAIN_URL+"/list/mods/access/{ids_array}")
async def access_to_mods(response: Response, request: Request, ids_array, edit: bool = False,
                         user: int = -1, token: str = "none"):
    """
    Принимает массив ID модов, возвращает этот же массив в котором ID модов к которым есть read (или выше) доступ.

    Если edit = True, то фильтром выступает минимум edit доступ.

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

@router.get(MAIN_URL+"/list/mods/public/{ids_array}")
async def public_mods(ids_array, in_catalog:bool = False):
    """
    Возвращает список публичных модов на сервере.
    Принимает массив ID модов. Возвращает масссив id's модов.
    Ограничение на разовый запрос - 50 элементов.
    """
    ids_array = tools.str_to_list(ids_array)

    if len(ids_array) < 1 or len(ids_array) > 50:
        return JSONResponse(status_code=413, content={"message": "the size of the array is not correct", "error_id": 1})

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

@router.get(MAIN_URL+"/list/mods/")
async def mod_list(response: Response, request: Request, page_size: int = 10, page: int = 0, sort: str = "DOWNLOADS",
                   tags=[], game: int = -1, allowed_ids=[], independents: bool = False, primary_sources=[],
                   name: str = "", short_description: bool = False, description: bool = False, dates: bool = False,
                   general: bool = True, user: int = 0, user_owner: int = -1, user_catalog: bool = True):
    """
    Возвращает список модов к конкретной игре, которые есть на сервере. Не до конца провалидированные моды и не полностью публичные моды в список не попадают.

    1. `page_size` *(int)* - размер 1 страницы. Диапазон - 1...50 элементов.
    2. `page` *(int)* - номер странице. Не должна быть отрицательной.
    3. `short_description` *(bool)* - отправлять ли короткое описание мода в ответе. В длину оно максимум 256 символов. По умолчанию `False`.
    4. `description` *(bool)* - отправлять ли полное описание мода в ответе. По умолчанию `False`.
    5. `dates` *(bool)* - отправлять ли дату последнего обновления и дату создания в ответе. По умолчанию `False`.
    6. `general` *(bool)* - отправлять ли базовые поля *(название, размер, источник, количество загрузок)*. По умолчанию `True`.

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

    О фильтрации:
    1. `tags` - передать список тегов которые должен содержать мод *(по умолчанию пуст)* *(нужно передать ID тегов)*.
    2. `game` - ID игры за которой закреплен мод *(фильтр работает если `значение > 0`)*.
    3. `allowed_ids` - если передан хотя бы один элемент, идет выдача конкретно этих модов.
    4. `dependencies` *(bool)* - отфильтровывает моды у которых есть зависимости на другие моды.
    5. `primary_sources` - список допустимых первоисточников.
    6. `name` - поиск по имени. Например `name=Harmony` *(в отличии от передаваемых списков, тут скобки не нужны)*.
    Работает как проверка есть ли у мода в названии определенная последовательности символов.
    7. `user` *(int)* - если > 0, то фильтрует по конкретному переданному пользователю.
    8. `user_owner` *(int)* - учитывается, если фильтрация по user активна. Если 0 возвращает моды, где юзер "создатель".
    Если 1, то возвращает моды где юзре "соавтор". При других значениях (рекомендую -1) фильтрация по этому признаку не производится.
    9. `user_catalog` *(bool)* - если False, то возврашает все моды (требует запрос от имени запрашиваемого пользователя, либо права админа).
    Если True, возвращает моды с публичностью "в каталоге" (public == 0).
    """
    tags = tools.str_to_list(tags)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)

    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})
    elif (len(tags) + len(primary_sources) + len(allowed_ids)) > 30:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 30 elements in sum",
                                     "error_id": 2})

    if user > 0 and not user_catalog:
        access_result = await account.check_access(request=request, response=response)

        if not access_result or access_result.get("owner_id", -1) < 0:
            return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

        # Создание сессии
        user_session = sessionmaker(bind=account.engine)()

        if not user_catalog and user != access_result.get("owner_id", -1):
            # Выполнение запроса
            row = user_session.query(account.Account).filter_by(id=access_result.get("owner_id", -1))
            row_result = row.first()
            if not row_result or not row_result.admin:
                user_session.close()
                return JSONResponse(status_code=403, content="Вы не имеете доступа к этой информации!")
            user_session.close()

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

        if user_catalog:
            query = query.filter(catalog.Mod.public == 0)


    mods_count = query.count()

    offset = page_size * page
    mods = query.offset(offset).limit(page_size).all()

    session.close()

    output_mods = []
    for mod in mods:
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

    # Вывод результатов
    return {"database_size": mods_count, "offset": offset, "results": output_mods}

@router.get(MAIN_URL+"/list/tags/mods/{mods_ids_list}")
async def list_tags_for_mods(response: Response, request: Request, mods_ids_list, tags=[], only_ids: bool = False):
    """
    Возвращает ассоциации модов с тегами.
    Если в переданном списке модов есть ID непубличного мода, то будет отказано в доступе, делать такие запросы через микросервис account!

    1. `mods_ids_list` - список модов к которым нужно вернуть ассоциации (принимает список ID модов).
    2. `tags` - если не пуст возвращает ассоциации конкретно с этими тегами (принимает список ID тегов).
    3. `only_ids` - если True возвращает только ID ассоцируемых тегов, если False возвращает всю информацию о каждом ассоцируемом теге.
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    tags = tools.str_to_list(tags)

    if (len(mods_ids_list) + len(tags)) > 80:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 1})

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    query = session.query(catalog.Mod.id)
    query = query.filter(catalog.Mod.id.in_(mods_ids_list))

    if len(query.all()) > 0:
        result_access = await tools.access_mods(response=response, request=request, mods_ids=mods_ids_list)
        if result_access != True:
            return result_access

    # Выполнение запроса
    result = {}
    query_global = session.query(catalog.Tag).join(catalog.mods_tags)
    for mod_id in mods_ids_list:
        query = query_global.filter(catalog.mods_tags.c.mod_id == mod_id)
        if len(tags) > 0:
            query = query.filter(catalog.Tag.id.in_(tags))

        if only_ids:
            if result.get(mod_id, None) == None: result[mod_id] = []
            for id in query.all(): result[mod_id].append(id.id)
        else:
            result[mod_id] = query.all()

    return result


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

    statistics.update("mod_page_view", mod_id)
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
