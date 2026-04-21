from fastapi import APIRouter, Request, Response, Form, Query, Path
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
import logging
import bcrypt
from open_workshop_manager import tools
from open_workshop_manager.settings import MAIN_URL
import datetime
from open_workshop_manager import settings as config
import uuid
from urllib.parse import quote
from open_workshop_manager.limits import LIMITS
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager import standarts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    MAIN_URL + "/profiles/{user_id}",
    tags=["Profile"],
    summary="Информация о профиле",
    status_code=200,
    responses={
        200: {
            "description": "Возвращает информацию о профиле по запрошенным разделам."
        },
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        404: {"description": "Профиль не найден."},
    },
)
async def info_profile(
    response: Response,
    request: Request,
    user_id: int = Path(description="ID запрашивающего профиля."),
    general: bool = Query(True, description="Вернуть ли общую информацию."),
    rights: bool = Query(
        False,
        description="Вернуть ли права пользователя *(должен быть владельцем аккаунта или админом)*.",
    ),
    private: bool = Query(
        False,
        description="Вернуть ли скрытую информацию *(должен быть владельцем аккаунта или админом)*.",
    ),
):
    result: dict[str, dict[str, object]] = {}
    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    query = session.query(account.Account).filter_by(id=user_id)
    row = query.first()
    if not row:
        session.close()
        raise standarts.NotFoundError(
            detail="Пользователь не найден(",
            instance=str(request.url),
        )

    if rights or private:
        # Чекаем сессию юзера
        logger.debug(
            "Access token cookie present=%s",
            bool(request.cookies.get("accessToken")),
        )
        access_result = await account.check_access(request=request, response=response)

        # Смотрим действительна ли она (сессия)
        if access_result and access_result.get("owner_id", -1) >= 0:
            owner_id = access_result.get(
                "owner_id", -1
            )  # id юзера запрашивающего данные

            if (
                user_id != owner_id
            ):  # Доп проверка если запрос делает не сам пользователь "про себя"
                query = session.query(account.Account.admin).filter_by(id=owner_id)
                owner_row = query.first()

                if not owner_row.admin:
                    session.close()
                    raise standarts.ForbiddenError(
                        detail="Вы не имеете доступа к этой информации!",
                        instance=str(request.url),
                    )

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
                result["rights"][
                    "change_authorship_forums"
                ] = row.change_authorship_forums
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
            raise standarts.UnauthorizedError(instance=str(request.url))

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
        result["general"]["mute"] = (
            row.mute_until
            if row.mute_until and row.mute_until > datetime.datetime.now()
            else False
        )  # есть ли мут, если да, то до какого времени действует

    session.close()
    return result


@router.get(
    MAIN_URL + "/profiles/{user_id}/avatar",
    tags=["Profile"],
    summary="Аватар профиля",
    status_code=307,
    responses={
        207: {"description": "Пользователь не назначил аватар."},
        307: {"description": "Перенаправляет на аватар*(файл)* пользователя."},
        404: {"description": "Пользователь не найден."},
    },
)
async def avatar_profile(
    user_id: int = Path(description="ID профиля."),
):
    """
    Возвращает url, по которому можно получить аватар пользователя при условии, что он есть.
    """
    session = sessionmaker(bind=account.engine)()

    avatar_url = session.query(account.Account.avatar_url).filter_by(id=user_id).first()

    session.close()

    if avatar_url:
        if avatar_url[0].startswith("local"):
            return RedirectResponse(
                url=f'{config.STORAGE_URL}/download/avatar/{user_id}.{avatar_url[0].split(".")[1]}'
            )
        elif len(avatar_url[0]) > 0:
            return RedirectResponse(url=avatar_url[0])
        else:
            return PlainTextResponse(status_code=204, content="Avatar not set.")
    else:
        raise standarts.NotFoundError(
            detail="User not found!",
            instance=str(request.url),
        )


