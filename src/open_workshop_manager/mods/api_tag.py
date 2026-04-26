"""Tag management routes."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete

from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


class TagCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=LIMITS.tag.name_max)


class TagUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=LIMITS.tag.name_max)


@router.post(
    MAIN_URL + "/tags",
    tags=["Tag"],
    summary="Добавление тега",
    status_code=202,
    responses={
        202: {
            "description": "Возвращает ID добавленного тега",
            "content": {"application/json": {"example": 1}},
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def add_tag(
    response: Response,
    request: Request,
    payload: TagCreatePayload,
):
    access_result = await tools.access_admin(request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            new_tag = catalog.Tag(name=payload.name)
            session.add(new_tag)
            await session.flush()
            tag_id = int(new_tag.id)  # Получаем ID последней вставленной строки

            await session.commit()

        return JSONResponse(status_code=202, content=tag_id)  # Возвращаем значение `id`
    else:
        return access_result


@router.patch(
    MAIN_URL + "/tags/{tag_id}",
    tags=["Tag"],
    summary="Редактирование тега",
    status_code=202,
    responses={
        202: {
            "description": "Успешно изменено.",
            "content": {"application/json": {"example": "Complite"}},
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
        404: {
            "description": "Тег не найден.",
            "content": {"text/plain": {"example": "The element does not exist."}},
        },
        418: {
            "description": "Пустой запрос *(нужно запросить что-то отредактировать)*.",
            "content": {"text/plain": {"example": "The request is empty"}},
        },
    },
)
async def edit_tag(
    response: Response,
    request: Request,
    tag_id: int,
    payload: TagUpdatePayload,
):
    access_result = await tools.access_admin(request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            tag = await session.get(catalog.Tag, tag_id)
            if not tag:
                raise standarts.NotFoundError(
                    detail="The element does not exist.",
                    instance=str(request.url),
                )

            data_edit = {}
            if payload.name:
                data_edit["name"] = payload.name

            if len(data_edit) <= 0:
                raise standarts.RequestRejectedError(
                    detail="The request is empty",
                    instance=str(request.url),
                )

            for key, value in data_edit.items():
                setattr(tag, key, value)
            await session.commit()
        return PlainTextResponse(status_code=202, content="Complite")
    else:
        return access_result


@router.delete(
    MAIN_URL + "/tags/{tag_id}",
    tags=["Tag"],
    summary="Удаление тега",
    status_code=202,
    responses={
        202: {
            "description": "Успешно удалено.",
            "content": {"text/plain": {"example": "Complite"}},
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.ADMIN_FORBIDDEN_RESPONSE_SPEC,
    },
)
async def delete_tag(
    response: Response,
    request: Request,
    tag_id: int,
):
    access_result = await tools.access_admin(request=request)

    if access_result is True:
        async with catalog.AsyncSessionLocal() as session:
            delete_game = delete(catalog.Tag).where(catalog.Tag.id == tag_id)

            delete_mods_tags_association = catalog.mods_tags.delete().where(
                catalog.mods_tags.c.tag_id == tag_id
            )
            delete_game_tags_association = catalog.allowed_mods_tags.delete().where(
                catalog.allowed_mods_tags.c.tag_id == tag_id
            )

            # Выполнение операции DELETE
            await session.execute(delete_game)
            await session.execute(delete_mods_tags_association)
            await session.execute(delete_game_tags_association)
            await session.commit()
        return PlainTextResponse(status_code=202, content="Complite")
    else:
        return access_result
