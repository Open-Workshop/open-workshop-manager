import datetime
import json
import logging
import os
import random
import string
from functools import lru_cache
from io import BytesIO
from pathlib import Path as FilePath
from typing import TypedDict, cast
from urllib import parse

import aiohttp
import bcrypt
from fastapi import APIRouter, Form, Path, Query, Request, Response
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from google_auth_oauthlib.flow import Flow
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from yandexid import AsyncYandexID, AsyncYandexOAuth
from yandexid.errors.yandexoauth import YandexOAuthError

from open_workshop_manager import settings as config
from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_account as account

logger = logging.getLogger(__name__)

STANDART_STR_TIME = account.STANDART_STR_TIME
GOOGLE_CREDENTIALS_PATH_ENV = "GOOGLE_OAUTH_CREDENTIALS_PATH"
DEFAULT_GOOGLE_CREDENTIALS_PATH = (
    FilePath(__file__).resolve().parents[3] / "credentials.json"
)
GOOGLE_OAUTH_STATE_COOKIE = "googleOAuthState"
GOOGLE_OAUTH_CODE_VERIFIER_COOKIE = "googleOAuthCodeVerifier"
GOOGLE_OAUTH_COOKIE_MAX_AGE = 600


class _GoogleWebConfig(TypedDict):
    client_id: str
    client_secret: str
    redirect_uris: list[str]


class _GoogleConfig(TypedDict):
    web: _GoogleWebConfig


class _GoogleTokenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    access_token: str | None = None
    error: str | None = None
    error_description: str | None = None


router = APIRouter()

yandex_oauth = AsyncYandexOAuth(
    client_id=config.yandex_client_id,
    client_secret=config.yandex_client_secret,
    redirect_uri=f"{config.API_BASE_URL.rstrip('/')}{MAIN_URL}/session/yandex/complite",
)


def _google_credentials_path() -> FilePath:
    configured = os.getenv(GOOGLE_CREDENTIALS_PATH_ENV)
    if configured:
        return FilePath(configured).expanduser()
    return DEFAULT_GOOGLE_CREDENTIALS_PATH


@lru_cache(maxsize=1)
def _google_config() -> _GoogleConfig:
    credentials_path = _google_credentials_path()
    if not credentials_path.exists():
        raise FileNotFoundError(credentials_path)

    with credentials_path.open("r", encoding="utf-8") as config_file:
        return cast(_GoogleConfig, json.load(config_file))


@lru_cache(maxsize=1)
def _google_flow() -> Flow:
    google_config = _google_config()
    return Flow.from_client_config(
        google_config,
        scopes=["openid", "profile"],
        redirect_uri=google_config["web"]["redirect_uris"][0],
    )


def _google_token_data() -> dict[str, str]:
    google_config = _google_config()
    return {
        "client_id": google_config["web"]["client_id"],
        "client_secret": google_config["web"]["client_secret"],
        "redirect_uri": google_config["web"]["redirect_uris"][0],
        "grant_type": "authorization_code",
    }


@router.get(
    MAIN_URL + "/session/google/link",
    response_class=HTMLResponse,
    tags=["Session"],
    status_code=307,
    summary="Переадресация на авторизацию Google",
    responses={
        200: {"description": "Запрещено на основании законодательства РФ."},
        307: {"description": "Переадресация на SSO Google."},
    },
)
async def google_send_link(request: Request):
    """
    Получение ссылки на авторизацию через Google.
    """
    ru = await account.no_from_russia(request=request)
    if ru:
        raise standarts.ForbiddenError(
            detail=ru,
            instance=str(request.url),
        )

    try:
        flow = _google_flow()
    except FileNotFoundError:
        raise standarts.InternalServerError(
            detail="Google OAuth credentials are not configured",
            instance=str(request.url),
        )

    authorization_url, _state = flow.authorization_url()
    response = RedirectResponse(url=authorization_url)
    cookie_path = MAIN_URL or "/"

    if _state:
        response.set_cookie(
            key=GOOGLE_OAUTH_STATE_COOKIE,
            value=_state,
            secure=config.COOKIE_SECURE,
            samesite=config.COOKIE_SAMESITE,
            httponly=True,
            max_age=GOOGLE_OAUTH_COOKIE_MAX_AGE,
            path=cookie_path,
        )

    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        response.set_cookie(
            key=GOOGLE_OAUTH_CODE_VERIFIER_COOKIE,
            value=code_verifier,
            secure=config.COOKIE_SECURE,
            samesite=config.COOKIE_SAMESITE,
            httponly=True,
            max_age=GOOGLE_OAUTH_COOKIE_MAX_AGE,
            path=cookie_path,
        )

    return response