@router.post(
    MAIN_URL + "/profiles/{user_id}/avatar/upload",
    tags=["Profile"],
    summary="Инициализация загрузки аватара (файл напрямую на Storage)",
    status_code=307,
    responses={
        200: {"description": "JSON с transfer_url/ws_url для прямой загрузки"},
        307: {"description": "Redirect на Storage transfer/upload"},
        403: standarts.responses["non-admin"][403],
        404: {"description": "Пользователь не найден."},
        425: {"description": "Временное ограничение социальной активности."},
        500: {"description": "Не настроен JWT секрет."},
    },
)
async def init_avatar_upload(
    response: Response,
    request: Request,
    user_id: int = Path(description="ID профиля."),
):
    access_result = await account.check_access(request=request, response=response)
    if not access_result or access_result.get("owner_id", -1) < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))
    owner_id = access_result.get("owner_id", -1)

    session = sessionmaker(bind=account.engine)()
    user = session.query(account.Account).filter_by(id=user_id).first()
    if not user:
        session.close()
        raise standarts.NotFoundError(
            detail="Пользователь не найден!",
            instance=str(request.url),
        )

    owner = session.query(account.Account).filter_by(id=owner_id).first()
    if not owner:
        session.close()
        raise standarts.ForbiddenError(
            detail="Доступ запрещен!",
            instance=str(request.url),
        )

    now = datetime.datetime.now()
    if owner_id != user_id:
        if not owner.admin:
            session.close()
            raise standarts.ForbiddenError(
                detail="Доступ запрещен!",
                instance=str(request.url),
            )
    elif not owner.admin:
        if owner.mute_until and owner.mute_until > now:
            session.close()
            raise standarts.TooEarlyError(
                detail="Вам выдано временное ограничение на социальную активность :(",
                instance=str(request.url),
            )
        if not owner.change_avatar:
            session.close()
            raise standarts.ForbiddenError(
                detail="Вам по какой-то причине запрещено менять аватар!",
                instance=str(request.url),
            )
    session.close()

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900

    payload = {
        "job_id": job_id,
        "transfer_kind": "img",
        "storage_type": "avatar",
        "file_kind": "img",
        "max_bytes": LIMITS.profile.avatar_max_bytes,
        "callback_action": "avatar_set",
        "callback_context": {"user_id": user_id},
        "target_path": f"{user_id}.webp",
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    transfer_url = f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept", "") or "")
    )
    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "user_id": user_id,
                "transfer_url": transfer_url,
                "ws_url": f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}",
            },
        )

    out = RedirectResponse(url=transfer_url, status_code=307)
    out.headers["X-Upload-Job"] = job_id
    out.headers["X-Progress-WS"] = f"{config.STORAGE_URL}/transfer/ws/{job_id}"
    return out


