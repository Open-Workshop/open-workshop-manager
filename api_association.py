from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import JSONResponse
import tools
from ow_config import MAIN_URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert
from sql_logic import sql_catalog as catalog


router = APIRouter()


@router.post(MAIN_URL+"/association/game/genre", tags=["Association", "Game", "Genre"])
async def association_game_with_genre(
    response: Response, 
    request: Request, 
    game_id: int = Form(..., description="ID игры"),
    mode: bool = Form(..., description="Режим работы функции. True - добавление ассоциации. False - удаление ассоциации."),
    genre_id: int = Form(..., description="ID жанра")
):
    """
    Создание ассоциации между игрой и жанром.

    game_id (int) - ID игры
    mode (bool) - Режим работы функции. True - добавление ассоциации. False - удаление ассоциации.
    genre_id (int) - ID жанра
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        if mode:
            output = session.query(catalog.game_genres).filter_by(game_id=game_id, genre_id=genre_id).first()
            if output is None:
                insert_statement = insert(catalog.game_genres).values(game_id=game_id, genre_id=genre_id)
                session.execute(insert_statement)
                session.commit()
                session.close()
                return JSONResponse(status_code=202, content="Complite")
            else:
                session.close()
                return JSONResponse(status_code=409, content="The association is already present")
        else:
            delete_genre_association = catalog.game_genres.delete().where(catalog.game_genres.c.game_id == game_id,
                                                                          catalog.game_genres.c.genre_id == genre_id)

            # Выполнение операции DELETE
            session.execute(delete_genre_association)
            session.commit()
            session.close()
            return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.post(MAIN_URL+"/association/game/tag", tags=["Association", "Game", "Tag"])
async def association_game_with_tag(
    response: Response, 
    request: Request, 
    game_id: int = Form(..., description="ID игры"),
    mode: bool = Form(..., description="Режим работы функции. True - добавление ассоциации. False - удаление ассоциации."),
    tag_id: int = Form(..., description="ID тега")
):
    """
    Создание ассоциации между игрой и тегом.

    game_id (int) - ID игры
    mode (bool) - Режим работы функции. True - добавление ассоциации. False - удаление ассоциации.
    tag_id (int) - ID тега
    """
    access_result = await tools.access_admin(response=response, request=request)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        if mode:
            output = session.query(catalog.allowed_mods_tags).filter_by(game_id=game_id, tag_id=tag_id).first()
            if output is None:
                insert_statement = insert(catalog.allowed_mods_tags).values(game_id=game_id, tag_id=tag_id)
                session.execute(insert_statement)
                session.commit()
                session.close()
                return JSONResponse(status_code=202, content="Complite")
            else:
                session.close()
                return JSONResponse(status_code=409, content="The association is already present")
        else:
            delete_tags_association = catalog.allowed_mods_tags.delete().where(catalog.allowed_mods_tags.c.game_id == game_id,
                                                                               catalog.allowed_mods_tags.c.tag_id == tag_id)

            # Выполнение операции DELETE
            session.execute(delete_tags_association)
            session.commit()
            session.close()
            return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.post(MAIN_URL+"/association/mod/tag", tags=["Association", "Mod", "Tag"])
async def association_mod_with_tag(
    response: Response, 
    request: Request, 
    mod_id: int = Form(..., description="ID мода"),
    mode: bool = Form(..., description="Режим работы функции. True - добавление ассоциации. False - удаление ассоциации."),
    tag_id: int = Form(..., description="ID тега")
):
    """
    Создание ассоциации между модом и тегом.

    mod_id (int) - ID мода
    mode (bool) - Режим работы функции. True - добавление ассоциации. False - удаление ассоциации.
    tag_id (int) - ID тега
    """
    access_result = await tools.access_mods(response=response, request=request, mods_ids=mod_id)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        if mode:
            output = session.query(catalog.mods_tags).filter_by(mod_id=mod_id, tag_id=tag_id).first()
            if output is None:
                insert_statement = insert(catalog.mods_tags).values(mod_id=mod_id, tag_id=tag_id)
                session.execute(insert_statement)
                session.commit()
                session.close()
                return JSONResponse(status_code=202, content="Complite")
            else:
                session.close()
                return JSONResponse(status_code=409, content="The association is already present")
        else:
            delete_tags_association = catalog.mods_tags.delete().where(catalog.mods_tags.c.mod_id == mod_id,
                                                                       catalog.mods_tags.c.tag_id == tag_id)

            # Выполнение операции DELETE
            session.execute(delete_tags_association)
            session.commit()
            session.close()
            return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result

@router.post(MAIN_URL+"/association/mod/dependencie", tags=["Association", "Mod"])
async def association_mod_with_dependencie(
    response: Response, 
    request: Request, 
    mod_id: int = Form(..., description="ID мода"),
    mode: bool = Form(..., description="Режим работы функции. True - добавление ассоциации. False - удаление ассоциации."),
    dependencie: int = Form(..., description="ID зависимости (мода)")
):
    """
    Создание ассоциации между модом и зависимостью.

    mod_id (int) - ID мода
    mode (bool) - Режим работы функции. True - добавление ассоциации. False - удаление ассоциации.
    dependencie (int) - ID зависимости (мода)
    """
    access_result = await tools.access_mods(response=response, request=request, mods_ids=mod_id)

    if access_result == True:
        session = sessionmaker(bind=catalog.engine)()

        if mode:
            output = session.query(catalog.mods_dependencies).filter_by(mod_id=mod_id, dependence=dependencie).first()
            if output is None:
                insert_statement = insert(catalog.mods_dependencies).values(mod_id=mod_id, dependence=dependencie)
                session.execute(insert_statement)
                session.commit()
                session.close()
                return JSONResponse(status_code=202, content="Complite")
            else:
                session.close()
                return JSONResponse(status_code=409, content="The association is already present")
        else:
            delete_dependence_association = catalog.mods_dependencies.delete().where(
                catalog.mods_dependencies.c.mod_id == mod_id,
                catalog.mods_dependencies.c.dependence == dependencie)

            # Выполнение операции DELETE
            session.execute(delete_dependence_association)
            session.commit()
            session.close()
            return JSONResponse(status_code=202, content="Complite")
    else:
        return access_result
