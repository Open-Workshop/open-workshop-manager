"""Profile REST routes."""

from __future__ import annotations

import datetime
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import insert, select, update

from open_workshop_manager import settings as config, standarts, tools
from open_workshop_manager.api_helpers import ensure_fields_not_none, ensure_non_empty_patch
from open_workshop_manager.api_models import (
    ProfileGeneralRead,
    ProfilePatch,
    ProfilePasswordPatch,
    ProfilePrivateRead,
    ProfileRead,
    ProfileRightsPatch,
    ProfileRightsRead,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account

router = APIRouter()

PROFILE_INCLUDE_FIELDS = {"general", "rights", "private"}


def _raise_profile_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Profile not found.",
        code="PROFILE_NOT_FOUND",
        instance=str(request.url),
    )


def _profile_general_payload(row: account.Account, now: datetime.datetime) -> ProfileGeneralRead:
    return ProfileGeneralRead(
        id=int(row.id),
        username=str(getattr(row, "username", "")),
        about=str(getattr(row, "about", "") or ""),
        avatar_url=str(getattr(row, "avatar_url", "") or ""),
        grade=str(getattr(row, "grade", "") or ""),
        comments=int(getattr(row, "comments", 0) or 0),
        author_mods=int(getattr(row, "author_mods", 0) or 0),
        registration_date=getattr(row, "registration_date", now),
        reputation=int(getattr(row, "reputation", 0) or 0),
        mute=bool(getattr(row, "mute_until", None) and getattr(row, "mute_until") > now),
        mute_until=getattr(row, "mute_until", None),
    )


def _profile_private_payload(row: account.Account) -> ProfilePrivateRead:
    return ProfilePrivateRead(
        last_username_reset=getattr(row, "last_username_reset", None),
        last_password_reset=getattr(row, "last_password_reset", None),
        yandex=bool(getattr(row, "yandex_id", None)),
        google=bool(getattr(row, "google_id", None)),
    )


def _profile_rights_payload(row: account.Account) -> ProfileRightsRead:
    return ProfileRightsRead(
        admin=bool(getattr(row, "admin", False)),
        write_comments=bool(getattr(row, "write_comments", False)),
        set_reactions=bool(getattr(row, "set_reactions", False)),
        create_reactions=bool(getattr(row, "create_reactions", False)),
        publish_mods=bool(getattr(row, "publish_mods", False)),
        change_authorship_mods=bool(getattr(row, "change_authorship_mods", False)),
        change_self_mods=bool(getattr(row, "change_self_mods", False)),
        change_mods=bool(getattr(row, "change_mods", False)),
        delete_self_mods=bool(getattr(row, "delete_self_mods", False)),
        delete_mods=bool(getattr(row, "delete_mods", False)),
        mute_users=bool(getattr(row, "mute_users", False)),
        create_forums=bool(getattr(row, "create_forums", False)),
        change_authorship_forums=bool(getattr(row, "change_authorship_forums", False)),
        change_self_forums=bool(getattr(row, "change_self_forums", False)),
        change_forums=bool(getattr(row, "change_forums", False)),
        delete_self_forums=bool(getattr(row, "delete_self_forums", False)),
        delete_forums=bool(getattr(row, "delete_forums", False)),
        change_username=bool(getattr(row, "change_username", False)),
        change_about=bool(getattr(row, "change_about", False)),
        change_avatar=bool(getattr(row, "change_avatar", False)),
        vote_for_reputation=bool(getattr(row, "vote_for_reputation", False)),
    )


def _normalize_include(request: Request, include: list[str]) -> set[str]:
    normalized = {item.strip() for item in include if item and item.strip()}
    unknown = normalized.difference(PROFILE_INCLUDE_FIELDS)
    if unknown:
        raise standarts.StandardAPIError(
            status_code=400,
            title="Bad Request",
            detail="Unsupported include field.",
            code="UNSUPPORTED_INCLUDE_FIELD",
            instance=str(request.url),
            context={"field": sorted(unknown)[0], "allowed": sorted(PROFILE_INCLUDE_FIELDS)},
        )
    if not normalized:
        normalized = {"general"}
    return normalized