@router.patch(
    MAIN_URL + "/profiles/{user_id}",
    tags=["Profile"],
    summary="Редактирование профиля",
    status_code=202,
    responses={
        202: {"description": "Профиль успешно отредактирован."},
        400: {"description": "Нельзя замутить самого себя."},
        403: standarts.responses["non-admin"][403],
        404: {"description": "Пользователь не найден."},
        411: {
            "description": "Недостигнута длина *(слишком короткий никнейм/грейд/пароль)*, либо указанная дата мута уже прошла."
        },
        413: {"desctiption": "Превышена длина *(никнейм/обо мне/грейд/пароль)*."},
        425: {
            "description": "Отказано в изменении, т.к. запрашивающий в муте *(узнать о длине мута можно в GET /profiles/{user_id})*, либо слишком часто меняется пароль/никнейм *(в таком случае в теле ответа возвращается дата снятия ограничения)*"
        },
        500: {
            "description": "Неизвестная ошибка при подготовке изменений *(детали в теле ответа)*."
        },
        523: {"description": "Ошибка на стороне файлового сервера."},
    },
)
async def edit_profile(
    response: Response,
    request: Request,
    user_id: int = Path(description="ID профиля."),
    username: str | None = Form(
        None,
        description="Новое имя пользователя.",
        min_length=LIMITS.profile.username_min_form,
        max_length=LIMITS.profile.username_max,
    ),
    about: str | None = Form(
        None, description="Новое описание профиля.", max_length=LIMITS.profile.about_max
    ),
    empty_avatar: bool | None = Form(
        None, description="Удалить аватар профиля *(приоритетней установки аватара)*."
    ),
    grade: str | None = Form(
        None,
        description="Новое звание пользователя *(назначается только админами)*.",
        min_length=LIMITS.profile.grade_min_form,
        max_length=LIMITS.profile.grade_max,
    ),
    off_password: bool | None = Form(
        None, description="Отключить пароль *(приоритетней установки пароля)*."
    ),
    new_password: str | None = Form(
        None,
        description="Новый пароль.",
        min_length=LIMITS.profile.password_min,
        max_length=LIMITS.profile.password_max,
    ),
    mute: datetime.datetime | None = Form(
        None,
        description="Время мута *(может быть назначен только админом и не самому себе)*, *(время не должно быть прошедшим)*.",
    ),
):
    """
    Редактирование пользователей *(самого себя или другого юзера)*.
    """
    access_result = await account.check_access(request=request, response=response)

    # Смотрим действительна ли она (сессия)
    if not access_result or access_result.get("owner_id", -1) < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    owner_id = access_result.get("owner_id", -1)  # id юзера запрашивающего данные

    # Создание сессии
    session = sessionmaker(bind=account.engine)()

    # Получаем запись о юзере
    user_query = session.query(account.Account).filter_by(id=user_id)
    user = user_query.first()

    # Проверка, существует ли пользователь
    if not user:
        session.close()
        raise standarts.NotFoundError(
            detail="Пользователь не найден!",
            instance=str(request.url),
        )

    today = datetime.datetime.now()
    # Проверка, может ли просящий выполнить такую операцию
    query = session.query(account.Account).filter_by(id=owner_id)
    row = query.first()

    if owner_id != user_id:
        if not row.admin:
            # Перебираем все запрещенные поля и убеждаемся, что их изменить не пытаются
            for i in [
                username,
                about,
                empty_avatar,
                grade,
                off_password,
                new_password,
            ]:
                if i is not None:
                    session.close()
                    raise standarts.ForbiddenError(
                        detail="Доступ запрещен!",
                        instance=str(request.url),
                    )
            else:
                # Проверяем, есть ли у запрашивающего право мутить других пользователей и пытается ли он замутить
                if (
                    not row.mute_users or mute is None
                ):  # разрешено ли мутить, пытается ли замутить
                    session.close()
                    raise standarts.ForbiddenError(
                        detail="Доступ запрещен!",
                        instance=str(request.url),
                    )
        elif new_password is not None or off_password is not None:
            session.close()
            raise standarts.ForbiddenError(
                detail="Даже администраторы не могут менять пароли!",
                instance=str(request.url),
            )
    else:
        if mute is not None:
            session.close()
            raise standarts.BadRequestError(
                detail="Нельзя замутить самого себя!",
                instance=str(request.url),
            )
        elif (
            not row.admin
        ):  # Админы могут менять свои пароли и имена пользователей без ограничений
            if (
                row.mute_until and row.mute_until > today
            ):  # Даже если админ замутен, то на него ограничение не распространяется
                session.close()
                raise standarts.TooEarlyError(
                    detail="Вам выдано временное ограничение на социальную активность :(",
                    instance=str(request.url),
                )

            if grade is not None:
                session.close()
                raise standarts.ForbiddenError(
                    detail="Не админ не может менять грейды!",
                    instance=str(request.url),
                )

            if (
                new_password is not None
                and row.last_password_reset
                and row.last_password_reset + datetime.timedelta(minutes=5) > today
            ):
                session.close()
                raise standarts.TooEarlyError(
                    detail=(
                        row.last_password_reset + datetime.timedelta(minutes=5)
                    ).strftime(account.STANDART_STR_TIME),
                    instance=str(request.url),
                )
            if username is not None:
                if not row.change_username:
                    session.close()
                    raise standarts.ForbiddenError(
                        detail="Вам по какой-то причине запрещено менять никнейм!",
                        instance=str(request.url),
                    )
                elif (
                    row.last_username_reset
                    and (row.last_username_reset + datetime.timedelta(days=30)) > today
                ):
                    session.close()
                    raise standarts.TooEarlyError(
                        detail=(
                            row.last_username_reset + datetime.timedelta(days=30)
                        ).strftime(account.STANDART_STR_TIME),
                        instance=str(request.url),
                    )
            if empty_avatar is not None:
                if not row.change_avatar:
                    session.close()
                    raise standarts.ForbiddenError(
                        detail="Вам по какой-то причине запрещено менять аватар!",
                        instance=str(request.url),
                    )
            if about is not None:
                if not row.change_about:
                    session.close()
                    raise standarts.ForbiddenError(
                        detail='Вам по какой-то причине запрещено менять "обо мне"!',
                        instance=str(request.url),
                    )

    # Подготавливаемся к выполнению операции и смотрим чтобы переданные данные были корректны
    query_update: dict[str, object] = {}

    if username:
        if len(username) < LIMITS.profile.username_min:
            session.close()
            raise standarts.PreconditionRequiredError(
                detail="Слишком короткий никнейм! (минимальная длина 2 символа)",
                instance=str(request.url),
            )
        elif len(username) > LIMITS.profile.username_max:
            session.close()
            raise standarts.PayloadTooLargeError(
                detail="Слишком длинный никнейм! (максимальная длина 50 символов)",
                instance=str(request.url),
            )
        else:
            # Ensure username uniqueness
            existing_username = (
                session.query(account.Account.id)
                .filter(
                    account.Account.username == username,
                    account.Account.id != user_id,
                )
                .first()
            )
            if existing_username:
                session.close()
                raise standarts.ConflictError(
                    detail="Этот никнейм уже занят!",
                    instance=str(request.url),
                )

        query_update["username"] = username
        query_update["last_username_reset"] = today

    if about:
        if len(about) > LIMITS.profile.about_max:
            session.close()
            raise standarts.PayloadTooLargeError(
                detail='Слишком длинное поле "обо мне"! (максимальная длина 512 символов)',
                instance=str(request.url),
            )

        query_update["about"] = about

    if grade:
        if len(grade) < LIMITS.profile.grade_min:
            session.close()
            raise standarts.PreconditionRequiredError(
                detail="Слишком короткий грейд! (минимальная длина 2 символа)",
                instance=str(request.url),
            )
        elif len(grade) > LIMITS.profile.grade_max:
            session.close()
            raise standarts.PayloadTooLargeError(
                detail="Слишком длинный грейд! (максимальная длина 100 символов)",
                instance=str(request.url),
            )

        query_update["grade"] = grade

    if off_password:
        query_update["password_hash"] = None
        query_update["last_password_reset"] = today
    elif new_password:
        if len(new_password) < LIMITS.profile.password_min:
            session.close()
            raise standarts.PreconditionRequiredError(
                detail="Слишком короткий пароль! (минимальная длина 6 символа)",
                instance=str(request.url),
            )
        elif len(new_password) > LIMITS.profile.password_max:
            session.close()
            raise standarts.PayloadTooLargeError(
                detail="Слишком длинный пароль! (максимальная длина 100 символов)",
                instance=str(request.url),
            )

        query_update["password_hash"] = (
            bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(9))
        ).decode("utf-8")
        query_update["last_password_reset"] = today

    if mute:
        if mute < today:
            session.close()
            raise standarts.PreconditionRequiredError(
                detail="Указанная дата окончания мута уже прошла!",
                instance=str(request.url),
            )

        query_update["mute_until"] = mute

    if empty_avatar:
        query_update["avatar_url"] = ""

        avatar_url = str(user.avatar_url)

        if avatar_url.startswith("local"):
            format_name = avatar_url.split(".")[1]
            if not await tools.storage_file_delete(
                type="avatar", path=f"{user.id}.{format_name}"
            ):
                session.close()
                raise standarts.AvatarDeletionFailedError(
                    detail="Что-то пошло не так при удалении аватара из системы.",
                    instance=str(request.url),
                )

    # Выполняем запрошенную операцию
    user_query.update(query_update)
    session.commit()
    session.close()

    # Возвращаем успешный результат
    return PlainTextResponse(status_code=202, content="Изменения приняты :)")


