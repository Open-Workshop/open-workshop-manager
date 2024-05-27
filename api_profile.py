from fastapi import APIRouter, Request, Response, Form, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, PlainTextResponse
from PIL import Image
from io import BytesIO
import bcrypt
import os
from ow_config import MAIN_URL
import datetime
import ow_config as config
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from sql_logic import sql_account as account

router = APIRouter()


@router.get(MAIN_URL + "/profile/info/{user_id}", tags=["Profile"])
async def info_profile(response: Response, request: Request, user_id: int, general: bool = True, rights: bool = False,
                       private: bool = False):
    """
    Возвращает информацию о пользователях.

    `general` - могут просматривать все.
    `rights` - исключительно админы и сам пользователь.
    `private` - исключительно админы и сам пользователь.
    """
    result = {}
    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    query = session.query(account.Account).filter_by(id=user_id)
    row = query.first()
    if not row:
        session.close()
        return JSONResponse(status_code=404, content="Пользователь не найден(")

    if rights or private:
        # Чекаем сессию юзера
        print(request.cookies.get("accessToken", ""))
        access_result = await account.check_access(request=request, response=response)

        # Смотрим действительна ли она (сессия)
        if access_result and access_result.get("owner_id", -1) >= 0:
            owner_id = access_result.get("owner_id", -1)  # id юзера запрашивающего данные

            if user_id != owner_id:  # Доп проверка если запрос делает не сам пользователь "про себя"
                query = session.query(account.Account.admin).filter_by(id=owner_id)
                owner_row = query.first()

                if not owner_row.admin:
                    session.close()
                    return JSONResponse(status_code=403, content="Вы не имеете доступа к этой информации!")

            if private:
                result["private"] = {}
                result["private"]["last_username_reset"] = row.last_username_reset
                result["private"]["last_password_reset"] = row.last_password_reset
                result["private"]["yandex"] = bool(row.yandex_id)
                result["private"]["google"] = bool(row.google_id)

            if rights:
                result["rights"] = {}
                result["rights"]["admin"] = row.admin
                result["rights"]["write_comments"] = row.write_comments
                result["rights"]["set_reactions"] = row.set_reactions
                result["rights"]["create_reactions"] = row.create_reactions
                result["rights"]["publish_mods"] = row.publish_mods
                result["rights"]["change_authorship_mods"] = row.change_authorship_mods
                result["rights"]["change_self_mods"] = row.change_self_mods
                result["rights"]["change_mods"] = row.change_mods
                result["rights"]["delete_self_mods"] = row.delete_self_mods
                result["rights"]["delete_mods"] = row.delete_mods
                result["rights"]["mute_users"] = row.mute_users
                result["rights"]["create_forums"] = row.create_forums
                result["rights"]["change_authorship_forums"] = row.change_authorship_forums
                result["rights"]["change_self_forums"] = row.change_self_forums
                result["rights"]["change_forums"] = row.change_forums
                result["rights"]["delete_self_forums"] = row.delete_self_forums
                result["rights"]["delete_forums"] = row.delete_forums
                result["rights"]["change_username"] = row.change_username
                result["rights"]["change_about"] = row.change_about
                result["rights"]["change_avatar"] = row.change_avatar
                result["rights"]["vote_for_reputation"] = row.vote_for_reputation
        else:
            session.close()
            return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

    if general:
        result["general"] = {}
        result["general"]["id"] = row.id
        result["general"]["username"] = row.username
        result["general"]["about"] = row.about
        result["general"]["avatar_url"] = row.avatar_url
        result["general"]["grade"] = row.grade
        result["general"]["comments"] = row.comments
        result["general"]["author_mods"] = row.author_mods
        result["general"]["registration_date"] = row.registration_date
        result["general"]["reputation"] = row.reputation
        result["general"][
            "mute"] = row.mute_until if row.mute_until and row.mute_until > datetime.datetime.now() else False  # есть ли мут, если да, то до какого времени действует

    session.close()
    return result

