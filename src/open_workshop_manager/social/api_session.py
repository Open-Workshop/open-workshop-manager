"""Session and OAuth routes."""

from __future__ import annotations

import datetime
import logging
import json
import os
import random
import string
from functools import lru_cache
from io import BytesIO
from pathlib import Path as FilePath
from typing import TypedDict, cast
from urllib.parse import unquote

import aiohttp
import bcrypt
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from httpx import HTTPStatusError
from sqlalchemy import select, update
from yandexid import AsyncYandexID, AsyncYandexOAuth
from yandexid.errors.yandexoauth import YandexOAuthError

from open_workshop_manager import settings as config, standarts, tools
from open_workshop_manager.api_models import SessionCreate, SessionRead, SessionRefreshRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account

router = APIRouter()
logger = logging.getLogger(__name__)

GOOGLE_CREDENTIALS_PATH_ENV = "GOOGLE_OAUTH_CREDENTIALS_PATH"
DEFAULT_GOOGLE_CREDENTIALS_PATH = FilePath(__file__).resolve().parents[3] / "credentials.json"
GOOGLE_OAUTH_STATE_COOKIE = "googleOAuthState"
GOOGLE_OAUTH_CODE_VERIFIER_COOKIE = "googleOAuthCodeVerifier"
GOOGLE_OAUTH_COOKIE_MAX_AGE = 600


class _GoogleWebConfig(TypedDict):
    client_id: str
    client_secret: str
    redirect_uris: list[str]


class _GoogleConfig(TypedDict):
    web: _GoogleWebConfig


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


yandex_oauth = AsyncYandexOAuth(
    client_id=config.yandex_client_id,
    client_secret=config.yandex_client_secret,
    redirect_uri=f"{config.API_BASE_URL.rstrip('/')}/oauth/yandex/callback",
)


def _raise_bad_request(request: Request, detail: str, code: str = "BAD_REQUEST") -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail=detail,
        code=code,
        instance=str(request.url),
    )


def _set_session_cookies(response: Response, access_token: str, refresh_token: str, access_end: datetime.datetime, refresh_end: datetime.datetime, user_id: int) -> None:
    response.set_cookie(
        key="accessToken",
        value=access_token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=2100,
    )
    response.set_cookie(
        key="refreshToken",
        value=refresh_token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )
    response.set_cookie(
        key="loginJS",
        value=refresh_end.strftime(account.STANDART_STR_TIME),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )
    response.set_cookie(
        key="accessJS",
        value=access_end.strftime(account.STANDART_STR_TIME),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )
    response.set_cookie(
        key="userID",
        value=str(user_id),
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=5184000,
    )


def _generate_session_pair(
    now: datetime.datetime | None = None,
) -> tuple[str, str, datetime.datetime, datetime.datetime]:
    now = now or datetime.datetime.now()
    access_token = bcrypt.hashpw(
        str(now.microsecond).encode("utf-8"),
        bcrypt.gensalt(6),
    ).decode("utf-8")
    refresh_token = bcrypt.hashpw(
        str(now.microsecond).encode("utf-8"),
        bcrypt.gensalt(7),
    ).decode("utf-8")
    access_end = now + datetime.timedelta(minutes=40)
    refresh_end = now + datetime.timedelta(days=60)
    return access_token, refresh_token, access_end, refresh_end


def _random_username(prefix: str = "OW user ", length: int = 6) -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=length))
    return f"{prefix}{suffix}"


def _bounded_username(value: str | None, fallback: str) -> str:
    username = (value or "").strip() or fallback
    return username[:128]


def _session_summary(row: account.Session) -> SessionRead | SessionRefreshRead:
    return SessionRead(
        user_id=int(row.owner_id or 0),
        access_expires_at=row.end_date_access,
        refresh_expires_at=row.end_date_refresh,
    )


