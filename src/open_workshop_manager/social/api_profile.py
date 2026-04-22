import datetime
import logging
import uuid
from urllib.parse import quote

import bcrypt
from fastapi import APIRouter, Form, Path, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import insert, select, update

from open_workshop_manager import settings as config
from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_account as account

logger = logging.getLogger(__name__)

router = APIRouter()


class ProfileRightsPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    admin: bool
    write_comments: bool
    set_reactions: bool
    create_reactions: bool
    publish_mods: bool
    change_authorship_mods: bool
    change_self_mods: bool
    change_mods: bool
    delete_self_mods: bool
    delete_mods: bool
    mute_users: bool
    create_forums: bool
    change_authorship_forums: bool
    change_self_forums: bool
    change_forums: bool
    delete_self_forums: bool
    delete_forums: bool
    change_username: bool
    change_about: bool
    change_avatar: bool
    vote_for_reputation: bool


class ProfilePrivatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_username_reset: datetime.datetime | None = None
    last_password_reset: datetime.datetime | None = None
    yandex: bool
    google: bool


class ProfileGeneralPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    username: str
    about: str
    avatar_url: str
    grade: str
    comments: int
    author_mods: int
    registration_date: datetime.datetime
    reputation: int
    mute: datetime.datetime | bool


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    general: ProfileGeneralPayload | None = None
    private: ProfilePrivatePayload | None = None
    rights: ProfileRightsPayload | None = None


def _profile_private_payload(row: account.Account) -> ProfilePrivatePayload:
    return ProfilePrivatePayload(
        last_username_reset=row.last_username_reset,
        last_password_reset=row.last_password_reset,
        yandex=bool(row.yandex_id),
        google=bool(row.google_id),
    )


def _profile_rights_payload(row: account.Account) -> ProfileRightsPayload:
    return ProfileRightsPayload.model_validate(row, from_attributes=True)


def _profile_general_payload(
    row: account.Account, now: datetime.datetime
) -> ProfileGeneralPayload:
    return ProfileGeneralPayload(
        id=row.id,
        username=row.username,
        about=row.about,
        avatar_url=row.avatar_url,
        grade=row.grade,
        comments=row.comments,
        author_mods=row.author_mods,
        registration_date=row.registration_date,
        reputation=row.reputation,
        mute=row.mute_until if row.mute_until and row.mute_until > now else False,
    )


