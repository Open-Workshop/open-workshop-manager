from fastapi import APIRouter, Request, Response, Form, Query, Path
from fastapi.responses import JSONResponse
import tools
from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, delete
from ow_config import MAIN_URL


router = APIRouter()


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
