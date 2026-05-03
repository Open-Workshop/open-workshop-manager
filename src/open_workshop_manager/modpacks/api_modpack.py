"""Modpack REST routes."""

from __future__ import annotations

import datetime
import re

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, insert, select, update

from open_workshop_manager import reputation, standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import (
    ModAuthorUpsert,
    ModpackCreate,
    ModpackListResponse,
    ModpackPatch,
    ModpackRead,
    ModpackRatingRead,
    RatingVoteUpsert,
    stringify_source_id,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

MODPACK_BAD_REQUEST_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        400,
        title="Bad Request",
        detail="The modpack request contains invalid filters, payload values, or sort fields.",
        code="BAD_REQUEST",
    ),
    "Invalid request parameters.",
)

MODPACK_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Modpack not found.",
        code="MODPACK_NOT_FOUND",
    ),
    "Modpack not found.",
)

GAME_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Game not found.",
        code="GAME_NOT_FOUND",
    ),
    "Game not found.",
)

MODPACK_CONFLICT_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        409,
        title="Conflict",
        detail="Modpack source already exists.",
        code="MODPACK_SOURCE_ALREADY_EXISTS",
    ),
    "Modpack source already exists.",
)


def _raise_modpack_not_found(request: Request) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="Modpack not found.",
        code="MODPACK_NOT_FOUND",
        instance=str(request.url),
    )


def _raise_unsupported_sort(request: Request, field: str) -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported sort field.",
        code="UNSUPPORTED_SORT_FIELD",
        instance=str(request.url),
        context={
            "field": field,
            "allowed": [
                "name",
                "created_at",
                "updated_at",
                "source",
                "downloads",
                "rating",
                "public",
                "adult",
                "game_id",
            ],
        },
    )


def _raise_vote_right_denied(request: Request, right) -> None:
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


def _normalize_source_id(value: object | None) -> str | None:
    return stringify_source_id(value)


async def _load_modpack_current_vote(request: Request, modpack_id: int) -> int | None:
    access_state = await account.check_access(request=request)
    if not access_state or not getattr(access_state, "authenticated", False):
        return None

    voter_id = int(getattr(access_state, "owner_id", -1) or -1)
    if voter_id < 0:
        return None

    async with account.AsyncSessionLocal() as session:
        return await reputation.current_vote_value(
            session,
            voter_id=voter_id,
            target_type="modpack",
            target_id=int(modpack_id),
        )


async def _load_modpack_authors(
    session,
    modpack_ids: list[int],
) -> dict[int, dict[int, dict[str, bool]]]:
    if not modpack_ids:
        return {}

    result = await session.execute(
        select(
            account.modpack_and_author.c.modpack_id,
            account.modpack_and_author.c.user_id,
            account.modpack_and_author.c.owner,
        ).where(account.modpack_and_author.c.modpack_id.in_(modpack_ids))
    )
    authors_by_modpack: dict[int, dict[int, dict[str, bool]]] = {modpack_id: {} for modpack_id in modpack_ids}
    for modpack_id, user_id, owner in result.all():
        authors_by_modpack.setdefault(int(modpack_id), {})[int(user_id)] = {
            "owner": bool(owner),
        }
    return authors_by_modpack


def _serialize_modpack(
    row: catalog.Modpack,
    *,
    authors: dict[int, dict[str, bool]] | None = None,
    current_vote: int | None = None,
) -> ModpackRead:
    payload: dict[str, object] = {
        "id": int(getattr(row, "id", 0) or 0),
        "name": str(getattr(row, "name", "") or ""),
        "short_description": getattr(row, "short_description", None),
        "description": getattr(row, "description", None),
        "source": str(getattr(row, "source", "") or ""),
        "source_id": _normalize_source_id(getattr(row, "source_id", None)),
        "git_url": getattr(row, "git_url", None),
        "game_id": (
            int(getattr(row, "game", 0)) if getattr(row, "game", None) is not None else None
        ),
        "public": int(getattr(row, "public", 0) or 0),
        "adult": bool(getattr(row, "adult", False)),
        "condition": int(getattr(row, "condition", 0) or 0),
        "rating": int(getattr(row, "rating", 0) or 0),
        "current_vote": current_vote,
        "downloads": (
            int(getattr(row, "downloads", 0))
            if getattr(row, "downloads", None) is not None
            else None
        ),
        "created_at": getattr(row, "date_creation", None),
        "updated_at": getattr(row, "date_edit", None),
        "authors": authors,
    }
    return ModpackRead.model_validate(payload)