@router.get(
    MAIN_URL + "/profiles/{user_id}",
    tags=["Profile"],
    summary="Информация о профиле",
    status_code=200,
    response_model=ProfileResponse,
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "Возвращает информацию о профиле по запрошенным разделам."
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
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
    result = ProfileResponse()
    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if not row:
            raise standarts.NotFoundError(
                detail="Пользователь не найден(",
                instance=str(request.url),
            )

        if rights or private:
            logger.debug(
                "Access token cookie present=%s",
                bool(request.cookies.get("accessToken")),
            )
            access_result = await tools.access_profile(
                response=response,
                request=request,
                profile_id=user_id,
            )

            if not access_result.authenticated or access_result.owner_id < 0:
                raise standarts.UnauthorizedError(instance=str(request.url))

            if user_id != access_result.owner_id and not access_result.info.meta.value:
                tools.raise_forbidden_from_right(
                    access_result.info.meta,
                    instance=str(request.url),
                )

            if private:
                result.private = _profile_private_payload(row)

            if rights:
                result.rights = _profile_rights_payload(row)

        if general:
            result.general = _profile_general_payload(row, datetime.datetime.now())

    return result


@router.get(
    MAIN_URL + "/profiles/{user_id}/avatar",
    tags=["Profile"],
    summary="Аватар профиля",
    status_code=307,
    responses={
        200: {"description": "Пользователь не назначил аватар."},
        307: {"description": "Перенаправляет на аватар*(файл)* пользователя."},
        404: {"description": "Пользователь не найден."},
    },
)
async def avatar_profile(
    request: Request,
    user_id: int = Path(description="ID профиля."),
):
    """
    Возвращает url, по которому можно получить аватар пользователя при условии, что он есть.
    """
    async with account.AsyncSessionLocal() as session:
        avatar_url = await session.scalar(
            select(account.Account.avatar_url).where(account.Account.id == user_id)
        )

    if avatar_url:
        if avatar_url.startswith("local"):
            return RedirectResponse(
                url=f'{config.STORAGE_URL}/download/avatar/{user_id}.{avatar_url.split(".")[1]}'
            )
        if len(avatar_url) > 0:
            return RedirectResponse(url=avatar_url)
        return PlainTextResponse(status_code=200, content="Avatar not set.")

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
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
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
    access_result = await tools.access_profile(
        response=response,
        request=request,
        profile_id=user_id,
    )
    if not access_result.authenticated or access_result.owner_id < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, user_id)
        if not user:
            raise standarts.NotFoundError(
                detail="Пользователь не найден!",
                instance=str(request.url),
            )

        if not access_result.edit.avatar.value:
            tools.raise_forbidden_from_right(
                access_result.edit.avatar,
                instance=str(request.url),
            )

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
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
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
    access_result = await tools.access_profile(
        response=response,
        request=request,
        profile_id=user_id,
    )

    # Смотрим действительна ли она (сессия)
    if not access_result.authenticated or access_result.owner_id < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    owner_id = access_result.owner_id  # id юзера запрашивающего данные

    today = datetime.datetime.now()

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, user_id)
        if not user:
            raise standarts.NotFoundError(
                detail="Пользователь не найден!",
                instance=str(request.url),
            )

        if owner_id != user_id:
            if not access_result.admin:
                if new_password is not None or off_password is not None:
                    raise standarts.ForbiddenError(
                        detail="Доступ запрещен!",
                        instance=str(request.url),
                    )
                if username is not None and not access_result.edit.nickname.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.nickname,
                        instance=str(request.url),
                    )
                if about is not None and not access_result.edit.description.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.description,
                        instance=str(request.url),
                    )
                if empty_avatar is not None and not access_result.edit.avatar.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.avatar,
                        instance=str(request.url),
                    )
                if grade is not None and not access_result.edit.grade.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.grade,
                        instance=str(request.url),
                    )
                if mute is not None and not access_result.edit.mute.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.mute,
                        instance=str(request.url),
                    )
            elif new_password is not None or off_password is not None:
                raise standarts.ForbiddenError(
                    detail="Даже администраторы не могут менять пароли!",
                    instance=str(request.url),
                )
        else:
            if mute is not None:
                raise standarts.BadRequestError(
                    detail="Нельзя замутить самого себя!",
                    instance=str(request.url),
                )
            elif not access_result.admin:
                if access_result.mute_until and access_result.mute_until > today:
                    raise standarts.TooEarlyError(
                        detail="Вам выдано временное ограничение на социальную активность :(",
                        instance=str(request.url),
                    )

                if grade is not None:
                    tools.raise_forbidden_from_right(
                        access_result.edit.grade,
                        instance=str(request.url),
                    )

                if (
                    new_password is not None
                    and access_result.last_password_reset
                    and access_result.last_password_reset + datetime.timedelta(minutes=5) > today
                ):
                    raise standarts.TooEarlyError(
                        detail=(
                            access_result.last_password_reset + datetime.timedelta(minutes=5)
                        ).strftime(account.STANDART_STR_TIME),
                        instance=str(request.url),
                    )

                if username is not None:
                    if not access_result.edit.nickname.value:
                        tools.raise_forbidden_from_right(
                            access_result.edit.nickname,
                            instance=str(request.url),
                        )
                    elif (
                        access_result.last_username_reset
                        and (access_result.last_username_reset + datetime.timedelta(days=30)) > today
                    ):
                        raise standarts.TooEarlyError(
                            detail=(
                                access_result.last_username_reset + datetime.timedelta(days=30)
                            ).strftime(account.STANDART_STR_TIME),
                            instance=str(request.url),
                        )

                if empty_avatar is not None and not access_result.edit.avatar.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.avatar,
                        instance=str(request.url),
                    )

                if about is not None and not access_result.edit.description.value:
                    tools.raise_forbidden_from_right(
                        access_result.edit.description,
                        instance=str(request.url),
                    )

        if username:
            if len(username) < LIMITS.profile.username_min:
                raise standarts.PreconditionRequiredError(
                    detail="Слишком короткий никнейм! (минимальная длина 2 символа)",
                    instance=str(request.url),
                )
            if len(username) > LIMITS.profile.username_max:
                raise standarts.PayloadTooLargeError(
                    detail="Слишком длинный никнейм! (максимальная длина 50 символов)",
                    instance=str(request.url),
                )

            existing_username = (
                await session.execute(
                    select(account.Account.id).where(
                        account.Account.username == username,
                        account.Account.id != user_id,
                    )
                )
            ).first()
            if existing_username:
                raise standarts.ConflictError(
                    detail="Этот никнейм уже занят!",
                    instance=str(request.url),
                )

            user.username = username
            user.last_username_reset = today

        if about:
            if len(about) > LIMITS.profile.about_max:
                raise standarts.PayloadTooLargeError(
                    detail='Слишком длинное поле "обо мне"! (максимальная длина 512 символов)',
                    instance=str(request.url),
                )
            user.about = about

        if grade:
            if len(grade) < LIMITS.profile.grade_min:
                raise standarts.PreconditionRequiredError(
                    detail="Слишком короткий грейд! (минимальная длина 2 символа)",
                    instance=str(request.url),
                )
            if len(grade) > LIMITS.profile.grade_max:
                raise standarts.PayloadTooLargeError(
                    detail="Слишком длинный грейд! (максимальная длина 100 символов)",
                    instance=str(request.url),
                )
            user.grade = grade

        if off_password:
            user.password_hash = None
            user.last_password_reset = today
        elif new_password:
            if len(new_password) < LIMITS.profile.password_min:
                raise standarts.PreconditionRequiredError(
                    detail="Слишком короткий пароль! (минимальная длина 6 символа)",
                    instance=str(request.url),
                )
            if len(new_password) > LIMITS.profile.password_max:
                raise standarts.PayloadTooLargeError(
                    detail="Слишком длинный пароль! (максимальная длина 100 символов)",
                    instance=str(request.url),
                )

            user.password_hash = (
                bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(9))
            ).decode("utf-8")
            user.last_password_reset = today

        if mute:
            if mute < today:
                raise standarts.PreconditionRequiredError(
                    detail="Указанная дата окончания мута уже прошла!",
                    instance=str(request.url),
                )
            user.mute_until = mute

        if empty_avatar:
            user.avatar_url = ""

            avatar_url = str(user.avatar_url)
            if avatar_url.startswith("local"):
                format_name = avatar_url.split(".")[1]
                if not await tools.storage_file_delete(
                    type="avatar", path=f"{user.id}.{format_name}"
                ):
                    raise standarts.AvatarDeletionFailedError(
                        detail="Что-то пошло не так при удалении аватара из системы.",
                        instance=str(request.url),
                    )
        await session.commit()

    # Возвращаем успешный результат
    return PlainTextResponse(status_code=202, content="Изменения приняты :)")