@router.post(
    "/sessions",
    tags=["Session"],
    status_code=201,
    response_model=SessionRead,
    response_model_exclude_none=True,
)
async def create_session(response: Response, request: Request, payload: SessionCreate) -> SessionRead:
    if payload.method != "password":
        _raise_bad_request(request, "Unsupported login method.", code="UNSUPPORTED_LOGIN_METHOD")

    if len(payload.password) < LIMITS.session.password_min:
        raise standarts.PreconditionRequiredError(
            detail="Password is too short.",
            instance=str(request.url),
        )
    if len(payload.password) > LIMITS.session.password_max:
        raise standarts.PayloadTooLargeError(
            detail="Password is too long.",
            instance=str(request.url),
        )

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Account.id, account.Account.password_hash).where(
                account.Account.username == payload.login
            )
        )
        user = result.first()

        if (
            user
            and user.password_hash is not None
            and len(user.password_hash) > 1
            and bcrypt.checkpw(
                password=payload.password.encode("utf-8"),
                hashed_password=user.password_hash.encode("utf-8"),
            )
        ):
            sessions_data = await account.gen_session(
                user_id=user.id,
                session=session,
                login_method="password",
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
                value=sessions_data["refresh"]["end"].strftime(account.STANDART_STR_TIME),
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )
            response.set_cookie(
                key="accessJS",
                value=sessions_data["access"]["end"].strftime(account.STANDART_STR_TIME),
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )
            response.set_cookie(
                key="userID",
                value=str(user.id),
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                max_age=5184000,
            )

            await session.commit()
            return SessionRead(
                user_id=int(user.id),
                access_expires_at=sessions_data["access"]["end"],
                refresh_expires_at=sessions_data["refresh"]["end"],
            )

    raise standarts.UnauthorizedError(
        detail="Invalid login or password.",
        instance=str(request.url),
    )


@router.post(
    "/sessions/current/refresh",
    tags=["Session"],
    status_code=200,
    response_model=SessionRefreshRead,
    response_model_exclude_none=True,
)
async def refresh_session(response: Response, request: Request) -> SessionRefreshRead:
    access_token = request.cookies.get("accessToken", "")
    refresh_token = request.cookies.get("refreshToken", "")
    if not access_token or not refresh_token:
        raise standarts.UnauthorizedError(instance=str(request.url))

    now = datetime.datetime.now()
    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Session).where(
                account.Session.access_token == access_token,
                account.Session.refresh_token == refresh_token,
                account.Session.broken.is_(None),
                account.Session.end_date_refresh > now,
            )
        )
        row = result.scalar_one_or_none()
        if row is None or row.owner_id is None:
            raise standarts.UnauthorizedError(instance=str(request.url))

        account_row = await session.get(account.Account, row.owner_id)
        if account_row is None:
            raise standarts.UnauthorizedError(instance=str(request.url))

        new_access_token, new_refresh_token, new_access_end, new_refresh_end = _generate_session_pair(
            now
        )
        row.access_token = new_access_token
        row.refresh_token = new_refresh_token
        row.last_request_date = now
        row.end_date_access = new_access_end
        row.end_date_refresh = new_refresh_end
        await session.commit()

    _set_session_cookies(
        response=response,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        access_end=new_access_end,
        refresh_end=new_refresh_end,
        user_id=int(account_row.id),
    )
    return SessionRefreshRead(
        access_expires_at=new_access_end,
        refresh_expires_at=new_refresh_end,
    )


@router.delete(
    "/sessions/current",
    tags=["Session"],
    status_code=204,
)
async def logout(response: Response, request: Request) -> Response:
    access_token = request.cookies.get("accessToken", "")
    if not access_token:
        raise standarts.UnauthorizedError(instance=str(request.url))

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Session).where(account.Session.access_token == access_token)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise standarts.UnauthorizedError(instance=str(request.url))

        await session.execute(
            update(account.Session)
            .where(account.Session.access_token == access_token)
            .values(broken="logout")
        )
        await session.commit()

    response.delete_cookie(key="accessToken")
    response.delete_cookie(key="refreshToken")
    response.delete_cookie(key="loginJS")
    response.delete_cookie(key="accessJS")
    response.delete_cookie(key="userID")
    response.status_code = 204
    return response


@router.get(
    "/oauth/{service}/authorize",
    tags=["OAuth"],
    status_code=307,
)
async def oauth_authorize(request: Request, service: str):
    service = service.lower()
    if service == "google":
        try:
            flow = _google_flow()
        except FileNotFoundError:
            raise standarts.InternalServerError(
                detail="Google OAuth credentials are not configured.",
                instance=str(request.url),
            )

        authorization_url, state = flow.authorization_url()
        response = RedirectResponse(url=authorization_url)
        if state:
            response.set_cookie(
                key=GOOGLE_OAUTH_STATE_COOKIE,
                value=state,
                secure=config.COOKIE_SECURE,
                samesite=config.COOKIE_SAMESITE,
                httponly=True,
                max_age=GOOGLE_OAUTH_COOKIE_MAX_AGE,
                path="/",
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
                path="/",
            )
        return response

    if service == "yandex":
        return RedirectResponse(url=yandex_oauth.get_authorization_url())

    _raise_bad_request(request, "Unsupported OAuth service.", code="UNSUPPORTED_OAUTH_SERVICE")


