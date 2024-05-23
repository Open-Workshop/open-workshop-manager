from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import JSONResponse
import tools
from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, delete
from ow_config import MAIN_URL


router = APIRouter()


@router.get("/list/tags/{game_id}")
async def list_tags(game_id: int, page_size: int = 10, page: int = 0, name: str = '', tags_ids = []):
    """
    Возвращает список тегов закрепленных за игрой и её модами. Нужно передать ID интересующей игры.

    1. `page_size` - размер 1 страницы. Диапазон - 1...50 элементов.
    2. `page` - номер странице. Не должна быть отрицательной.
    3. `name` - фильтрация по имени.
    4. `tags_ids` - фильтрация по id тегов *(массив id)*.
    """
    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})

    tags_ids = tools.str_to_list(tags_ids)

    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()
    # Выполнение запроса
    query = session.query(catalog.Tag)
    query = query.filter(catalog.Tag.associated_games.any(catalog.Game.id == game_id))
    if len(name) > 0:
        query = query.filter(catalog.Tag.name.ilike(f'%{name}%'))

    if len(tags_ids) > 0:
        query = query.filter(catalog.Tag.id.in_(tags_ids))

    tags_count = query.count()
    offset = page_size * page
    tags = query.offset(offset).limit(page_size).all()

    session.close()
    return {"database_size": tags_count, "offset": offset, "results": tags}

@router.get(MAIN_URL+"/list/tags/mods/{mods_ids_list}", tags=["Tag"])
async def list_tags_for_mods(response: Response, request: Request, mods_ids_list, tags=[], only_ids: bool = False):
    """
    Тестовая функция
    """
    mods_ids_list = tools.str_to_list(mods_ids_list)
    tags = tools.str_to_list(tags)

    if (len(mods_ids_list) + len(tags)) > 80:
        return JSONResponse(status_code=413,
                            content={"message": "the maximum complexity of filters is 80 elements in sum",
                                     "error_id": 1})

    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()

    query = session.query(catalog.Mod.id)
    query = query.filter(catalog.Mod.id.in_(mods_ids_list))

    result = query.all()

    l = []
    for i in result:
        if i.public >= 2:
            l.append(i)
    if len(l) > 0:
        access_result = await account.check_access(request=request, response=response)

        if access_result and access_result.get("owner_id", -1) >= 0:
            session.close()
            # Создание сессии
            session = sessionmaker(bind=account.engine)()

            row = session.query(account.Account.admin).filter_by(id=access_result.get("owner_id", -1)).first()

            rowT = session.query(account.mod_and_author).filter_by(user_id=access_result.get("owner_id", -1))
            rowT = rowT.filter(account.mod_and_author.c.mod_id.in_(l))

            if rowT.count() != len(l) and not row.admin:
                session.close()
                return JSONResponse(status_code=403, content="Доступ воспрещен!")
            session.close()
        else:
            session.close()
            return JSONResponse(status_code=401, content="Недействительный ключ сессии!")

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

    session.close()
    return result


@router.post(MAIN_URL+"/add/tag", tags=["Tag"])
async def add_tag(response: Response, request: Request, tag_name: str = Form(...)):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Tag).values(
            name=tag_name
        )

        result = session.execute(insert_statement)
        id = result.lastrowid  # Получаем ID последней вставленной строки

        session.commit()
        session.close()

        return JSONResponse(status_code=202, content=id)  # Возвращаем значение `id`
    else:
        return access_result

@router.post(MAIN_URL+"/edit/tag", tags=["Tag"])
async def edit_tag(response: Response, request: Request, tag_id: int, tag_name: str = Form(None)):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        tag = session.query(catalog.Tag).filter_by(id=tag_id)
        if not tag.first():
            return JSONResponse(status_code=404, content="The element does not exist.")

        # Подготавливаем данные
        data_edit = {}
        if tag_name:
            data_edit["name"] = tag_name

        if len(data_edit) <= 0:
            return JSONResponse(status_code=418, content="The request is empty")

        # Меняем данные в БД
        tag.update(data_edit)
        session.commit()
        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.delete(MAIN_URL+"/delete/tag", tags=["Tag"])
async def delete_tag(response: Response, request: Request, tag_id: int):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        delete_game = delete(catalog.Tag).where(catalog.Tag.id == tag_id)

        delete_mods_tags_association = catalog.mods_tags.delete().where(catalog.mods_tags.c.tag_id == tag_id)
        delete_game_tags_association = catalog.allowed_mods_tags.delete().where(catalog.allowed_mods_tags.c.tag_id == tag_id)

        # Выполнение операции DELETE
        session.execute(delete_game)
        session.execute(delete_mods_tags_association)
        session.execute(delete_game_tags_association)
        session.commit()
        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