@router.get(
    "/modpacks",
    tags=["Modpack"],
    summary="List modpacks",
    description=(
        "Returns a paginated list of modpacks.\n\n"
        "Use `show_not_public=true` together with `author_id` to include hidden modpacks "
        "that are visible to the current author context."
    ),
    status_code=200,
    response_model=ModpackListResponse,
    response_model_exclude_none=True,
    response_description="Paginated modpack list.",
    responses={400: MODPACK_BAD_REQUEST_RESPONSE},
)
async def list_modpacks(
    request: Request,
    page_size: int = Query(
        default=LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of modpacks to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(default=None, max_length=LIMITS.mod.name_max),
    source: list[str] = Query(default_factory=list),
    source_ids: list[str] = Query(default_factory=list),
    author_id: int | None = Query(default=None, ge=1),
    game_id: int | None = Query(default=None, ge=1),
    public: int | None = Query(default=None, ge=0, le=2),
    adult: int | None = Query(default=None, ge=0, le=1),
    show_not_public: bool = Query(default=False),
    sort: str = Query(
        default="downloads",
        description="Sort field, optionally prefixed with `-` for descending order.",
    ),
):
    show_not_public = bool(show_not_public and author_id is not None)
    source_ids_normalized = [
        normalized
        for normalized in (
            _normalize_source_id(source_id) for source_id in source_ids
        )
        if normalized is not None
    ]

    try:
        sort_clause = tools.sort_modpacks(sort)
    except KeyError as exc:
        _raise_unsupported_sort(request, exc.args[0] if exc.args else str(exc))

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Modpack).where(catalog.Modpack.condition == 0)
        if author_id is not None:
            stmt = stmt.where(
                catalog.Modpack.id.in_(
                    select(account.modpack_and_author.c.modpack_id).where(
                        account.modpack_and_author.c.user_id == author_id
                    )
                )
            )
        if game_id is not None:
            stmt = stmt.where(catalog.Modpack.game == game_id)
        if public in (0, 1, 2):
            stmt = stmt.where(catalog.Modpack.public == int(public))
        if adult in (0, 1):
            stmt = stmt.where(catalog.Modpack.adult == bool(adult))
        if source:
            stmt = stmt.where(catalog.Modpack.source.in_(source))
        if source_ids_normalized:
            stmt = stmt.where(catalog.Modpack.source_id.in_(source_ids_normalized))
        if name:
            stmt = stmt.where(catalog.Modpack.name.ilike(f"%{name.strip()}%"))

        if show_not_public:
            candidate_ids = [
                int(modpack_id)
                for modpack_id in (
                    await session.execute(
                        stmt.with_only_columns(catalog.Modpack.id).order_by(None)
                    )
                ).scalars().all()
            ]
            if not candidate_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            allowed_ids = await tools.access_modpacks(
                request=request,
                modpack_ids=candidate_ids,
                author_id=author_id,
                catalog=True,
                check_mode=True,
            )
            if not allowed_ids:
                return make_list_response([], page=page, page_size=page_size, total=0)

            stmt = stmt.where(catalog.Modpack.id.in_(allowed_ids))
        else:
            stmt = stmt.where(catalog.Modpack.public == 0)

        filtered = stmt.order_by(None).subquery()
        count_stmt = select(func.count()).select_from(filtered)
        total = int((await session.scalar(count_stmt)) or 0)
        rows = (
            await session.execute(
                stmt.order_by(sort_clause, catalog.Modpack.id.asc())
                .offset(page * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        authors = await _load_modpack_authors(session, [int(row.id) for row in rows])

    items = [
        _serialize_modpack(row, authors=authors.get(int(row.id))).model_dump(
            mode="json",
            exclude_none=True,
        )
        for row in rows
    ]
    return make_list_response(items, page=page, page_size=page_size, total=total)


@router.get(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Get modpack",
    description="Returns a modpack by ID, including its authors and current vote state when available.",
    status_code=200,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Modpack resource.",
    responses={404: MODPACK_NOT_FOUND_RESPONSE},
)
async def get_modpack(
    request: Request,
    modpack_id: int,
) -> ModpackRead:
    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        if row.public > 0 or int(getattr(row, "condition", 0) or 0) != 0:
            await tools.access_modpacks(request=request, modpack_ids=[modpack_id])

        authors = await _load_modpack_authors(session, [modpack_id])

    current_vote = await _load_modpack_current_vote(request, modpack_id)
    return _serialize_modpack(
        row,
        authors=authors.get(modpack_id),
        current_vote=current_vote,
    )


@router.put(
    "/modpacks/{modpack_id}/rating",
    tags=["Modpack"],
    summary="Rate modpack",
    description=(
        "Sets the current user's vote for a modpack. Votes adjust the modpack rating by one point "
        "per step and propagate reputation changes to all listed authors."
    ),
    status_code=200,
    response_model=ModpackRatingRead,
    response_model_exclude_none=True,
    response_description="Updated modpack rating.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
    },
)
async def put_modpack_rating(
    request: Request,
    modpack_id: int,
    payload: RatingVoteUpsert,
) -> ModpackRatingRead:
    vote_access = await tools.access_vote_for_reputation(request=request)
    if not vote_access.vote_for_reputation.value:
        _raise_vote_right_denied(request, vote_access.vote_for_reputation)

    async with account.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

        await tools.access_modpacks(request=request, modpack_ids=[modpack_id], catalog=True)

        rating = await reputation.apply_modpack_vote(
            session,
            voter_id=int(vote_access.owner_id),
            modpack=modpack,
            value=int(payload.value),
        )
        await session.commit()
        return ModpackRatingRead(modpack_id=modpack_id, rating=rating)


@router.post(
    "/modpacks",
    tags=["Modpack"],
    summary="Create modpack",
    description="Creates a new modpack draft or published entry.",
    status_code=201,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Created modpack resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: GAME_NOT_FOUND_RESPONSE,
        409: MODPACK_CONFLICT_RESPONSE,
    },
)
async def create_modpack(
    response: Response,
    request: Request,
    payload: ModpackCreate,
) -> ModpackRead:
    access_result = await tools.access_modpack_add(request=request)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    required_right = access_result.anonymous_add if payload.without_author else access_result.add
    if not required_right.value:
        raise standarts.ForbiddenError(
            detail=required_right.reason,
            instance=str(request.url),
            context={"reason_code": required_right.reason_code},
        )

    candidate_source_id = _normalize_source_id(payload.source_id)
    if payload.game_id is not None and not await tools.check_game_exists(int(payload.game_id)):
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Game not found.",
            code="GAME_NOT_FOUND",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        if candidate_source_id is not None and payload.source != "local":
            existing = await session.scalar(
                select(catalog.Modpack.id).where(
                    catalog.Modpack.source == payload.source,
                    catalog.Modpack.source_id == candidate_source_id,
                    catalog.Modpack.condition == 0,
                )
            )
            if existing is not None:
                raise standarts.StandardAPIError(
                    status_code=409,
                    title="Conflict",
                    detail="Modpack source already exists.",
                    code="MODPACK_SOURCE_ALREADY_EXISTS",
                    instance=str(request.url),
                    context={"source": payload.source, "source_id": candidate_source_id},
                )

        modpack = catalog.Modpack(
            name=payload.name,
            short_description=payload.short_description,
            description=payload.description,
            condition=0,
            public=payload.public,
            adult=payload.adult,
            rating=0,
            downloads=0,
            date_creation=datetime.datetime.now(),
            date_edit=datetime.datetime.now(),
            source=payload.source,
            source_id=candidate_source_id,
            git_url=payload.git_url,
            game=payload.game_id,
        )
        session.add(modpack)
        await session.flush()

        authors: dict[int, dict[str, bool]] | None = None
        if not payload.without_author and access_result.owner_id >= 0:
            await session.execute(
                insert(account.modpack_and_author).values(
                    modpack_id=modpack.id,
                    user_id=access_result.owner_id,
                    owner=True,
                )
            )
            authors = {int(access_result.owner_id): {"owner": True}}

        await session.commit()
        response.headers["Location"] = f"/modpacks/{modpack.id}"
        return _serialize_modpack(modpack, authors=authors)


@router.patch(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Update modpack",
    description="Updates an existing modpack.",
    status_code=200,
    response_model=ModpackRead,
    response_model_exclude_none=True,
    response_description="Updated modpack resource.",
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
        409: MODPACK_CONFLICT_RESPONSE,
    },
)
async def patch_modpack(
    request: Request,
    modpack_id: int,
    payload: ModpackPatch,
) -> ModpackRead:
    await tools.access_modpacks(request=request, modpack_ids=[modpack_id], edit=True)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name", "source", "public", "adult"),
        detail="Modpack patch fields cannot be null.",
    )

    if "name" in data:
        if len(str(data["name"])) > LIMITS.mod.name_max:
            raise standarts.PayloadTooLargeError(
                detail="Name is too long.",
                instance=str(request.url),
            )
        if len(str(data["name"])) < LIMITS.mod.name_min:
            raise standarts.PreconditionRequiredError(
                detail="Name is too short.",
                instance=str(request.url),
            )
    if "short_description" in data and len(re.sub(r"\s+", " ", str(data["short_description"]))) > LIMITS.mod.short_desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Short description is too long.",
            instance=str(request.url),
        )
    if "description" in data and len(re.sub(r"\s+", " ", str(data["description"]))) > LIMITS.mod.desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Description is too long.",
            instance=str(request.url),
        )

    if "game_id" in data and data["game_id"] is not None and not await tools.check_game_exists(int(data["game_id"])):
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Game not found.",
            code="GAME_NOT_FOUND",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        current_source = str(getattr(row, "source", "local") or "local")
        current_source_id = _normalize_source_id(getattr(row, "source_id", None))
        if "source" in data or "source_id" in data:
            candidate_source = str(data.get("source", current_source))
            candidate_source_id = _normalize_source_id(data.get("source_id", current_source_id))
            if candidate_source_id is not None and candidate_source != "local":
                existing = await session.scalar(
                    select(catalog.Modpack.id).where(
                        catalog.Modpack.id != modpack_id,
                        catalog.Modpack.source == candidate_source,
                        catalog.Modpack.source_id == candidate_source_id,
                        catalog.Modpack.condition == 0,
                    )
                )
                if existing is not None:
                    raise standarts.StandardAPIError(
                        status_code=409,
                        title="Conflict",
                        detail="Modpack source already exists.",
                        code="MODPACK_SOURCE_ALREADY_EXISTS",
                        instance=str(request.url),
                        context={"source": candidate_source, "source_id": candidate_source_id},
                    )
            row.source = candidate_source
            row.source_id = candidate_source_id

        if "git_url" in data:
            row.git_url = data["git_url"] if data["git_url"] is None else str(data["git_url"])

        for key, value in data.items():
            if key == "game_id":
                row.game = int(value) if value is not None else None
            elif key == "public":
                row.public = int(value)
            elif key == "adult":
                row.adult = bool(value)
            elif key == "name":
                row.name = str(value)
            elif key == "short_description":
                row.short_description = value if value is None else str(value)
            elif key == "description":
                row.description = value if value is None else str(value)

        row.date_edit = datetime.datetime.now()
        authors = await _load_modpack_authors(session, [modpack_id])
        await session.commit()
        return _serialize_modpack(row, authors=authors.get(modpack_id))


