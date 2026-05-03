"""Profile REST routes."""

from __future__ import annotations

import datetime
from typing import Literal
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, insert, select, update

from open_workshop_manager import reputation, settings as config, standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    ProfileGeneralRead,
    ProfilePatch,
    ProfilePasswordPatch,
    ProfilePrivateRead,
    ProfileSearchListResponse,
    ProfileSearchRead,
    ProfileRead,
    ProfileRatingRead,
    ProfileRightsPatch,
    ProfileRightsRead,
    RatingHistoryRead,
    RatingHistoryListResponse,
    RatingVoteUpsert,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account

router = APIRouter()

PROFILE_INCLUDE_FIELDS = {"general", "rights", "private"}
ProfileIncludeField = Literal["general", "rights", "private"]


def _raise_profile_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Profile not found.",
        code="PROFILE_NOT_FOUND",
        instance=str(request.url),
    )


PROFILE_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Profile not found.",
        code="PROFILE_NOT_FOUND",
    ),
    "Profile not found.",
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
        reputation=float(getattr(row, "reputation", 0) or 0.0),
        mute=bool(getattr(row, "mute_until", None) and getattr(row, "mute_until") > now),
        mute_until=getattr(row, "mute_until", None),
    )


def _profile_search_payload(row: account.Account) -> ProfileSearchRead:
    return ProfileSearchRead(
        id=int(row.id),
        username=str(getattr(row, "username", "")),
        grade=str(getattr(row, "grade", "") or ""),
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


def _raise_profile_right_denied(request: Request, right) -> None:
    reason_code = str(getattr(right, "reason_code", "") or "forbidden")
    detail = str(getattr(right, "reason", "") or "Forbidden")
    if reason_code in {"muted", "cooldown"}:
        raise standarts.TooEarlyError(
            detail=detail,
            instance=str(request.url),
            context={"reason_code": reason_code},
        )
    raise standarts.ForbiddenError(
        detail=detail,
        instance=str(request.url),
        context={"reason_code": reason_code},
    )


@router.get(
    "/profiles",
    tags=["Profile"],
    summary="Search profiles",
    description=(
        "Returns a paginated list of profiles filtered by nickname substring.\n\n"
        "Use this endpoint to look up users by nickname when adding authors."
    ),
    status_code=200,
    response_model=ProfileSearchListResponse,
    response_model_exclude_none=True,
    response_description="Paginated profile search results.",
)
async def list_profiles(
    request: Request,
    page_size: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of profiles to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    username: str = Query(
        ...,
        min_length=1,
        max_length=LIMITS.profile.username_max,
        description="Case-insensitive substring filter for the profile nickname.",
    ),
):
    username_query = username.strip()
    if not username_query:
        return make_list_response([], page=page, page_size=page_size, total=0)

    async with account.AsyncSessionLocal() as session:
        base_stmt = (
            select(account.Account)
            .where(account.Account.username.is_not(None))
            .where(account.Account.username != "")
        )
        count_stmt = select(func.count()).select_from(account.Account).where(
            account.Account.username.is_not(None),
            account.Account.username != "",
            account.Account.username.ilike(f"%{username_query}%"),
        )
        list_stmt = (
            base_stmt.where(account.Account.username.ilike(f"%{username_query}%"))
            .order_by(account.Account.username.asc(), account.Account.id.asc())
        )

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

    items = [_profile_search_payload(row).model_dump(mode="json", exclude_none=True) for row in rows]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/profiles/{user_id}",
    tags=["Profile"],
    summary="Get profile",
    description=(
        "Returns a profile by user ID.\n\n"
        "Use `include` to opt in to the `general`, `private`, and `rights` sections."
    ),
    status_code=200,
    response_model=ProfileRead,
    response_model_exclude_none=True,
    response_description="Profile object.",
)
async def get_profile(
    request: Request,
    user_id: int,
    include: list[ProfileIncludeField] = Query(
        default_factory=lambda: ["general"],
        description="Profile sections to include in the response.",
    ),
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


@router.put(
    "/profiles/{user_id}/rating",
    tags=["Profile"],
    summary="Rate profile",
    description=(
        "Sets the current user's vote for a profile.\n\n"
        "Send `value=1` to upvote, `value=-1` to downvote, or `value=0` to clear "
        "the current vote. Profile reputation changes by 1 point per vote step, "
        "while mod ratings change by 1 point per vote step and author reputation "
        "changes by 0.1 point per mod vote, which is 1 point for every 10 mod "
        "rating points."
    ),
    status_code=200,
    response_model=ProfileRatingRead,
    response_model_exclude_none=True,
    response_description="Updated profile reputation.",
    responses={401: standarts.UNAUTHORIZED_RESPONSE_SPEC, 403: standarts.FORBIDDEN_RESPONSE_SPEC, 404: PROFILE_NOT_FOUND_RESPONSE},
)
async def put_profile_rating(
    request: Request,
    user_id: int,
    payload: RatingVoteUpsert,
) -> ProfileRatingRead:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.vote_for_reputation.value:
        _raise_profile_right_denied(request, access_result.vote_for_reputation)

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        reputation_value = await reputation.apply_profile_vote(
            session,
            voter_id=int(access_result.owner_id),
            profile=row,
            value=int(payload.value),
        )
        await session.commit()
        return ProfileRatingRead(profile_id=user_id, reputation=reputation_value)


@router.get(
    "/profiles/{user_id}/rating/history",
    tags=["Profile"],
    summary="Get vote history",
    description=(
        "Returns the latest stored vote state for each mod or profile this user has rated."
    ),
    status_code=200,
    response_model=RatingHistoryListResponse,
    response_model_exclude_none=True,
    response_description="Paginated latest vote states.",
    responses={404: PROFILE_NOT_FOUND_RESPONSE},
)
async def get_profile_rating_history(
    request: Request,
    user_id: int,
    page_size: int = Query(
        default=LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of history items to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
):
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if user_id != access_result.owner_id and not access_result.info.meta.value:
        raise standarts.ForbiddenError(
            detail=access_result.info.meta.reason,
            instance=str(request.url),
            context={"reason_code": access_result.info.meta.reason_code},
        )

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        offset = page * page_size
        total, rows = await reputation.load_vote_history_page(
            session,
            voter_id=user_id,
            offset=offset,
            limit=page_size,
        )

    items = [
        RatingHistoryRead.model_validate(row).model_dump(mode="json", exclude_none=True)
        for row in rows
    ]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/profiles/{user_id}/avatar",
    tags=["Profile"],
    summary="Get profile avatar",
    description="Redirects to the current profile avatar URL.",
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
    summary="Delete profile avatar",
    description="Deletes the current profile avatar.",
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
    summary="Update profile",
    description="Updates the editable general profile fields.",
    status_code=200,
    response_model=ProfileGeneralRead,
    response_model_exclude_none=True,
    response_description="Updated general profile data.",
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

    now = datetime.datetime.now()

    async with account.AsyncSessionLocal() as session:
        row = await session.get(account.Account, user_id)
        if row is None:
            _raise_profile_not_found(request)

        if "username" in data and not access_result.edit.nickname.value:
            _raise_profile_right_denied(request, access_result.edit.nickname)
        if "about" in data and not access_result.edit.description.value:
            _raise_profile_right_denied(request, access_result.edit.description)
        if "grade" in data and not access_result.edit.grade.value:
            _raise_profile_right_denied(request, access_result.edit.grade)
        if "mute_until" in data and not access_result.edit.mute.value:
            _raise_profile_right_denied(request, access_result.edit.mute)

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
    summary="Update profile rights",
    description="Updates the profile moderation and permission flags.",
    status_code=200,
    response_model=ProfileRightsRead,
    response_model_exclude_none=True,
    response_description="Updated profile rights.",
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
    summary="Update profile password",
    description="Changes the profile password.",
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
    if not access_result.edit.password.value:
        _raise_profile_right_denied(request, access_result.edit.password)

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
    summary="Delete profile password",
    description="Removes the profile password hash.",
    status_code=204,
)
async def delete_profile_password(request: Request, user_id: int) -> Response:
    access_result = await tools.access_profile(request=request, profile_id=user_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.edit.password.value:
        _raise_profile_right_denied(request, access_result.edit.password)

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
    summary="Delete profile",
    description="Deletes the profile and its attached avatar, if any.",
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