@router.get(
    "/profiles/{user_id}",
    tags=["Profile"],
    status_code=200,
    response_model=ProfileRead,
    response_model_exclude_none=True,
)
async def get_profile(
    request: Request,
    user_id: int,
    include: list[str] = Query(default_factory=lambda: ["general"]),
) -> ProfileRead:
    include_set = _normalize_include(request, include)
    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        result = ProfileRead()
        now = datetime.datetime.now()

        if "general" in include_set:
            result.general = _profile_general_payload(row, now)

        if "private" in include_set or "rights" in include_set:
            access_result = await tools.access_profile(request=request, profile_id=user_id)
            if not access_result.authenticated:
                raise standarts.UnauthorizedError(instance=str(request.url))
            if user_id != access_result.owner_id and not access_result.info.meta.value:
                raise standarts.ForbiddenError(
                    detail=access_result.info.meta.reason,
                    instance=str(request.url),
                    context={"reason_code": access_result.info.meta.reason_code},
                )

            if "private" in include_set:
                result.private = _profile_private_payload(row)
            if "rights" in include_set:
                result.rights = _profile_rights_payload(row)

        return result


@router.get(
    "/profiles/{user_id}/avatar",
    tags=["Profile"],
    status_code=307,
)
async def get_avatar(request: Request, user_id: int):
    async with account.AsyncSessionLocal() as session:
        avatar_url = await session.scalar(
            select(account.Account.avatar_url).where(account.Account.id == user_id)
        )

    if avatar_url is None:
        _raise_profile_not_found(request)

    if not avatar_url:
        return Response(status_code=204)

    avatar_url_str = str(avatar_url)
    if avatar_url_str.startswith("local"):
        ext = avatar_url_str.split(".")[-1]
        return RedirectResponse(url=f"{config.STORAGE_URL}/download/avatar/{user_id}.{ext}")

    return RedirectResponse(url=avatar_url_str)


@router.delete(
    "/profiles/{user_id}/avatar",
    tags=["Profile"],
    status_code=204,
)
async def delete_avatar(request: Request, user_id: int) -> Response:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.edit.avatar.value:
        raise standarts.ForbiddenError(
            detail=access_result.edit.avatar.reason,
            instance=str(request.url),
            context={"reason_code": access_result.edit.avatar.reason_code},
        )

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        avatar_url = str(getattr(row, "avatar_url", "") or "")
        if avatar_url.startswith("local"):
            ext = avatar_url.split(".")[-1]
            if not await tools.storage_file_delete(type="avatar", path=f"{row.id}.{ext}"):
                raise standarts.AvatarDeletionFailedError(instance=str(request.url))
        row.avatar_url = ""
        await session.commit()

    return Response(status_code=204)


@router.patch(
    "/profiles/{user_id}",
    tags=["Profile"],
    status_code=200,
    response_model=ProfileGeneralRead,
    response_model_exclude_none=True,
)
async def patch_profile(
    request: Request,
    user_id: int,
    payload: ProfilePatch,
) -> ProfileGeneralRead:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("username", "about", "grade"),
        detail="Profile patch fields cannot be null.",
    )

    owner_id = access_result.owner_id
    can_manage_rights = bool(access_result.edit.rights.value)
    now = datetime.datetime.now()

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        if owner_id != user_id and not can_manage_rights:
            if "username" in data and not access_result.edit.nickname.value:
                raise standarts.ForbiddenError(
                    detail=access_result.edit.nickname.reason,
                    instance=str(request.url),
                    context={"reason_code": access_result.edit.nickname.reason_code},
                )
            if "about" in data and not access_result.edit.description.value:
                raise standarts.ForbiddenError(
                    detail=access_result.edit.description.reason,
                    instance=str(request.url),
                    context={"reason_code": access_result.edit.description.reason_code},
                )
            if "grade" in data and not access_result.edit.grade.value:
                raise standarts.ForbiddenError(
                    detail=access_result.edit.grade.reason,
                    instance=str(request.url),
                    context={"reason_code": access_result.edit.grade.reason_code},
                )
            if "mute_until" in data and not access_result.edit.mute.value:
                raise standarts.ForbiddenError(
                    detail=access_result.edit.mute.reason,
                    instance=str(request.url),
                    context={"reason_code": access_result.edit.mute.reason_code},
                )
        elif owner_id == user_id and "mute_until" in data:
            raise standarts.BadRequestError(
                detail="Cannot mute yourself.",
                instance=str(request.url),
                code="SELF_MUTE_FORBIDDEN",
            )

        if "username" in data:
            username = str(data["username"])
            if len(username) < LIMITS.profile.username_min:
                raise standarts.PreconditionRequiredError(
                    detail="Username is too short.",
                    instance=str(request.url),
                )
            if len(username) > LIMITS.profile.username_max:
                raise standarts.PayloadTooLargeError(
                    detail="Username is too long.",
                    instance=str(request.url),
                )
            existing = (
                await session.execute(
                    select(account.Account.id).where(
                        account.Account.username == username,
                        account.Account.id != user_id,
                    )
                )
            ).first()
            if existing:
                raise standarts.ConflictError(
                    detail="Username already exists.",
                    instance=str(request.url),
                    code="PROFILE_USERNAME_ALREADY_EXISTS",
                )
            row.username = username
            row.last_username_reset = now

        if "about" in data:
            about = str(data["about"])
            if len(about) > LIMITS.profile.about_max:
                raise standarts.PayloadTooLargeError(
                    detail="About is too long.",
                    instance=str(request.url),
                )
            row.about = about

        if "grade" in data:
            grade = str(data["grade"])
            if len(grade) < LIMITS.profile.grade_min:
                raise standarts.PreconditionRequiredError(
                    detail="Grade is too short.",
                    instance=str(request.url),
                )
            if len(grade) > LIMITS.profile.grade_max:
                raise standarts.PayloadTooLargeError(
                    detail="Grade is too long.",
                    instance=str(request.url),
                )
            row.grade = grade

        if "mute_until" in data:
            mute_until = data["mute_until"]
            if mute_until is not None and not isinstance(mute_until, datetime.datetime):
                raise standarts.BadRequestError(
                    detail="Invalid mute_until value.",
                    instance=str(request.url),
                )
            if mute_until is not None and mute_until <= now:
                raise standarts.PreconditionRequiredError(
                    detail="Mute end date must be in the future.",
                    instance=str(request.url),
                )
            row.mute_until = mute_until

        await session.commit()
        return _profile_general_payload(row, now)