@router.patch(
    MAIN_URL + "/profiles/{user_id}/rights",
    tags=["Profile"],
    summary="Редактирование прав профиля",
    status_code=202,
    responses={
        202: {"description": "Изменения приняты."},
        401: standarts.responses[401],
        403: standarts.responses["admin"][403],
        404: {"description": "Профиль не найден."},
    },
)
async def edit_profile_rights(
    response: Response,
    request: Request,
    user_id: int = Path(description="ID профиля."),
    write_comments: bool = Form(None, description="Разрешено ли писать комментарии."),
    set_reactions: bool = Form(None, description="Разрешено ли устанавливать реакции."),
    create_reactions: bool = Form(None, description="Разрешено ли создавать реакции."),
    mute_users: bool = Form(None, description="Разрешено ли мутить юзеров."),
    publish_mods: bool = Form(None, description="Разрешено ли публиковать моды."),
    change_authorship_mods: bool = Form(
        None, description="Разрешено ли менять авторство модов *(чужих)*."
    ),
    change_self_mods: bool = Form(None, description="Разрешено ли менять свои моды."),
    change_mods: bool = Form(None, description="Разрешено ли менять чужие моды."),
    delete_self_mods: bool = Form(None, description="Разрешено ли удалять свои моды."),
    delete_mods: bool = Form(None, description="Разрешено ли удалять чужие моды."),
    create_forums: bool = Form(None, description="Разрешено ли создавать форумы."),
    change_authorship_forums: bool = Form(
        None, description="Разрешено ли менять авторство форумов *(чужих)*."
    ),
    change_self_forums: bool = Form(
        None, description="Разрешено ли менять свои форумы."
    ),
    change_forums: bool = Form(None, description="Разрешено ли менять чужие форумы."),
    delete_self_forums: bool = Form(
        None, description="Разрешено ли удалять свои форумы."
    ),
    delete_forums: bool = Form(None, description="Разрешено ли удалять чужие форумы."),
    change_username: bool = Form(None, description="Разрешено ли менять юзернейм."),
    change_about: bool = Form(None, description='Разрешено ли менять о "обо мне".'),
    change_avatar: bool = Form(None, description="Разрешено ли менять аватар."),
    vote_for_reputation: bool = Form(
        None, description="Разрешено ли голосовать за репутацию модов и форумов."
    ),
):
    """
    Изменять права может только администратор.
    """
    access_result = await account.check_access(request=request, response=response)

    if (
        access_result and access_result.get("owner_id", -1) >= 0
    ):  # авторизован ли юзер в системе
        owner_id = access_result.get(
            "owner_id", -1
        )  # id юзера запрашивающего изменения

        # Создание сессии
        USession = sessionmaker(bind=account.engine)
        session = USession()

        # Получаем запись о юзере
        user_query = session.query(account.Account).filter_by(id=user_id)
        user = user_query.first()

        # Проверка, существует ли пользователь
        if not user:
            session.close()
            raise standarts.NotFoundError(
                detail="Пользователь не найден!",
                instance=str(request.url),
            )

        # Проверка, может ли просящий выполнить такую операцию
        query = session.query(account.Account).filter_by(id=owner_id)
        row = query.first()
        if not row.admin:
            session.close()
            raise standarts.ForbiddenError(
                detail="Только админ может менять права!",
                instance=str(request.url),
            )

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
            "vote_for_reputation": vote_for_reputation,
        }

        query_update: dict[str, object] = {}
        for key in sample_query_update.keys():
            if sample_query_update[key] is not None:
                query_update[key] = sample_query_update[key]

        # Выполняем запрошенную операцию
        user_query.update(query_update)
        session.commit()
        session.close()

        # Возвращаем успешный результат
        return PlainTextResponse(status_code=202, content="Изменения приняты :)")
    else:
        raise standarts.UnauthorizedError(instance=str(request.url))


