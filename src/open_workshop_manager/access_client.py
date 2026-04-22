from __future__ import annotations

import datetime
from typing import Any, TypeVar

import aiohttp
from fastapi import Request
from pydantic import BaseModel, ConfigDict

from open_workshop_manager import settings as config

T = TypeVar("T", bound=BaseModel)


class AccessModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class AccessModEntry(AccessModel):
    mod_id: int
    public: int = 0
    condition: int = 0
    owner: bool = False
    member: bool = False


class AccessState(AccessModel):
    authenticated: bool = False
    owner_id: int = -1
    login_method: str | None = None

    admin: bool = False
    write_comments: bool = False
    set_reactions: bool = False
    create_reactions: bool = False
    mute_until: datetime.datetime | None = None
    mute_users: bool = False

    publish_mods: bool = False
    change_authorship_mods: bool = False
    change_self_mods: bool = False
    change_mods: bool = False
    delete_self_mods: bool = False
    delete_mods: bool = False

    create_forums: bool = False
    change_authorship_forums: bool = False
    change_self_forums: bool = False
    change_forums: bool = False
    delete_self_forums: bool = False
    delete_forums: bool = False

    change_username: bool = False
    change_about: bool = False
    change_avatar: bool = False
    vote_for_reputation: bool = False

    last_username_reset: datetime.datetime | None = None
    last_password_reset: datetime.datetime | None = None
    password_change_available_at: datetime.datetime | None = None
    username_change_available_at: datetime.datetime | None = None

    mods: list[AccessModEntry] | None = None


class BaseRight(AccessModel):
    value: bool
    reason: str
    reason_code: str


class ModEditResponse(AccessModel):
    title: BaseRight
    description: BaseRight
    short_description: BaseRight
    screenshots: BaseRight
    new_version: BaseRight
    authors: BaseRight
    tags: BaseRight
    dependencies: BaseRight


class ModResponse(AccessState):
    info: BaseRight
    edit: ModEditResponse
    delete: BaseRight
    download: BaseRight


class ModAddResponse(AccessState):
    add: BaseRight
    anonymous_add: BaseRight


class SimpleCrudResponse(AccessState):
    add: BaseRight
    edit: BaseRight
    delete: BaseRight


class GameEditResponse(AccessModel):
    title: BaseRight
    description: BaseRight
    short_description: BaseRight
    screenshots: BaseRight
    tags: BaseRight
    genres: BaseRight


class GameResponse(AccessState):
    edit: GameEditResponse
    delete: BaseRight


class GameAddResponse(AccessState):
    add: BaseRight


class ProfileInfoResponse(AccessModel):
    public: BaseRight
    meta: BaseRight


class ProfileEditResponse(AccessModel):
    nickname: BaseRight
    grade: BaseRight
    description: BaseRight
    avatar: BaseRight
    mute: BaseRight
    rights: BaseRight


class ProfileResponse(AccessState):
    info: ProfileInfoResponse
    edit: ProfileEditResponse
    vote_for_reputation: BaseRight
    write_comments: BaseRight
    set_reactions: BaseRight
    delete: BaseRight


class AccessServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _normalize_mod_ids(mods_ids: list[int] | int | None) -> list[int]:
    if mods_ids is None:
        return []
    if isinstance(mods_ids, int):
        return [mods_ids]
    return [int(mod_id) for mod_id in mods_ids]


def _session_cookies(request: Request | None) -> dict[str, str]:
    if request is None:
        return {}

    cookies: dict[str, str] = {}

    access_token = request.cookies.get("accessToken", "")
    if access_token:
        cookies["accessToken"] = access_token

    refresh_token = request.cookies.get("refreshToken", "")
    if refresh_token:
        cookies["refreshToken"] = refresh_token

    return cookies


async def _post_model(
    path: str,
    payload: dict[str, Any] | None,
    model_cls: type[T],
    *,
    cookies: dict[str, str] | None = None,
) -> T:
    data = await _post_json(path, payload, cookies=cookies)
    return model_cls.model_validate(data)


async def _post_json(
    path: str,
    payload: dict[str, Any] | None,
    *,
    cookies: dict[str, str] | None = None,
) -> Any:
    url = config.ACCESS_SERVICE_URL.rstrip("/") + path
    headers = {"Authorization": f"Bearer {config.ACCESS_SERVICE_TOKEN}"}
    timeout = aiohttp.ClientTimeout(total=float(config.ACCESS_TIMEOUT_SECONDS))

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            post_kwargs: dict[str, Any] = {
                "headers": headers,
                "cookies": cookies or None,
            }
            if payload is not None:
                post_kwargs["json"] = payload
            async with session.post(url, **post_kwargs) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise AccessServiceError(
                        f"Access service rejected request with status {response.status}: {text}",
                        status_code=response.status,
                    )
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise AccessServiceError("Access service returned invalid JSON") from exc
    except aiohttp.ClientError as exc:  # pragma: no cover - network failure
        raise AccessServiceError(f"Access service call failed: {exc}") from exc


async def resolve_mod_add(
    *,
    request: Request | None = None,
) -> ModAddResponse:
    return await _post_model(
        "/mod",
        None,
        ModAddResponse,
        cookies=_session_cookies(request),
    )


async def resolve_mod(
    *,
    request: Request | None = None,
    mod_id: int,
    author_id: int | None = None,
    mode: bool | None = None,
) -> ModResponse:
    payload: dict[str, Any] = {}
    if author_id is not None:
        payload["author_id"] = author_id
    if mode is not None:
        payload["mode"] = mode

    return await _post_model(
        f"/mod/{mod_id}",
        payload,
        ModResponse,
        cookies=_session_cookies(request),
    )


async def resolve_mods(
    *,
    request: Request | None = None,
    mods_ids: list[int] | int,
) -> dict[int, ModResponse]:
    payload = {
        "mods_ids": _normalize_mod_ids(mods_ids),
    }
    data = await _post_json(
        "/mods",
        payload,
        cookies=_session_cookies(request),
    )
    if not isinstance(data, dict):
        raise AccessServiceError("Access service returned unexpected batch response")

    return {
        int(mod_id): ModResponse.model_validate(mod_payload)
        for mod_id, mod_payload in data.items()
    }


async def resolve_profile(
    *,
    request: Request | None = None,
    profile_id: int,
) -> ProfileResponse:
    return await _post_model(
        f"/profile/{profile_id}",
        {},
        ProfileResponse,
        cookies=_session_cookies(request),
    )
