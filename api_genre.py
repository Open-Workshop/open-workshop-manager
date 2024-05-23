from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import JSONResponse
import tools
from ow_config import MAIN_URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, delete
from sql_logic import sql_catalog as catalog


router = APIRouter()


@router.get(MAIN_URL+"/list/genres", tags=["Genre"])
async def list_genres(page_size: int = 10, page: int = 0, name: str = ''):
    """
    Возвращает список жанров для игр.

    1. `page_size` - размер 1 страницы. Диапазон - 1...50 элементов.
    2. `page` - номер странице. Не должна быть отрицательной.
    """
    if page_size > 50 or page_size < 1:
        return JSONResponse(status_code=413, content={"message": "incorrect page size", "error_id": 1})

    # Создание сессии
    Session = sessionmaker(bind=catalog.engine)
    session = Session()
    # Выполнение запроса
    query = session.query(catalog.Genre)
    if len(name) > 0:
        query = query.filter(catalog.Genre.name.ilike(f'%{name}%'))

    genres_count = query.count()
    offset = page_size * page
    genres = query.offset(offset).limit(page_size).all()

    session.close()
    return {"database_size": genres_count, "offset": offset, "results": genres}

@router.post(MAIN_URL+"/add/genre", tags=["Genre"])
async def add_genre(response: Response, request: Request, genre_name: str = Form(...)):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        insert_statement = insert(catalog.Genre).values(
            name=genre_name
        )

        result = session.execute(insert_statement)
        id = result.lastrowid  # Получаем ID последней вставленной строки

        session.commit()
        session.close()

        return JSONResponse(status_code=202, content=id)  # Возвращаем значение `id`
    else:
        return access_result

@router.post(MAIN_URL+"/edit/genre", tags=["Genre"])
async def edit_genre(response: Response, request: Request, genre_id: int, genre_name: str = Form(None)):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        genre = session.query(catalog.Genre).filter_by(id=genre_id)
        if genre.first():
            return JSONResponse(status_code=404, content="The element does not exist.")

        # Подготавливаем данные
        data_edit = {}
        if genre_name:
            data_edit["name"] = genre_name

        if len(data_edit) <= 0:
            return JSONResponse(status_code=418, content="The request is empty")

        # Меняем данные в БД
        genre = session.query(catalog.Genre).filter_by(id=genre_id)
        genre.update(data_edit)
        session.commit()
        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.delete(MAIN_URL+"/delete/genre", tags=["Genre"])
async def delete_genre(response: Response, request: Request, genre_id: int):
    """
    Тестовая функция
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        delete_game = delete(catalog.Genre).where(catalog.Genre.id == genre_id)

        delete_genres_association = catalog.game_genres.delete().where(catalog.game_genres.c.genre_id == genre_id)

        # Выполнение операции DELETE
        session.execute(delete_game)
        session.execute(delete_genres_association)
        session.commit()
        session.close()
        return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
