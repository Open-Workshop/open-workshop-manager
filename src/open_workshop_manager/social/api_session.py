"""Session and OAuth routes."""

from __future__ import annotations

import datetime
import json
import os
from functools import lru_cache
from pathlib import Path as FilePath
from typing import TypedDict, cast

import bcrypt
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select, update
from yandexid import AsyncYandexOAuth

from open_workshop_manager import settings as config, standarts
from open_workshop_manager.api_models import SessionCreate, SessionRead, SessionRefreshRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account

router = APIRouter()

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
async def refresh_session(request: Request) -> SessionRefreshRead:
    access_token = request.cookies.get("accessToken", "")
    refresh_token = request.cookies.get("refreshToken", "")
    if not access_token or not refresh_token:
        raise standarts.UnauthorizedError(instance=str(request.url))

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Session).where(
                account.Session.access_token == access_token,
                account.Session.refresh_token == refresh_token,
                account.Session.broken.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise standarts.UnauthorizedError(instance=str(request.url))

        row.last_request_date = datetime.datetime.now()
        await session.commit()
        return SessionRefreshRead(
            access_expires_at=row.end_date_access,
            refresh_expires_at=row.end_date_refresh,
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


@router.get(
    "/oauth/{service}/callback",
    response_class=HTMLResponse,
    tags=["OAuth"],
    status_code=200,
)
async def oauth_callback(request: Request, service: str, code: str = Query(...), state: str | None = Query(default=None)):
    service = service.lower()
    if service not in {"google", "yandex"}:
        _raise_bad_request(request, "Unsupported OAuth service.", code="UNSUPPORTED_OAUTH_SERVICE")

    # The legacy implementation performed account linking here; the new contract
    # keeps the endpoint but uses a simplified HTML completion response.
    return HTMLResponse("If this window did not close automatically, you can close it yourself.")