@router.delete(
    "/modpacks/{modpack_id}",
    tags=["Modpack"],
    summary="Delete modpack",
    description="Deletes a modpack and its author links.",
    status_code=204,
    responses={
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: MODPACK_NOT_FOUND_RESPONSE,
    },
)
async def delete_modpack(request: Request, modpack_id: int) -> Response:
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.delete.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.delete.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.delete.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.Modpack, modpack_id)
        if row is None:
            _raise_modpack_not_found(request)

        await session.execute(
            delete(account.modpack_and_author).where(
                account.modpack_and_author.c.modpack_id == modpack_id
            )
        )
        await session.execute(delete(catalog.Modpack).where(catalog.Modpack.id == modpack_id))
        await session.commit()

    return Response(status_code=204)


@router.put(
    "/modpacks/{modpack_id}/authors/{author_id}",
    tags=["Modpack", "Author"],
    summary="Set modpack author",
    description="Creates or updates a modpack author assignment.",
    status_code=204,
)
async def put_modpack_author(request: Request, modpack_id: int, author_id: int, payload: ModAuthorUpsert):
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
        author_id=author_id,
        mode=payload.owner,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.edit.authors.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.edit.authors.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.edit.authors.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.modpack_and_author.c.owner).where(
                account.modpack_and_author.c.modpack_id == modpack_id,
                account.modpack_and_author.c.user_id == author_id,
            )
        )

        if payload.owner:
            await session.execute(
                update(account.modpack_and_author)
                .where(account.modpack_and_author.c.modpack_id == modpack_id)
                .where(account.modpack_and_author.c.user_id != author_id)
                .values(owner=False)
            )

        if relation_owner is None:
            await session.execute(
                insert(account.modpack_and_author).values(
                    modpack_id=modpack_id,
                    user_id=author_id,
                    owner=bool(payload.owner),
                )
            )
        else:
            await session.execute(
                update(account.modpack_and_author)
                .where(account.modpack_and_author.c.modpack_id == modpack_id)
                .where(account.modpack_and_author.c.user_id == author_id)
                .values(owner=bool(payload.owner))
            )

        await session.commit()

    return Response(status_code=204)