@router.delete(
    MAIN_URL + "/profiles/{user_id}",
    tags=["Profile"],
    summary="Удаление аккаунта",
    status_code=200,
    responses={
        200: {"description": "Удален успешно."},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        523: {
            "description": "Не удалось удалить аватар пользователя *(удаление прервано)*."
        },
    },
)
async def delete_account(
    response: Response,
    request: Request,
    user_id: int = Path(description="ID профиля для удаления."),
):
    """
    Удаление аккаунта. Сделать это может только сам пользователь, при этом удаляются только персональные данные пользователя.
    Т.е. - аватар, никнейм, "обо мне", электронный адрес, ассоциация с сервисами авторизации, текста комментариев.
    "следы" такие, как история сессий, комментарии (сохраняется факт их наличия, содержимое удаляется) и т.п..
    """
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        if user_id is not None and user_id != access_result.get("owner_id", -1):
            raise standarts.ForbiddenError(
                detail="Вы не можете удалить этот аккаунт!",
                instance=str(request.url),
            )
        # Создание сессии
        session = sessionmaker(bind=account.engine)()

        # Выполнение запроса
        user_id = access_result.get("owner_id", -1)

        # Заносим в базу (блокируем на 5 дней создание аккаунта с такими же вводными)
        row = session.query(account.Account).filter_by(id=user_id).first()
        insert_statement = insert(account.blocked_account_creation).values(
            yandex_id=row.yandex_id,
            google_id=row.google_id,
            forget=datetime.datetime.now() + datetime.timedelta(days=5),
        )

        avatar_url = str(row.avatar_url)

        if avatar_url.startswith("local"):
            format_name = avatar_url.split(".")[1]
            if not await tools.storage_file_delete(
                type="avatar", path=f"{row.id}.{format_name}"
            ):
                session.close()
                raise standarts.AvatarDeletionFailedError(
                    detail="Что-то пошло не так при удалении аватара из системы.",
                    instance=str(request.url),
                )

        # Выполнение операции INSERT
        session.execute(insert_statement)
        session.commit()

        session.query(account.Account).filter_by(id=user_id).update(
            {
                "yandex_id": None,
                "google_id": None,
                "username": None,
                "about": None,
                "avatar_url": None,
                "grade": None,
                "password_hash": None,
            }
        )
        session.query(account.Session).filter_by(owner_id=user_id).update(
            {
                "broken": "account deleted",
            }
        )

        session.commit()

        session.close()
        return PlainTextResponse(status_code=200, content="Успешно!")
    else:
        raise standarts.UnauthorizedError(instance=str(request.url))