@router.get(MAIN_URL + "/profile/avatar/{user_id}", tags=["Profile"])
async def avatar_profile(user_id: int):
    """
    Возвращает url, по которому можно получить аватар пользователя при условии, что он есть.
    """
    session = sessionmaker(bind=account.engine)()

    avatar_url = session.query(account.Account.avatar_url).filter_by(id=user_id).first()

    session.close()

    if avatar_url:
        if avatar_url[0].startswith('local'):
            return RedirectResponse(url=f'{config.STORAGE_URL}/img/avatar/{user_id}.{avatar_url[0].split(".")[1]}')
        elif len(avatar_url[0]) > 0:
            return RedirectResponse(url=avatar_url[0])
        else:
            return PlainTextResponse(status_code=204, content="Avatar not set.")
    else:
        return PlainTextResponse(status_code=404, content="User not found!")


@router.post(MAIN_URL + "/profile/edit/{user_id}", tags=["Profile"])
async def edit_profile(response: Response, request: Request, user_id: int, username: str = Form(None),
                       about: str = Form(None), avatar: UploadFile = File(None), empty_avatar: bool = Form(None),
                       grade: str = Form(None), off_password: bool = Form(None), new_password: str = Form(None),
                       mute: datetime.datetime = Form(None)):
    """
    Редактирование пользователей *(самого себя или другого юзера)*.
    """
    try:
        global STANDART_STR_TIME

        access_result = await account.check_access(request=request, response=response)

        # Смотрим действительна ли она (сессия)
        if access_result and access_result.get("owner_id", -1) >= 0:
            owner_id = access_result.get("owner_id", -1)  # id юзера запрашивающего данные

            # Создание сессии
            session = sessionmaker(bind=account.engine)()

            # Получаем запись о юзере
            user_query = session.query(account.Account).filter_by(id=user_id)
            user = user_query.first()

            # Проверка, существует ли пользователь
            if not user:
                session.close()
                return JSONResponse(status_code=404, content="Пользователь не найден!")

            try:
                today = datetime.datetime.now()
                # Проверка, может ли просящий выполнить такую операцию
                query = session.query(account.Account).filter_by(id=owner_id)
                row = query.first()
                if owner_id != user_id:
                    if not row.admin:
                        # Перебираем все запрещенные поля и убеждаемся, что их изменить не пытаются
                        for i in [username, about, avatar, empty_avatar, grade, off_password, new_password]:
                            if i is not None:
                                session.close()
                                return JSONResponse(status_code=403, content="Доступ запрещен!")
                        else:
                            # Проверяем, есть ли у запрашивающего право мутить других пользователей и пытается ли он замутить
                            if not row.mute_users or mute is None:  # разрешено ли мутить, пытается ли замутить
                                session.close()
                                return JSONResponse(status_code=403, content="Доступ запрещен!")
                    elif new_password is not None or off_password is not None:
                        session.close()
                        return JSONResponse(status_code=403, content="Даже администраторы не могут менять пароли!")
                else:
                    if mute is not None:
                        session.close()
                        return JSONResponse(status_code=400, content="Нельзя замутить самого себя!")
                    elif not row.admin:  # Админы могут менять свои пароли и имена пользователей без ограничений
                        if row.mute_until and row.mute_until > today:  # Даже если админ замутен, то на него ограничение не распространяется
                            session.close()
                            return JSONResponse(status_code=425,
                                                content="Вам выдано временное ограничение на социальную активность :(")

                        if grade is not None:
                            session.close()
                            return JSONResponse(status_code=403, content="Не админ не может менять грейды!")

                        if new_password is not None and row.last_password_reset and row.last_password_reset + datetime.timedelta(
                                minutes=5) > today:
                            session.close()
                            return JSONResponse(status_code=425, content=(
                                        row.last_password_reset + datetime.timedelta(minutes=5)).strftime(
                                STANDART_STR_TIME))
                        if username is not None:
                            if not row.change_username:
                                session.close()
                                return JSONResponse(status_code=403,
                                                    content="Вам по какой-то причине запрещено менять никнейм!")
                            elif row.last_username_reset and (
                                    row.last_username_reset + datetime.timedelta(days=30)) > today:
                                session.close()
                                return JSONResponse(status_code=425, content=(
                                            row.last_username_reset + datetime.timedelta(days=30)).strftime(
                                    STANDART_STR_TIME))
                        if avatar is not None or empty_avatar is not None:
                            if not row.change_avatar:
                                session.close()
                                return JSONResponse(status_code=403,
                                                    content="Вам по какой-то причине запрещено менять аватар!")
                        if about is not None:
                            if not row.change_about:
                                session.close()
                                return JSONResponse(status_code=403,
                                                    content="Вам по какой-то причине запрещено менять \"обо мне\"!")
            except:
                session.close()
                return JSONResponse(status_code=500, content='Что-то пошло не так при проверке ваших прав...')

            # Подготавливаемся к выполнению операции и смотрим чтобы переданные данные были корректны
            query_update = {}

            try:
                try:
                    if username:
                        if len(username) < 2:
                            session.close()
                            return JSONResponse(status_code=411,
                                                content="Слишком короткий никнейм! (минимальная длина 2 символа)")
                        elif len(username) > 50:
                            session.close()
                            return JSONResponse(status_code=413,
                                                content="Слишком длинный никнейм! (максимальная длина 50 символов)")

                        query_update["username"] = username
                        query_update["last_username_reset"] = today
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (username) на обновление БД...')

                try:
                    if about:
                        if len(about) > 512:
                            session.close()
                            return JSONResponse(status_code=413,
                                                content="Слишком длинное поле \"обо мне\"! (максимальная длина 512 символов)")

                        query_update["about"] = about
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (about) на обновление БД...')

                try:
                    if grade:
                        if len(grade) < 2:
                            session.close()
                            return JSONResponse(status_code=411,
                                                content="Слишком короткий грейд! (минимальная длина 2 символа)")
                        elif len(grade) > 100:
                            session.close()
                            return JSONResponse(status_code=413,
                                                content="Слишком длинный грейд! (максимальная длина 100 символов)")

                        query_update["grade"] = grade
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (grade) на обновление БД...')

                try:
                    if off_password:
                        query_update["password_hash"] = None
                        query_update["last_password_reset"] = today
                    elif new_password:
                        if len(new_password) < 6:
                            session.close()
                            return JSONResponse(status_code=411,
                                                content="Слишком короткий пароль! (минимальная длина 6 символа)")
                        elif len(new_password) > 100:
                            session.close()
                            return JSONResponse(status_code=413,
                                                content="Слишком длинный пароль! (максимальная длина 100 символов)")

                        query_update["password_hash"] = (
                            bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt(9))).decode('utf-8')
                        query_update["last_password_reset"] = today
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (password) на обновление БД...')

                try:
                    if mute:
                        if mute < today:
                            session.close()
                            return JSONResponse(status_code=411, content="Указанная дата окончания мута уже прошла!")

                        query_update["mute_until"] = mute
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (mute) на обновление БД...')

                try:
                    if empty_avatar:
                        # TODO удаляем аватар на другом микросервисе

                        query_update["avatar_url"] = ""

                        image_avatar = f"accounts_avatars/{user_id}.jpeg"
                        if os.path.isfile(image_avatar):
                            os.remove(image_avatar)
                    elif avatar is not None:  # Проверка на аватар в самом конце, т.к. он приводит к изменениям в файловой системе
                        # TODO заменяем аватар на другом микросервисе

                        query_update["avatar_url"] = "local"

                        if avatar.size >= 2097152:
                            session.close()
                            return JSONResponse(status_code=413, content="Вес аватара не должен превышать 2 МБ.")

                        try:
                            im = Image.open(BytesIO(await avatar.read()))
                            if im.mode in ("RGBA", "P"):
                                im = im.convert("RGB")
                            im.save(f'accounts_avatars/{user_id}.jpeg', 'JPEG', quality=50)
                        except:
                            await avatar.close()
                            session.close()
                            return JSONResponse(status_code=500,
                                                content="Что-то пошло не так при обработке аватара ._.")
                except:
                    session.close()
                    return JSONResponse(status_code=500,
                                        content='Что-то пошло не так при подготовке данных (avatar) на обновление БД...')
            except:
                return JSONResponse(status_code=500,
                                    content='Что-то пошло не так при подготовке данных на обновление БД...')

            # Выполняем запрошенную операцию
            user_query.update(query_update)
            session.commit()
            session.close()

            # Возвращаем успешный результат
            return JSONResponse(status_code=202, content='Изменения приняты :)')
        else:
            return JSONResponse(status_code=403, content="Недействительный ключ сессии!")
    except:
        session.close()
        return JSONResponse(status_code=500, content='В огромной функции произошла неизвестная ошибка...')