async def _oauth_google_callback(
    request: Request,
    response: Response,
    code: str,
    state: str | None,
) -> str:
    ru = await account.no_from_russia(request=request)
    if ru:
        raise standarts.ForbiddenError(
            detail=ru,
            instance=str(request.url),
        )

    cookie_state = request.cookies.get(GOOGLE_OAUTH_STATE_COOKIE, "")
    if not cookie_state or not state or state != cookie_state:
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

    token_data: dict[str, object]
    async with aiohttp.ClientSession() as net_session:
        token_payload = data.copy()
        token_payload["code"] = unquote(code)
        token_payload["code_verifier"] = code_verifier

        async with net_session.post(
            "https://oauth2.googleapis.com/token",
            data=token_payload,
        ) as token_response:
            try:
                token_data = cast(dict[str, object], await token_response.json())
            except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError) as exc:
                logger.error(
                    "Google token endpoint returned malformed payload: status=%s",
                    token_response.status,
                )
                raise standarts.InternalServerError(
                    detail="Google OAuth returned malformed token response",
                    instance=str(request.url),
                ) from exc

            error = token_data.get("error")
            if error:
                raise standarts.BadRequestError(
                    detail=str(token_data.get("error_description") or error),
                    instance=str(request.url),
                )

            access_token = str(token_data.get("access_token") or "")
            if not access_token:
                raise standarts.BadRequestError(
                    detail="Google OAuth did not return an access token",
                    instance=str(request.url),
                )

            async with net_session.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as user_info_response:
                try:
                    user_data = cast(dict[str, object], await user_info_response.json())
                except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError) as exc:
                    logger.error(
                        "Google userinfo endpoint returned malformed payload: status=%s",
                        user_info_response.status,
                    )
                    raise standarts.InternalServerError(
                        detail="Google OAuth returned malformed userinfo response",
                        instance=str(request.url),
                    ) from exc

    response.delete_cookie(key=GOOGLE_OAUTH_STATE_COOKIE, path="/")
    response.delete_cookie(key=GOOGLE_OAUTH_CODE_VERIFIER_COOKIE, path="/")

    provider_id = str(user_data.get("id") or "")
    if not provider_id:
        raise standarts.BadRequestError(
            detail="Google OAuth did not return user id",
            instance=str(request.url),
        )

    picture_url = str(user_data.get("picture") or "")
    fallback_username = _random_username()
    async with account.AsyncSessionLocal() as session:
        existing_account_id = await session.scalar(
            select(account.Account.id).where(account.Account.google_id == provider_id)
        )

        if existing_account_id is None:
            blocked_exists = await session.execute(
                select(account.blocked_account_creation.c.google_id).where(
                    account.blocked_account_creation.c.google_id == provider_id
                )
            )
            if blocked_exists.first():
                raise standarts.GoneError(
                    detail="Этот аккаунт Google использовался в недавно удаленном аккаунте Open Workshop!",
                    instance=str(request.url),
                )

            access_result = await account.check_access(request=request)
            if access_result and access_result.get("owner_id", -1) >= 0:
                row_connect_result = await session.scalar(
                    select(account.Account).where(
                        account.Account.google_id.is_(None),
                        account.Account.id == access_result.get("owner_id", -1),
                    )
                )

                if row_connect_result is None:
                    raise standarts.ConflictError(
                        detail="К аккаунту пользователя уже подключен Google ID",
                        instance=str(request.url),
                    )

                row_connect_result.google_id = provider_id
                await session.commit()
                user_id = int(row_connect_result.id)
            else:
                new_account = account.Account(
                    google_id=provider_id,
                    username=fallback_username,
                    comments=0,
                    author_mods=0,
                    registration_date=datetime.datetime.now(),
                    reputation=0,
                )
                session.add(new_account)
                await session.flush()
                user_id = int(new_account.id)

                if picture_url:
                    await session.commit()
                    async with aiohttp.ClientSession() as net_session:
                        async with net_session.get(picture_url) as picture_response:
                            if picture_response.status == 200:
                                _, _, upload_ok = await tools.storage_file_upload(
                                    type="avatar",
                                    path=f"{user_id}.webp",
                                    file=BytesIO(await picture_response.read()),
                                    file_kind="img",
                                )
                                if upload_ok:
                                    await session.execute(
                                        update(account.Account)
                                        .where(account.Account.id == user_id)
                                        .values(avatar_url="local.webp")
                                    )
                                    await session.commit()
                                else:
                                    logger.warning(
                                        "Google registration: avatar upload failed user_id=%s",
                                        user_id,
                                    )
                            else:
                                logger.warning(
                                    "Google registration: avatar download failed status=%s",
                                    picture_response.status,
                                )
        else:
            user_id = int(existing_account_id)

        sessions_data = await account.gen_session(
            user_id=user_id,
            session=session,
            login_method="google",
        )
        await session.commit()

    _set_session_cookies(
        response=response,
        access_token=sessions_data["access"]["token"],
        refresh_token=sessions_data["refresh"]["token"],
        access_end=sessions_data["access"]["end"],
        refresh_end=sessions_data["refresh"]["end"],
        user_id=user_id,
    )
    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"