@router.patch(
    MAIN_URL + "/profiles/{user_id}/rights",
    tags=["Profile"],
    summary="Редактирование прав профиля",
    status_code=202,
    responses={
        202: {"description": "Изменения приняты."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
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
    access_result = await tools.access_profile(
        response=response,
        request=request,
        profile_id=user_id,
    )

    if not access_result.authenticated or access_result.owner_id < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    owner_id = access_result.owner_id  # id юзера запрашивающего изменения

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, user_id)
        if not user:
            raise standarts.NotFoundError(
                detail="Пользователь не найден!",
                instance=str(request.url),
            )

        if not access_result.edit.rights.value:
            tools.raise_forbidden_from_right(
                access_result.edit.rights,
                instance=str(request.url),
            )

        sample_query_update: dict[str, bool | None] = {
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

        query_update: dict[str, bool] = {}
        for key, value in sample_query_update.items():
            if value is not None:
                query_update[key] = value

        for key, value in query_update.items():
            setattr(user, key, value)
        await session.commit()

    # Возвращаем успешный результат
    return PlainTextResponse(status_code=202, content="Изменения приняты :)")


@router.delete(
    MAIN_URL + "/profiles/{user_id}",
    tags=["Profile"],
    summary="Удаление аккаунта",
    status_code=200,
    responses={
        200: {"description": "Удален успешно."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
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
    access_result = await tools.access_profile(
        response=response,
        request=request,
        profile_id=user_id,
    )

    if not access_result.authenticated or access_result.owner_id < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    if not access_result.delete.value:
        tools.raise_forbidden_from_right(
            access_result.delete,
            instance=str(request.url),
        )

    user_id = access_result.owner_id

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            raise standarts.NotFoundError(
                detail="Пользователь не найден!",
                instance=str(request.url),
            )
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
                raise standarts.AvatarDeletionFailedError(
                    detail="Что-то пошло не так при удалении аватара из системы.",
                    instance=str(request.url),
                )

        await session.execute(insert_statement)
        await session.commit()

        for key in [
            "yandex_id",
            "google_id",
            "username",
            "about",
            "avatar_url",
            "grade",
            "password_hash",
        ]:
            setattr(row, key, None)
        await session.execute(
            update(account.Session)
            .where(account.Session.owner_id == user_id)
            .values(broken="account deleted")
        )

        await session.commit()

    return PlainTextResponse(status_code=200, content="Успешно!")