@router.post(MAIN_URL + "/edit/profile/rights", tags=["Profile"])
async def edit_profile_rights(response: Response, request: Request, user_id: int, write_comments: bool = Form(None),
                              set_reactions: bool = Form(None), create_reactions: bool = Form(None),
                              mute_users: bool = Form(None), publish_mods: bool = Form(None),
                              change_authorship_mods: bool = Form(None), change_self_mods: bool = Form(None),
                              change_mods: bool = Form(None), delete_self_mods: bool = Form(None),
                              delete_mods: bool = Form(None), create_forums: bool = Form(None),
                              change_authorship_forums: bool = Form(None), change_self_forums: bool = Form(None),
                              change_forums: bool = Form(None), delete_self_forums: bool = Form(None),
                              delete_forums: bool = Form(None), change_username: bool = Form(None),
                              change_about: bool = Form(None), change_avatar: bool = Form(None),
                              vote_for_reputation: bool = Form(None)):
    """
    Функция для изменения прав пользователей
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:  # авторизован ли юзер в системе
        owner_id = access_result.get("owner_id", -1)  # id юзера запрашивающего изменения

        # Создание сессии
        USession = sessionmaker(bind=account.engine)
        session = USession()

        # Получаем запись о юзере
        user_query = session.query(account.Account).filter_by(id=user_id)
        user = user_query.first()

        # Проверка, существует ли пользователь
        if not user:
            session.close()
            return JSONResponse(status_code=404, content="Пользователь не найден!")

        # Проверка, может ли просящий выполнить такую операцию
        query = session.query(account.Account).filter_by(id=owner_id)
        row = query.first()
        if not row.admin:
            session.close()
            return JSONResponse(status_code=403, content="Только админ может менять права!")

        # Подготавливаемся к выполнению операции и смотрим чтобы переданные данные были корректны
        sample_query_update = {
            "write_comments": write_comments,
            "set_reactions": set_reactions,
            "create_reactions": create_reactions,
            "mute_users": mute_users,
            "publish_mods": publish_mods,
            "change_authorship_mods": change_authorship_mods,
            "change_self_mods": change_self_mods,
            "change_mods": change_mods,
            "delete_self_mods": delete_self_mods,
            "delete_mods": delete_mods,
            "create_forums": create_forums,
            "change_authorship_forums": change_authorship_forums,
            "change_self_forums": change_self_forums,
            "change_forums": change_forums,
            "delete_self_forums": delete_self_forums,
            "delete_forums": delete_forums,
            "change_username": change_username,
            "change_about": change_about,
            "change_avatar": change_avatar,
            "vote_for_reputation": vote_for_reputation
        }

        query_update = {}
        for key in sample_query_update.keys():
            if sample_query_update[key] is not None:
                query_update[key] = sample_query_update[key]

        # Выполняем запрошенную операцию
        user_query.update(query_update)
        session.commit()
        session.close()

        # Возвращаем успешный результат
        return JSONResponse(status_code=202, content='Изменения приняты :)')
    else:
        return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

@router.delete(MAIN_URL+"/profile/delete", tags=["Profile"])
async def delete_account(response: Response, request: Request):
    """
    Удаление аккаунта. Сделать это может только сам пользователь, при этом удаляются только персональные данные пользователя.
    Т.е. - аватар, никнейм, "обо мне", электронный адрес, ассоциация с сервисами авторизации, текста комментариев.
    "следы" такие, как история сессий, комментарии (сохраняется факт их наличия, содержимое удаляется) и т.п..
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        session = sessionmaker(bind=account.engine)()

        # Выполнение запроса
        user_id = access_result.get("owner_id", -1)


        # Заносим в базу (блокируем на 5 дней создание аккаунта с такими же вводными)
        row = session.query(account.Account).filter_by(id=user_id).first()
        insert_statement = insert(account.blocked_account_creation).values(
            yandex_id=row.yandex_id,
            google_id=row.google_id,

            forget=datetime.datetime.now()+datetime.timedelta(days=5)
        )

        # TODO удаляем связанный аватар на другом микросервисе

        # Выполнение операции INSERT
        session.execute(insert_statement)
        session.commit()

        session.query(account.Account).filter_by(id=user_id).update({
            "yandex_id": None,
            "google_id": None,
            "username": None,
            "about": None,
            "avatar_url": None,
            "grade": None,
            "password_hash": None
        })
        session.query(account.Session).filter_by(owner_id=user_id).update({
            "broken": "account deleted",
        })

        session.commit()
        session.close()

        return JSONResponse(status_code=200, content="Успешно!")
    else:
        return JSONResponse(status_code=403, content="Недействительный ключ сессии!")