@router.get(
    MAIN_URL + "/session/yandex/link",
    tags=["Session"],
    status_code=307,
    summary="Переадресация на авторизацию Yandex",
    responses={307: {"description": "Переадресация на SSO Yandex *(YandexID)*."}},
)
async def yandex_send_link():
    """
    Получение ссылки на авторизацию через YandexID
    """
    return RedirectResponse(url=yandex_oauth.get_authorization_url())


@router.get(
    MAIN_URL + "/oauth/{service}/link",
    tags=["Session"],
    status_code=307,
    summary="Переадресация на авторизацию через OAuth сервис",
    responses={
        307: {"description": "Переадресация на SSO сервис."},
        400: {"description": "Неизвестный сервис авторизации."},
    },
)
async def oauth_link(
    request: Request,
    service: str = Path(description="OAuth сервис", examples=["google", "yandex"]),
):
    service = service.lower()
    if service == "google":
        return await google_send_link(request=request)
    if service == "yandex":
        return await yandex_send_link()
    raise standarts.BadRequestError(
        detail="Unsupported service",
        instance=str(request.url),
    )


@router.post(
    MAIN_URL + "/session/password",
    tags=["Session"],
    status_code=200,
    summary="Авторизация через пароль",
    responses={
        200: {"description": "Авторизация прошла успешно."},
        412: {"description": "Неправильный пароль/логин."},
    },
)
async def password_authorization(
    response: Response,
    request: Request,
    login: str = Form(
        ...,
        description="Логин *(имя пользователя)*",
        max_length=LIMITS.session.login_max,
    ),
    password: str = Form(
        ...,
        description="Пароль",
        min_length=LIMITS.session.password_min,
        max_length=LIMITS.session.password_max,
    ),
):
    """
    Рекомендую использовать внешние SSO сервисы авторизации.
    """
    async with account.AsyncSessionLocal() as session:
        # Получаем запись о юзере
        result = await session.execute(
            select(account.Account.id, account.Account.password_hash).where(
                account.Account.username == login
            )
        )
        user = result.first()

        if (
            user
            and user.password_hash is not None
            and len(user.password_hash) > 1
            and bcrypt.checkpw(
                password=password.encode("utf-8"),
                hashed_password=user.password_hash.encode("utf-8"),
            )
        ):
            sessions_data = await account.gen_session(
                user_id=user.id, session=session, login_method="password"
            )

            response.set_cookie(
                key="accessToken",
                value=sessions_data["access"]["token"],
                httponly=True,
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=2100,
            )
            response.set_cookie(
                key="refreshToken",
                value=sessions_data["refresh"]["token"],
                httponly=True,
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )

            response.set_cookie(
                key="loginJS",
                value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME),
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )
            response.set_cookie(
                key="accessJS",
                value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME),
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )
            response.set_cookie(
                key="userID",
                value=user.id,
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )

            await session.commit()

            return True

        raise standarts.UnauthorizedError(
            detail="Неправильный пароль или логин.",
            instance=str(request.url),
        )