@router.delete(
    "/modpacks/{modpack_id}/authors/{author_id}",
    tags=["Modpack", "Author"],
    summary="Remove modpack author",
    description="Removes a modpack author assignment.",
    status_code=204,
)
async def delete_modpack_author(request: Request, modpack_id: int, author_id: int):
    modpack_access = await tools.access_modpack_action(
        request=request,
        modpack_id=modpack_id,
        author_id=author_id,
        mode=False,
    )
    if not modpack_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not modpack_access.edit.authors.value:
        raise standarts.ForbiddenError(
            detail=modpack_access.edit.authors.reason,
            instance=str(request.url),
            context={"reason_code": modpack_access.edit.authors.reason_code},
        )

    async with catalog.AsyncSessionLocal() as session:
        modpack = await session.get(catalog.Modpack, modpack_id)
        if modpack is None:
            _raise_modpack_not_found(request)

    async with account.AsyncSessionLocal() as session:
        user = await session.get(account.Account, author_id)
        if user is None:
            raise standarts.NotFoundError(detail="User not found", instance=str(request.url))

        relation_owner = await session.scalar(
            select(account.modpack_and_author.c.owner).where(
                account.modpack_and_author.c.modpack_id == modpack_id,
                account.modpack_and_author.c.user_id == author_id,
            )
        )

        if relation_owner is not None:
            await session.execute(
                delete(account.modpack_and_author).where(
                    account.modpack_and_author.c.modpack_id == modpack_id,
                    account.modpack_and_author.c.user_id == author_id,
                )
            )

        await session.commit()

    return Response(status_code=204)
