from __future__ import annotations

import datetime
import logging
from typing import Any, TypeVar

import aiohttp
from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict, Field

from open_workshop_manager import settings as config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AccessClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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


class ModsResponse(AccessState):
    allowed_ids: list[int] = Field(default_factory=list)


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


def _request_payload(
    request: Request | None,
    *,
    user_id: int | None = None,
    mods_ids: list[int] | int | None = None,
    mod_id: int | None = None,
    profile_id: int | None = None,
    author_id: int | None = None,
    mode: bool | None = None,
    without_author: bool | None = None,
    edit: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if request is not None:
        access_token = request.cookies.get("accessToken", "")
        refresh_token = request.cookies.get("refreshToken", "")
        if access_token:
            payload["access_token"] = access_token
        if refresh_token:
            payload["refresh_token"] = refresh_token
    if user_id is not None:
        payload["user_id"] = user_id
    if mod_id is not None:
        payload["mod_id"] = mod_id
    normalized_mod_ids = _normalize_mod_ids(mods_ids)
    if normalized_mod_ids:
        payload["mods_ids"] = normalized_mod_ids
    if profile_id is not None:
        payload["profile_id"] = profile_id
    if author_id is not None:
        payload["author_id"] = author_id
    if mode is not None:
        payload["mode"] = mode
    if without_author is not None:
        payload["without_author"] = without_author
    if edit is not None:
        payload["edit"] = edit
    return payload


async def _post_model(path: str, payload: dict[str, Any], model_cls: type[T]) -> T:
    url = config.ACCESS_SERVICE_URL.rstrip("/") + path
    headers = {"x-token": config.ACCESS_SERVICE_TOKEN}
    timeout = aiohttp.ClientTimeout(total=float(config.ACCESS_TIMEOUT_SECONDS))

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise AccessServiceError(
                        f"Access service rejected request with status {response.status}: {text}",
                        status_code=response.status,
                    )
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise AccessServiceError("Access service returned invalid JSON") from exc
    except aiohttp.ClientError as exc:  # pragma: no cover - network failure
        raise AccessServiceError(f"Access service call failed: {exc}") from exc

    return model_cls.model_validate(data)


async def resolve_context(
    *,
    request: Request | None = None,
    response: Response | None = None,
    user_id: int | None = None,
) -> AccessState:
    payload = _request_payload(request, user_id=user_id)
    return await _post_model("/context", payload, AccessState)


async def resolve_mod_add(
    *,
    request: Request | None = None,
    response: Response | None = None,
    without_author: bool | None = None,
) -> ModAddResponse:
    payload = _request_payload(
        request,
        without_author=without_author,
    )
    return await _post_model("/mod", payload, ModAddResponse)


async def resolve_mod(
    *,
    request: Request | None = None,
    response: Response | None = None,
    mod_id: int,
    author_id: int | None = None,
    mode: bool | None = None,
    without_author: bool | None = None,
    user_id: int | None = None,
) -> ModResponse:
    payload = _request_payload(
        request,
        user_id=user_id,
        mod_id=mod_id,
        author_id=author_id,
        mode=mode,
        without_author=without_author,
    )
    return await _post_model(f"/mod/{mod_id}", payload, ModResponse)


async def resolve_mods(
    *,
    request: Request | None = None,
    response: Response | None = None,
    mods_ids: list[int] | int,
    edit: bool = False,
    user_id: int | None = None,
) -> ModsResponse:
    payload = _request_payload(
        request,
        user_id=user_id,
        mods_ids=mods_ids,
        edit=edit,
    )
    return await _post_model("/mods", payload, ModsResponse)


async def resolve_profile(
    *,
    request: Request | None = None,
    response: Response | None = None,
    profile_id: int,
) -> ProfileResponse:
    payload = _request_payload(request, profile_id=profile_id)
    return await _post_model(f"/profile/{profile_id}", payload, ProfileResponse)