async def _oauth_yandex_callback(
    request: Request,
    response: Response,
    code: str,
    cid: str | None,
) -> str:
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
    provider_id = int(user_data.id)
    login = _bounded_username(getattr(user_data, "login", None), _random_username())
    is_avatar_empty = bool(getattr(user_data, "is_avatar_empty", True))
    default_avatar_id = getattr(user_data, "default_avatar_id", None)

    async with account.AsyncSessionLocal() as session:
        existing_account_id = await session.scalar(
            select(account.Account.id).where(account.Account.yandex_id == provider_id)
        )

        if existing_account_id is None:
            blocked_exists = await session.execute(
                select(account.blocked_account_creation.c.yandex_id).where(
                    account.blocked_account_creation.c.yandex_id == provider_id
                )
            )
            if blocked_exists.first():
                raise standarts.GoneError(
                    detail="Этот аккаунт Yandex использовался в недавно удаленном аккаунте Open Workshop!",
                    instance=str(request.url),
                )

            access_result = await account.check_access(request=request)
            if access_result and access_result.get("owner_id", -1) >= 0:
                row_connect_result = await session.scalar(
                    select(account.Account).where(
                        account.Account.yandex_id.is_(None),
                        account.Account.id == access_result.get("owner_id", -1),
                    )
                )

                if row_connect_result is None:
                    raise standarts.ConflictError(
                        detail="К аккаунту пользователя уже подключен Yandex ID",
                        instance=str(request.url),
                    )

                row_connect_result.yandex_id = provider_id
                await session.commit()
                user_id = int(row_connect_result.id)
            else:
                new_account = account.Account(
                    yandex_id=provider_id,
                    username=login,
                    comments=0,
                    author_mods=0,
                    registration_date=datetime.datetime.now(),
                    reputation=0,
                )
                session.add(new_account)
                await session.flush()
                user_id = int(new_account.id)

                if not is_avatar_empty and default_avatar_id:
                    await session.commit()
                    async with aiohttp.ClientSession() as net_session:
                        async with net_session.get(
                            f"https://avatars.yandex.net/get-yapic/{default_avatar_id}/islands-200"
                        ) as avatar_response:
                            if avatar_response.status == 200:
                                _, _, upload_ok = await tools.storage_file_upload(
                                    type="avatar",
                                    path=f"{user_id}.webp",
                                    file=BytesIO(await avatar_response.read()),
                                    file_kind="img",
                                )
                                if upload_ok:
                                    await session.execute(
                                        update(account.Account)
                                        .where(account.Account.id == user_id)
                                        .values(avatar_url="local.webp")
                                    )
                                    await session.commit()
                                else:
                                    logger.warning(
                                        "Yandex registration: avatar upload failed user_id=%s",
                                        user_id,
                                    )
                            else:
                                logger.warning(
                                    "Yandex registration: avatar download failed status=%s",
                                    avatar_response.status,
                                )
        else:
            user_id = int(existing_account_id)

        sessions_data = await account.gen_session(
            user_id=user_id,
            session=session,
            login_method="yandex",
        )
        await session.commit()

    _set_session_cookies(
        response=response,
        access_token=sessions_data["access"]["token"],
        refresh_token=sessions_data["refresh"]["token"],
        access_end=sessions_data["access"]["end"],
        refresh_end=sessions_data["refresh"]["end"],
        user_id=user_id,
    )
    return "Если это окно не закрылось автоматически, можете закрыть его сами :)"


@router.get(
    "/oauth/{service}/callback",
    response_class=HTMLResponse,
    tags=["OAuth"],
    status_code=200,
)
async def oauth_callback(
    request: Request,
    response: Response,
    service: str,
    code: str = Query(...),
    state: str | None = Query(default=None),
    cid: str | None = Query(default=None),
):
    service = service.lower()
    if service == "google":
        return await _oauth_google_callback(
            request=request,
            response=response,
            code=code,
            state=state,
        )
    if service == "yandex":
        return await _oauth_yandex_callback(
            request=request,
            response=response,
            code=code,
            cid=cid,
        )

    _raise_bad_request(request, "Unsupported OAuth service.", code="UNSUPPORTED_OAUTH_SERVICE")