@router.get(
    MAIN_URL + "/session/google/complite",
    response_class=HTMLResponse,
    tags=["Session"],
    status_code=200,
    summary="Завершение авторизации (Google)",
    responses={
        200: {"description": "Авторизация прошла успешно."},
        400: {"description": "Не удалось получить access token Google OAuth."},
        409: {"description": "К аккаунту пользователя уже подлючен Google ID."},
        410: {
            "description": "Аккаунт Google использовался в недавно удаленном аккаунте OW *(подождать)*."
        },
    },
)
async def google_complite(
    response: Response,
    request: Request,
    code: str = Query(description="Код доступа к Google OAuth API"),
    state: str = Query(default="", description="OAuth state"),
    _scope: str = "",
    _authuser: int = -1,
    _prompt: str = "",
):
    """
    Если данный аккаунт Google не привязан ни к одному из аккаунтов OW и при этом передать действующий access_token то произойдет коннект.

    Если не передать действующий access_token то создаётся новый аккаунт OW. С Google будет взят аватар и сгенерирован случайный никнейм.
    """
    ru = await account.no_from_russia(request=request)
    if ru:
        raise standarts.ForbiddenError(
            detail=ru,
            instance=str(request.url),
        )

    cookie_state = request.cookies.get(GOOGLE_OAUTH_STATE_COOKIE, "")
    if not cookie_state or state != cookie_state:
        raise standarts.BadRequestError(
            detail="Google OAuth state mismatch",
            instance=str(request.url),
        )

    try:
        data = _google_token_data()
    except FileNotFoundError:
        raise standarts.InternalServerError(
            detail="Google OAuth credentials are not configured",
            instance=str(request.url),
        )

    code_verifier = request.cookies.get(GOOGLE_OAUTH_CODE_VERIFIER_COOKIE, "")
    if not code_verifier:
        raise standarts.BadRequestError(
            detail="Google OAuth verifier is missing",
            instance=str(request.url),
        )

    async with aiohttp.ClientSession() as NETsession:
        data_complite = data.copy()
        data_complite["code"] = parse.unquote(code)
        data_complite["code_verifier"] = code_verifier

        async with NETsession.post(
            "https://oauth2.googleapis.com/token", data=data_complite
        ) as token_response:
            try:
                google_access = _GoogleTokenResponse.model_validate(
                    await token_response.json()
                )
            except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError) as exc:
                logger.error(
                    "Google token endpoint returned malformed payload: status=%s",
                    token_response.status,
                )
                raise standarts.InternalServerError(
                    detail="Google OAuth returned malformed token response",
                    instance=str(request.url),
                ) from exc

            logger.debug("Google token response received")

            if google_access.error:
                raise standarts.BadRequestError(
                    detail=google_access.error_description or google_access.error,
                    instance=str(request.url),
                )

            if not google_access.access_token:
                logger.error(
                    "Google token response is missing access_token: %s",
                    google_access.model_dump(exclude_none=True),
                )
                raise standarts.BadRequestError(
                    detail="Google OAuth did not return an access token",
                    instance=str(request.url),
                )

            async with NETsession.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {google_access.access_token}"},
            ) as user_info_response:
                user_data = await user_info_response.json()

    response.delete_cookie(key=GOOGLE_OAUTH_STATE_COOKIE, path=MAIN_URL or "/")
    response.delete_cookie(
        key=GOOGLE_OAUTH_CODE_VERIFIER_COOKIE, path=MAIN_URL or "/"
    )

    async with account.AsyncSessionLocal() as session:
        # Выполнение запроса
        existing_account_id = (
            await session.execute(
                select(account.Account.id).where(
                    account.Account.google_id == user_data["id"]
                )
            )
        ).scalar_one_or_none()

        if existing_account_id is None:
            blocked_exists = await session.execute(
                select(account.blocked_account_creation.c.google_id).where(
                    account.blocked_account_creation.c.google_id == user_data["id"]
                )
            )
            if blocked_exists.first():
                raise standarts.GoneError(
                    detail="Этот аккаунт Google использовался в недавно удаленном аккаунте Open Workshop!",
                    instance=str(request.url),
                )

            access_result = await account.check_access(request=request, response=response)

            if access_result and access_result.get("owner_id", -1) >= 0:
                row_connect_result = (
                    await session.execute(
                        select(account.Account).where(
                            account.Account.google_id.is_(None),
                            account.Account.id == access_result.get("owner_id", -1),
                        )
                    )
                ).scalar_one_or_none()

                if row_connect_result:
                    row_connect_result.google_id = user_data["id"]
                    await session.commit()
                    id = row_connect_result.id
                else:
                    raise standarts.ConflictError(
                        detail="К аккаунту пользователя уже подключен Google ID",
                        instance=str(request.url),
                    )
            else:
                dtime = datetime.datetime.now()

                async def generate_unique_username():
                    prefix = "OW user "
                    suffix = "".join(
                        random.choices(string.ascii_letters + string.digits, k=6)
                    )
                    return prefix + suffix

                logger.debug("Google registration time=%s", dtime)
                new_account = account.Account(
                    google_id=user_data["id"],
                    username=await generate_unique_username(),
                    comments=0,
                    author_mods=0,
                    registration_date=dtime,
                    reputation=0,
                )
                session.add(new_account)
                await session.flush()
                id = int(new_account.id)

                if len(user_data.get("picture", "")) > 0:
                    await session.commit()

                    async with aiohttp.ClientSession() as NETsession:
                        async with NETsession.get(user_data["picture"]) as resp:
                            if resp.status == 200:
                                result_upload_code, result_upload, result_response = (
                                    await tools.storage_file_upload(
                                        type="avatar",
                                        path=f"{id}.webp",
                                        file=BytesIO(await resp.read()),
                                        file_kind="img",
                                    )
                                )
                                if result_response is not False:
                                    # Помечаем в БД пользователя, что у него есть аватар
                                    await session.execute(
                                        update(account.Account)
                                        .where(account.Account.id == id)
                                        .values(avatar_url="local.webp")
                                    )
                                    await session.commit()
                                else:
                                    logger.warning(
                                        "Google регистрация: во время загрузки аватара "
                                        "произошла ошибка! code=%s detail=%s",
                                        result_upload_code,
                                        result_upload,
                                    )
                            else:
                                logger.warning(
                                    "Google регистрация: во время получения изображения "
                                    "произошла ошибка! status=%s",
                                    resp.status,
                                )
        else:
            id = int(existing_account_id)

        sessions_data = await account.gen_session(
            user_id=id, session=session, login_method="google"
        )

        await session.commit()

    response.set_cookie(
        key="accessToken",
        value=sessions_data["access"]["token"],
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=2100,
    )
    response.set_cookie(
        key="refreshToken",
        value=sessions_data["refresh"]["token"],
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )

    response.set_cookie(
        key="loginJS",
        value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )
    response.set_cookie(
        key="accessJS",
        value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )
    response.set_cookie(
        key="userID",
        value=str(id),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"


@router.get(
    MAIN_URL + "/session/yandex/complite",
    response_class=HTMLResponse,
    tags=["Session"],
    status_code=200,
    summary="Завершение авторизации (Yandex)",
    responses={
        200: {"description": "Авторизация прошла успешно."},
        409: {"description": "К аккаунту пользователя уже подлючен YandexID."},
        410: {
            "description": "Аккаунт Yandex использовался в недавно удаленном аккаунте OW *(подождать)*."
        },
    },
)
async def yandex_complite(
    response: Response,
    request: Request,
    code: str = Query(description="Код доступа к Yandex OAuth API"),
    cid: str | None = Query(
        default=None,
        description="Идентификатор устройства, если Yandex передал его в callback.",
    ),
):
    """
    Если данный аккаунт Yandex не привязан ни к одному из аккаунтов OW и при этом передать действующий access_token то произойдет коннект.

    Если не передать действующий access_token то создаётся новый аккаунт OW. С Yandex будет взят аватар и никнейм.
    """
    device_id = cid if cid and 6 <= len(cid) <= 50 and cid.isalnum() else None

    try:
        token = await yandex_oauth.get_token_from_code(code, device_id=device_id)
    except (HTTPStatusError, YandexOAuthError) as exc:
        logger.warning(
            "Yandex token exchange failed: url=%s cid=%s error=%s",
            request.url.path,
            cid or "-",
            exc,
        )
        raise standarts.BadRequestError(
            detail=str(exc),
            instance=str(request.url),
        ) from exc

    user_data = await AsyncYandexID(oauth_token=token.access_token).get_user_info_json()

    async with account.AsyncSessionLocal() as session:
        # Выполнение запроса
        existing_account_id = (
            await session.execute(
                select(account.Account.id).where(
                    account.Account.yandex_id == user_data.id
                )
            )
        ).scalar_one_or_none()

        if existing_account_id is None:
            blocked_exists = await session.execute(
                select(account.blocked_account_creation.c.yandex_id).where(
                    account.blocked_account_creation.c.yandex_id == user_data.id
                )
            )
            if blocked_exists.first():
                raise standarts.GoneError(
                    detail="Этот аккаунт Yandex использовался в недавно удаленном аккаунте Open Workshop!",
                    instance=str(request.url),
                )

            access_result = await account.check_access(request=request, response=response)

            if access_result and access_result.get("owner_id", -1) >= 0:
                row_connect_result = (
                    await session.execute(
                        select(account.Account).where(
                            account.Account.yandex_id.is_(None),
                            account.Account.id == access_result.get("owner_id", -1),
                        )
                    )
                ).scalar_one_or_none()

                if row_connect_result:
                    row_connect_result.yandex_id = user_data.id
                    await session.commit()
                    rid = row_connect_result.id
                else:
                    raise standarts.ConflictError(
                        detail="К аккаунту пользователя уже подключен Yandex ID",
                        instance=str(request.url),
                    )
            else:
                dtime = datetime.datetime.now()
                print(dtime, type(dtime))
                new_account = account.Account(
                    yandex_id=user_data.id,
                    username=user_data.login,
                    comments=0,
                    author_mods=0,
                    registration_date=dtime,
                    reputation=0,
                )
                session.add(new_account)
                await session.flush()
                rid = int(new_account.id)

                if not user_data.is_avatar_empty:
                    await session.commit()

                    async with aiohttp.ClientSession() as NETsession:
                        async with NETsession.get(
                            f"https://avatars.yandex.net/get-yapic/{user_data.default_avatar_id}/islands-200"
                        ) as resp:
                            if resp.status == 200:
                                result_upload_code, result_upload, result_status = (
                                    await tools.storage_file_upload(
                                        type="avatar",
                                        path=f"{rid}.webp",
                                        file=BytesIO(await resp.read()),
                                        file_kind="img",
                                    )
                                )
                                if result_status:
                                    # Помечаем в БД пользователя, что у него есть аватар
                                    await session.execute(
                                        update(account.Account)
                                        .where(account.Account.id == rid)
                                        .values(avatar_url="local.webp")
                                    )
                                    await session.commit()
                                else:
                                    logger.warning(
                                        "Яндекс регистрация: ошибка загрузки аватара code=%s detail=%s",
                                        result_upload_code,
                                        result_upload,
                                    )
                            else:
                                logger.warning(
                                    "Яндекс регистрация: ошибка получения аватара status=%s",
                                    resp.status,
                                )
        else:
            rid = int(existing_account_id)

        sessions_data = await account.gen_session(
            user_id=rid, session=session, login_method="yandex"
        )

        await session.commit()

    response.set_cookie(key='accessToken', value=sessions_data["access"]["token"], httponly=True, secure=True, max_age=2100)
    response.set_cookie(key='refreshToken', value=sessions_data["refresh"]["token"], httponly=True, secure=True, max_age=5184000)

    response.set_cookie(key='loginJS', value=sessions_data["refresh"]["end"].strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
    response.set_cookie(key='accessJS', value=sessions_data["access"]["end"].strftime(STANDART_STR_TIME), secure=True, max_age=5184000)
    response.set_cookie(key='userID', value=str(rid), secure=True, max_age=5184000)

    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"


@router.delete(
    MAIN_URL + "/oauth/{service_name}",
    tags=["Session", "Profile"],
    status_code=200,
    summary="Отвязывание OAuth сервиса от аккаунта",
    responses={
        200: {"description": "Отвязывание прошло успешно."},
        400: {"description": "Недопустимое значение `service_name`"},
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Аккаунт не найден."},
        406: {"description": "Нельзя отсоединить все сервисы от аккаунта."},
    },
)
@router.post(
    MAIN_URL + "/session/{service_name}/disconnect",
    tags=["Session", "Profile"],
    status_code=200,
    summary="Отвязывание сервиса от аккаунта",
    responses={
        200: {"description": "Отвязывание прошло успешно."},
        400: {"description": "Недопустимое значение `service_name`"},
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Аккаунт не найден."},
        406: {"description": "Нельзя отсоединить все сервисы от аккаунта."},
    },
)
async def disconnect_service(
    response: Response,
    request: Request,
    service_name: str = Path(
        description="Сервис, который необходимо отключить",
        examples=["yandex", "google"],
    ),
):
    """
    Отвязываем один из сервисов от аккаунта, при этом OW не допустит чтобы от аккаунта были отвязаны все сервисы.
    """
    services = ["google", "yandex"]

    if service_name not in services:
        raise standarts.BadRequestError(
            detail="Недопустимое значение service_name!",
            instance=str(request.url),
        )

    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        async with account.AsyncSessionLocal() as session:
            row_result = await session.get(
                account.Account, access_result.get("owner_id", -1)
            )
            if row_result:
                if row_result.yandex_id and row_result.google_id:
                    setattr(row_result, service_name + "_id", None)

                    await session.commit()

                    return PlainTextResponse(status_code=200, content="Успешно!")
                else:
                    raise standarts.ConflictError(
                        detail="Нельзя отсоединить все сервисы от аккаунта!",
                        instance=str(request.url),
                    )
            else:
                raise standarts.NotFoundError(
                    detail="Пользователь не найден!",
                    instance=str(request.url),
                )
    else:
        raise standarts.UnauthorizedError(instance=str(request.url))


@router.post(
    MAIN_URL + "/session/refresh",
    tags=["Session"],
    status_code=200,
    summary="Обновление токенов доступа",
    responses={
        200: {"description": "Токены обновлены."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
    },
)
async def refresh(response: Response, request: Request):
    """
    Получение новой пары access+refresh токенов на основе еще живого refresh токена
    """
    if not await account.update_session(response=response, request=request):
        raise standarts.UnauthorizedError(instance=str(request.url))

    return PlainTextResponse(status_code=200, content="Запрос обработан")


@router.delete(
    MAIN_URL + "/sessions/current",
    tags=["Session"],
    status_code=200,
    summary="Выход из системы",
    responses={
        200: {"description": "Успешно"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
    },
)
@router.post(
    MAIN_URL + "/session/logout",
    tags=["Session"],
    status_code=200,
    summary="Выход из системы",
    responses={200: {"description": "Успешно"}, 401: standarts.UNAUTHORIZED_RESPONSE_SPEC},
)
async def logout(response: Response, request: Request):
    """
    Выход из системы.

    Удаляет аккаунт-куки у пользователя, а так же убивает сессию *(соответсвующее токены становятся невалидными)*!
    """

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Session).where(
                account.Session.access_token == request.cookies.get("accessToken", "")
            )
        )

        if result.scalar_one_or_none():
            # Выполнение запроса
            await session.execute(
                update(account.Session)
                .where(
                    account.Session.access_token
                    == request.cookies.get("accessToken", "")
                )
                .values(broken="logout")
            )
            await session.commit()

            # Удаление токенов у юзера
            response.delete_cookie(key="accessToken")
            response.delete_cookie(key="refreshToken")
            response.delete_cookie(key="loginJS")
            response.delete_cookie(key="accessJS")
            response.delete_cookie(key="userID")

            return PlainTextResponse(status_code=200, content="Успешно!")
        else:
            raise standarts.UnauthorizedError(instance=str(request.url))