@router.patch(
    "/profiles/{user_id}/rights",
    tags=["Profile"],
    status_code=200,
    response_model=ProfileRightsRead,
    response_model_exclude_none=True,
)
async def patch_profile_rights(
    request: Request,
    user_id: int,
    payload: ProfileRightsPatch,
) -> ProfileRightsRead:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.edit.rights.value:
        raise standarts.ForbiddenError(
            detail=access_result.edit.rights.reason,
            instance=str(request.url),
            context={"reason_code": access_result.edit.rights.reason_code},
        )

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        data.keys(),
        detail="Profile rights fields cannot be null.",
    )

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        for key, value in data.items():
            setattr(row, key, value)
        await session.commit()
        return _profile_rights_payload(row)


@router.patch(
    "/profiles/{user_id}/password",
    tags=["Profile"],
    status_code=204,
)
async def patch_profile_password(
    request: Request,
    user_id: int,
    payload: ProfilePasswordPatch,
) -> Response:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if access_result.owner_id != user_id:
        raise standarts.ForbiddenError(
            detail="Password can only be changed for your own account.",
            instance=str(request.url),
        )

    if len(payload.new_password) < LIMITS.profile.password_min:
        raise standarts.PreconditionRequiredError(
            detail="Password is too short.",
            instance=str(request.url),
        )
    if len(payload.new_password) > LIMITS.profile.password_max:
        raise standarts.PayloadTooLargeError(
            detail="Password is too long.",
            instance=str(request.url),
        )

    import bcrypt

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)
        row.password_hash = bcrypt.hashpw(payload.new_password.encode("utf-8"), bcrypt.gensalt(9)).decode("utf-8")
        row.last_password_reset = datetime.datetime.now()
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/profiles/{user_id}/password",
    tags=["Profile"],
    status_code=204,
)
async def delete_profile_password(request: Request, user_id: int) -> Response:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if access_result.owner_id != user_id:
        raise standarts.ForbiddenError(
            detail="Password can only be changed for your own account.",
            instance=str(request.url),
        )

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)
        row.password_hash = None
        row.last_password_reset = datetime.datetime.now()
        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/profiles/{user_id}",
    tags=["Profile"],
    status_code=204,
)
async def delete_profile(request: Request, user_id: int) -> Response:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.delete.value:
        raise standarts.ForbiddenError(
            detail=access_result.delete.reason,
            instance=str(request.url),
            context={"reason_code": access_result.delete.reason_code},
        )

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        avatar_url = str(getattr(row, "avatar_url", "") or "")
        if avatar_url.startswith("local"):
            ext = avatar_url.split(".")[-1]
            if not await tools.storage_file_delete(type="avatar", path=f"{row.id}.{ext}"):
                raise standarts.AvatarDeletionFailedError(instance=str(request.url))

        await session.execute(
            insert(account.blocked_account_creation).values(
                yandex_id=row.yandex_id,
                google_id=row.google_id,
                forget=datetime.datetime.now() + datetime.timedelta(days=5),
            )
        )
        await session.execute(
            update(account.Session)
            .where(account.Session.owner_id == user_id)
            .values(broken="account deleted")
        )

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
        await session.commit()

    return Response(status_code=204)
