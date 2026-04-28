"""Genre REST routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import (
    ensure_fields_not_none,
    ensure_non_empty_patch,
    make_list_response,
)
from open_workshop_manager.api_models import GenreCreate, GenreListResponse, GenrePatch, GenreRead
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()

GENRE_NOT_FOUND_RESPONSE = standarts.response_spec(
    standarts.build_problem(
        404,
        title="Not Found",
        detail="Genre not found.",
        code="GENRE_NOT_FOUND",
    ),
    "Genre not found.",
)


def _serialize_genre(genre: catalog.Genre) -> GenreRead:
    return GenreRead(id=int(genre.id), name=str(genre.name))


@router.get(
    "/genres",
    tags=["Genre"],
    summary="List genres",
    description="Returns a paginated list of genres with optional name and ID filters.",
    status_code=200,
    response_model=GenreListResponse,
    response_model_exclude_none=True,
    response_description="Paginated genre list.",
)
async def list_genres(
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        ge=LIMITS.page.min,
        le=LIMITS.page.max,
        description="Maximum number of genres to return per page.",
    ),
    page: int = Query(0, ge=0, description="Zero-based page index."),
    name: str | None = Query(
        default=None,
        max_length=LIMITS.genre.name_max,
        description="Case-insensitive substring filter for the genre name.",
    ),
    ids: list[int] = Query(default_factory=list, description="Limit results to these genre IDs."),
):
    async with catalog.AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(catalog.Genre)
        list_stmt = select(catalog.Genre)

        if name:
            condition = catalog.Genre.name.ilike(f"%{name}%")
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)

        if ids:
            count_stmt = count_stmt.where(catalog.Genre.id.in_(ids))
            list_stmt = list_stmt.where(catalog.Genre.id.in_(ids))

        total = int((await session.scalar(count_stmt)) or 0)
        offset = page * page_size
        rows = (await session.execute(list_stmt.offset(offset).limit(page_size))).scalars().all()

    items = [_serialize_genre(row) for row in rows]
    return make_list_response(
        [item.model_dump(mode="json", exclude_none=True) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/genres/{genre_id}",
    tags=["Genre"],
    summary="Get genre",
    description="Returns a single genre by ID.",
    status_code=200,
    response_model=GenreRead,
    response_model_exclude_none=True,
    response_description="Genre resource.",
    responses={404: GENRE_NOT_FOUND_RESPONSE},
)
async def get_genre(request: Request, genre_id: int) -> GenreRead:
    async with catalog.AsyncSessionLocal() as session:
        genre = await session.get(catalog.Genre, genre_id)

    if genre is None:
        raise standarts.StandardAPIError(
            status_code=404,
            title="Not Found",
            detail="Genre not found.",
            code="GENRE_NOT_FOUND",
            instance=str(request.url),
        )

    return _serialize_genre(genre)


@router.post(
    "/genres",
    tags=["Genre"],
    summary="Create genre",
    description="Creates a new genre. Admin privileges are required.",
    status_code=201,
    response_model=GenreRead,
    response_model_exclude_none=True,
    response_description="Created genre resource.",
    responses={403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC},
)
async def create_genre(response: Response, request: Request, payload: GenreCreate) -> GenreRead:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        genre = catalog.Genre(name=payload.name)
        session.add(genre)
        await session.flush()
        await session.commit()
        response.headers["Location"] = f"/genres/{genre.id}"
        return _serialize_genre(genre)


@router.patch(
    "/genres/{genre_id}",
    tags=["Genre"],
    summary="Update genre",
    description="Updates the genre name. Admin privileges are required.",
    status_code=200,
    response_model=GenreRead,
    response_model_exclude_none=True,
    response_description="Updated genre resource.",
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: GENRE_NOT_FOUND_RESPONSE,
    },
)
async def patch_genre(
    response: Response,
    request: Request,
    genre_id: int,
    payload: GenrePatch,
) -> GenreRead:
    await tools.access_admin(request=request)

    data = payload.model_dump(exclude_unset=True)
    ensure_non_empty_patch(data)
    ensure_fields_not_none(
        request,
        data,
        ("name",),
        detail="Genre name cannot be null.",
    )

    async with catalog.AsyncSessionLocal() as session:
        genre = await session.get(catalog.Genre, genre_id)
        if genre is None:
            raise standarts.StandardAPIError(
                status_code=404,
                title="Not Found",
                detail="Genre not found.",
                code="GENRE_NOT_FOUND",
                instance=str(request.url),
            )

        for key, value in data.items():
            setattr(genre, key, value)
        await session.commit()
        return _serialize_genre(genre)


@router.delete(
    "/genres/{genre_id}",
    tags=["Genre"],
    summary="Delete genre",
    description="Deletes a genre and detaches it from all games. Admin privileges are required.",
    status_code=204,
    responses={
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: GENRE_NOT_FOUND_RESPONSE,
    },
)
async def delete_genre(request: Request, genre_id: int) -> Response:
    await tools.access_admin(request=request)

    async with catalog.AsyncSessionLocal() as session:
        genre = await session.get(catalog.Genre, genre_id)
        if genre is None:
            raise standarts.StandardAPIError(
                status_code=404,
                title="Not Found",
                detail="Genre not found.",
                code="GENRE_NOT_FOUND",
                instance=str(request.url),
            )

        await session.execute(
            catalog.game_genres.delete().where(catalog.game_genres.c.genre_id == genre_id)
        )
        await session.execute(delete(catalog.Genre).where(catalog.Genre.id == genre_id))
        await session.commit()

    return Response(status_code=204)
