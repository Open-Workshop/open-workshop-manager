"""Mod management routes."""

import logging
import re
import uuid
from datetime import datetime
from typing import Optional, cast
from urllib.parse import quote, urlparse

from fastapi import (
    APIRouter,
    Form,
    Header,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import aliased

from open_workshop_manager import settings as config
from open_workshop_manager import standarts, tools
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog
from open_workshop_manager.sql_logic import sql_statistics as statistics

logger = logging.getLogger(__name__)

ALLOWED_FILENAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)

routers_edit_mod_response = {
    411: {
        "description": "Не достингнут минимальный размер (название мода).",
        "content": {"text/plain": {"example": "Название слишком короткое!"}},
    },
    413: {
        "description": "Слишком длинное значение параметра(ов): короткое/полное описание, название, размер файла.",
        "content": {
            "application/json": {
                "example": {"message": "... слишком длинное!", "error_id": 1}
            }
        },
    },
    500: {
        "description": "Во время передачи файла на Storage сервер произошла ошибка.",
        "content": {"text/plain": {"example": "Не удалось загрузить файл!"}},
    },
}


router = APIRouter()


def _bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


@router.post(
    MAIN_URL + "/mods/from-file",
    tags=["Mod"],
    summary="Добавление мода (файл напрямую на Storage)",
    status_code=307,
    responses={
        307: {"description": "Перенаправление на Storage для загрузки"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        411: routers_edit_mod_response[411],
        412: {
            "description": "Неккоректный ID выбранной игры ИЛИ source-связка уже занята.",
            "content": {"text/plain": {"example": "Такой игры не существует!"}},
        },
        413: routers_edit_mod_response[413],
        500: routers_edit_mod_response[500],
    },
)
async def add_mod_from_file(
    response: Response,
    request: Request,
    without_author: bool = Form(
        False,
        description="Указывать ли авторство мода. Для выбора должны быть админ права.",
    ),
    mod_name: str = Form(
        ..., description="Название мода", max_length=LIMITS.mod.name_max
    ),
    mod_short_description: str = Form(
        "", description="Короткое описание мода.", max_length=LIMITS.mod.short_desc_max
    ),
    mod_description: str = Form(
        "", description="Полное описание мода.", max_length=LIMITS.mod.desc_max
    ),
    mod_source: str = Form(
        "local", description="Источник мода.", max_length=LIMITS.mod.source_max
    ),
    mod_source_id: int = Form(-1, description="ID мода в первоисточнике."),
    mod_game: int = Form(..., description="ID игры-владельца."),
    mod_public: int = Form(
        ..., description="Публичный ли мод? 0-да, 1-только по ссылке, 2-нет."
    ),
    pack_format: str = Form("zip", description="Формат упаковки."),
    pack_level: int = Form(3, description="Степень сжатия (0-9)."),
):
    access_result = await tools.access_mod_add(
        request=request,
    )
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    required_right = access_result.anonymous_add if without_author else access_result.add
    if not required_right.value:
        raise standarts.ForbiddenError(
            detail=required_right.reason,
            instance=str(request.url),
            context={"reason_code": required_right.reason_code},
        )

    user_id = access_result.owner_id

    logger.debug(
        "Mod short description length=%s", len(mod_short_description or "")
    )
    if len(re.sub(r"\s+", " ", mod_short_description)) > LIMITS.mod.short_desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Короткое описание слишком длинное!",
            instance=str(request.url),
        )
    elif len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Описание слишком длинное!",
            instance=str(request.url),
        )
    elif len(mod_name) > LIMITS.mod.name_max:
        raise standarts.PayloadTooLargeError(
            detail="Название слишком длинное!",
            instance=str(request.url),
        )
    elif len(mod_name) < LIMITS.mod.name_min:
        raise standarts.PreconditionRequiredError(
            detail="Название слишком короткое!",
            instance=str(request.url),
        )
    elif not await tools.check_game_exists(mod_game):
        raise standarts.PreconditionFailedError(
            detail="Такой игры не существует!",
            instance=str(request.url),
        )

    if pack_format != "zip":
        raise standarts.BadRequestError(
            detail="Unsupported format",
            instance=str(request.url),
        )

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    if mod_public not in [0, 1, 2]:
        mod_public = 0

    async with catalog.AsyncSessionLocal() as session:
        if mod_source_id > 0 and mod_source != "local":
            async with catalog.AsyncSessionLocal() as tsession:
                source_conflicts = (
                    await tsession.execute(
                        select(catalog.Mod).where(
                            catalog.Mod.source == mod_source,
                            catalog.Mod.source_id == mod_source_id,
                        )
                    )
                ).scalars().all()

            for conflict_mod in source_conflicts:
                # Игнорируем конфликт только для незавершенного мода того же автора.
                if conflict_mod.condition != 0:
                    async with account.AsyncSessionLocal() as asession:
                        same_author = await asession.scalar(
                            select(account.mod_and_author.c.user_id).where(
                                account.mod_and_author.c.mod_id == conflict_mod.id,
                                account.mod_and_author.c.user_id == user_id,
                            )
                        )
                    if same_author is not None:
                        continue

                raise standarts.PreconditionFailedError(
                    detail="Такая source-связка уже существует!",
                    instance=str(request.url),
                )

        new_mod = catalog.Mod(
            name=mod_name,
            short_description=mod_short_description,
            description=mod_description,
            size=0,
            condition=1,
            public=mod_public,
            date_creation=datetime.now(),
            date_update_file=datetime.now(),
            date_edit=datetime.now(),
            source=mod_source,
            downloads=0,
            game=mod_game,
        )
        if mod_source_id > 0 and mod_source != "local":
            new_mod.source_id = mod_source_id

        session.add(new_mod)
        await session.flush()
        rid = new_mod.id
        await session.commit()

    if not without_author:
        async with account.AsyncSessionLocal() as session:
            await session.execute(
                account.mod_and_author.insert().values(
                    mod_id=rid, user_id=user_id, owner=True
                )
            )
            await session.commit()

    try:
        pack_level = int(pack_level)
    except (TypeError, ValueError):
        pack_level = 3
    pack_level = max(0, min(pack_level, 9))
    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900
    payload = {
        "job_id": job_id,
        "mod_id": rid,
        "pack_format": pack_format,
        "pack_level": pack_level,
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    transfer_url = (
        f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    )

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept", "") or "")
    )

    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "mod_id": rid,
                "transfer_url": transfer_url,
                "ws_url": f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}",
            },
        )

    response = RedirectResponse(url=transfer_url, status_code=307)
    response.headers["X-Upload-Job"] = job_id
    response.headers["X-Progress-WS"] = f"{config.STORAGE_URL}/transfer/ws/{job_id}"
    return response


@router.post(
    MAIN_URL + "/mods/{mod_id}/file",
    tags=["Mod"],
    summary="Обновление файла мода (файл напрямую на Storage)",
    status_code=307,
    responses={
        307: {"description": "Перенаправление на Storage для загрузки"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Мод не найден."},
        411: routers_edit_mod_response[411],
        413: routers_edit_mod_response[413],
        500: routers_edit_mod_response[500],
    },
)
async def update_mod_file(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода для обновления файла."),
    pack_format: str = Form("zip", description="Формат упаковки."),
    pack_level: int = Form(3, description="Степень сжатия (0-9)."),
):
    access_result = await tools.access_mods(request=request, mods_ids=mod_id, edit=True)
    if access_result is not True:
        return access_result

    async with catalog.AsyncSessionLocal() as session:
        mod_exists = await session.get(catalog.Mod, mod_id)
    if not mod_exists:
        raise standarts.NotFoundError(
            detail="Mod not found",
            instance=str(request.url),
        )

    if pack_format != "zip":
        raise standarts.BadRequestError(
            detail="Unsupported format",
            instance=str(request.url),
        )

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    try:
        pack_level = int(pack_level)
    except (TypeError, ValueError):
        pack_level = 3
    pack_level = max(0, min(pack_level, 9))

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900
    payload = {
        "job_id": job_id,
        "mod_id": mod_id,
        "pack_format": pack_format,
        "pack_level": pack_level,
        "update_only": True,
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    transfer_url = f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept", "") or "")
    )
    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "mod_id": mod_id,
                "transfer_url": transfer_url,
                "ws_url": f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}",
            },
        )

    response = RedirectResponse(url=transfer_url, status_code=307)
    response.headers["X-Upload-Job"] = job_id
    response.headers["X-Progress-WS"] = f"{config.STORAGE_URL}/transfer/ws/{job_id}"
    return response


@router.post(
    MAIN_URL + "/mods/from-url",
    tags=["Mod"],
    summary="Добавление мода по ссылке",
    status_code=307,
    responses={
        307: {"description": "Перенаправление на Storage для загрузки"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        411: routers_edit_mod_response[411],
        412: {
            "description": "Неккоректный ID выбранной игры ИЛИ source-связка уже занята.",
            "content": {"text/plain": {"example": "Такой игры не существует!"}},
        },
        413: routers_edit_mod_response[413],
        500: routers_edit_mod_response[500],
    },
)
async def add_mod_from_url(
    response: Response,
    request: Request,
    without_author: bool = Form(
        False,
        description="Указывать ли авторство мода. Для выбора должны быть админ права.",
    ),
    mod_name: str = Form(
        ..., description="Название мода", max_length=LIMITS.mod.name_max
    ),
    mod_short_description: str = Form(
        "", description="Короткое описание мода.", max_length=LIMITS.mod.short_desc_max
    ),
    mod_description: str = Form(
        "", description="Полное описание мода.", max_length=LIMITS.mod.desc_max
    ),
    mod_source: str = Form(
        "local", description="Источник мода.", max_length=LIMITS.mod.source_max
    ),
    mod_source_id: int = Form(-1, description="ID мода в первоисточнике."),
    mod_game: int = Form(..., description="ID игры-владельца."),
    mod_public: int = Form(
        ..., description="Публичный ли мод? 0-да, 1-только по ссылке, 2-нет."
    ),
    mod_url: str = Form(..., description="Прямая ссылка на файл мода."),
    pack_format: str = Form("zip", description="Формат упаковки."),
    pack_level: int = Form(3, description="Степень сжатия (0-9)."),
):
    access_result = await tools.access_mod_add(
        request=request,
    )
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    required_right = access_result.anonymous_add if without_author else access_result.add
    if not required_right.value:
        raise standarts.ForbiddenError(
            detail=required_right.reason,
            instance=str(request.url),
            context={"reason_code": required_right.reason_code},
        )

    user_id = access_result.owner_id

    logger.debug(
        "Mod short description length=%s", len(mod_short_description or "")
    )
    if len(re.sub(r"\s+", " ", mod_short_description)) > LIMITS.mod.short_desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Короткое описание слишком длинное!",
            instance=str(request.url),
        )
    elif len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
        raise standarts.PayloadTooLargeError(
            detail="Описание слишком длинное!",
            instance=str(request.url),
        )
    elif len(mod_name) > LIMITS.mod.name_max:
        raise standarts.PayloadTooLargeError(
            detail="Название слишком длинное!",
            instance=str(request.url),
        )
    elif len(mod_name) < LIMITS.mod.name_min:
        raise standarts.PreconditionRequiredError(
            detail="Название слишком короткое!",
            instance=str(request.url),
        )
    elif not await tools.check_game_exists(mod_game):
        raise standarts.PreconditionFailedError(
            detail="Такой игры не существует!",
            instance=str(request.url),
        )

    parsed = urlparse(mod_url)
    if parsed.scheme not in {"http", "https"}:
        raise standarts.PreconditionRequiredError(
            detail="Некорректная ссылка!",
            instance=str(request.url),
        )

    if pack_format != "zip":
        raise standarts.BadRequestError(
            detail="Unsupported format",
            instance=str(request.url),
        )

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    if mod_public not in [0, 1, 2]:
        mod_public = 0

    async with catalog.AsyncSessionLocal() as session:
        if mod_source_id > 0 and mod_source != "local":
            async with catalog.AsyncSessionLocal() as tsession:
                source_conflict = await tsession.scalar(
                    select(catalog.Mod).where(
                        catalog.Mod.source == mod_source,
                        catalog.Mod.source_id == mod_source_id,
                    )
                )
            if source_conflict:
                raise standarts.PreconditionFailedError(
                    detail="Такая source-связка уже существует!",
                    instance=str(request.url),
                )

        new_mod = catalog.Mod(
            name=mod_name,
            short_description=mod_short_description,
            description=mod_description,
            size=0,
            condition=1,
            public=mod_public,
            date_creation=datetime.now(),
            date_update_file=datetime.now(),
            date_edit=datetime.now(),
            source=mod_source,
            downloads=0,
            game=mod_game,
        )
        if mod_source_id > 0 and mod_source != "local":
            new_mod.source_id = mod_source_id

        session.add(new_mod)
        await session.flush()
        rid = new_mod.id
        await session.commit()

    if not without_author:
        async with account.AsyncSessionLocal() as session:
            await session.execute(
                account.mod_and_author.insert().values(
                    mod_id=rid, user_id=user_id, owner=True
                )
            )
            await session.commit()

    try:
        pack_level = int(pack_level)
    except (TypeError, ValueError):
        pack_level = 3
    pack_level = max(0, min(pack_level, 9))
    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900
    payload = {
        "job_id": job_id,
        "mod_id": rid,
        "download_url": mod_url,
        "pack_format": pack_format,
        "pack_level": pack_level,
    }
    token = tools.create_transfer_jwt(payload, audience="storage", ttl_seconds=ttl_seconds)
    if not token:
        raise standarts.InternalServerError(
            detail="JWT secret missing",
            instance=str(request.url),
        )

    redirect_url = (
        f"{config.STORAGE_URL}/transfer/start?token={quote(token)}&job_id={job_id}"
    )

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept", "") or "")
    )

    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "mod_id": rid,
                "transfer_url": redirect_url,
                "ws_url": f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}",
            },
        )

    response = RedirectResponse(url=redirect_url, status_code=307)
    response.headers["X-Upload-Job"] = job_id
    response.headers["X-Progress-WS"] = f"{config.STORAGE_URL}/transfer/ws/{job_id}"
    return response


async def _storage_transfer_complete_img(
    request: Request, payload: dict
) -> PlainTextResponse:
    status = payload.get("status")
    job_id = str(payload.get("job_id") or "")
    callback_action = str(payload.get("callback_action") or "")
    storage_type = str(payload.get("storage_type") or "")
    target_path = str(payload.get("target_path") or "")
    callback_context = payload.get("callback_context")
    if not isinstance(callback_context, dict):
        callback_context = {}
    resource_id_cleanup = 0
    if callback_action == "resource_add":
        try:
            resource_id_cleanup_raw = cast(
                int | str | None, callback_context.get("resource_id")
            )
            if resource_id_cleanup_raw is not None:
                resource_id_cleanup = int(resource_id_cleanup_raw)
        except (TypeError, ValueError):
            resource_id_cleanup = 0

    if not job_id or not callback_action or not target_path:
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )
    if storage_type not in {"avatar", "resource"}:
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )
    if callback_action not in {"avatar_set", "resource_add", "resource_edit"}:
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )

    if callback_action == "avatar_set" and storage_type != "avatar":
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )
    if callback_action in {"resource_add", "resource_edit"} and storage_type != "resource":
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )

    if status != "success":
        logger.warning(
            "transfer img failed job_id=%s action=%s status=%s",
            job_id,
            callback_action,
            status,
        )
        if resource_id_cleanup > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(
                        catalog.Resource.id == resource_id_cleanup
                    )
                )
                await session.commit()
        return PlainTextResponse(status_code=202, content="Transfer failed")

    move_start = datetime.now()
    try:
        move_code, move_payload, move_ok = await tools.storage_job_move(
            job_id=job_id, type=storage_type, path=target_path
        )
    except Exception:
        logger.exception(
            "transfer img move exception job_id=%s action=%s path=%s",
            job_id,
            callback_action,
            target_path,
        )
        if resource_id_cleanup > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(
                        catalog.Resource.id == resource_id_cleanup
                    )
                )
                await session.commit()
        raise standarts.GatewayTimeoutError(
            detail="Move timeout",
            instance=str(request.url),
        )
    if not move_ok:
        logger.warning(
            "transfer img move failed job_id=%s action=%s status=%s body=%s",
            job_id,
            callback_action,
            move_code,
            move_payload,
        )
        if resource_id_cleanup > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(
                        catalog.Resource.id == resource_id_cleanup
                    )
                )
                await session.commit()
        raise standarts.InternalServerError(
            detail="Move failed",
            instance=str(request.url),
        )
    move_duration = (datetime.now() - move_start).total_seconds()
    logger.info(
        "transfer img move done job_id=%s action=%s type=%s duration=%.2fs",
        job_id,
        callback_action,
        storage_type,
        move_duration,
    )
    resource_size = None
    if isinstance(move_payload, dict):
        raw_resource_size = cast(int | str | None, move_payload.get("final_bytes"))
        try:
            if raw_resource_size is None:
                parsed_resource_size = None
            else:
                parsed_resource_size = int(raw_resource_size)
        except (TypeError, ValueError):
            parsed_resource_size = None
        if parsed_resource_size is not None and parsed_resource_size > 0:
            resource_size = parsed_resource_size

    if callback_action == "avatar_set":
        user_id_raw = cast(int | str | None, callback_context.get("user_id"))
        if user_id_raw is None:
            raise standarts.BadRequestError(
                detail="Invalid payload",
                instance=str(request.url),
            )
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            raise standarts.BadRequestError(
                detail="Invalid payload",
                instance=str(request.url),
            )

        async with account.AsyncSessionLocal() as session:
            user = await session.get(account.Account, user_id)
            if not user:
                await tools.storage_file_delete(type="avatar", path=target_path)
                raise standarts.NotFoundError(
                    detail="User not found",
                    instance=str(request.url),
                )
            old_avatar_url = str(user.avatar_url or "")
            user.avatar_url = "local.webp"
            await session.commit()

        if old_avatar_url.startswith("local"):
            try:
                old_ext = old_avatar_url.split(".", 1)[1]
            except IndexError:
                old_ext = "webp"
            old_path = f"{user_id}.{old_ext}"
            if old_path != target_path:
                await tools.storage_file_delete(type="avatar", path=old_path)
        return PlainTextResponse(status_code=200, content="OK")

    if callback_action in {"resource_add", "resource_edit"}:
        resource_id_raw = cast(int | str | None, callback_context.get("resource_id"))
        if resource_id_raw is None:
            raise standarts.BadRequestError(
                detail="Invalid payload",
                instance=str(request.url),
            )
        try:
            resource_id = int(resource_id_raw)
        except (TypeError, ValueError):
            raise standarts.BadRequestError(
                detail="Invalid payload",
                instance=str(request.url),
            )
        if resource_size is None:
            logger.warning(
                "resource transfer rejected (invalid final_bytes) job_id=%s action=%s resource_id=%s target=%s move_payload=%s",
                job_id,
                callback_action,
                resource_id,
                target_path,
                move_payload,
            )
            await tools.storage_file_delete(type="resource", path=target_path)
            if callback_action == "resource_add":
                async with catalog.AsyncSessionLocal() as session:
                    await session.execute(
                        delete(catalog.Resource).where(catalog.Resource.id == resource_id)
                    )
                    await session.commit()
            return PlainTextResponse(status_code=202, content="Invalid file size")

        async with catalog.AsyncSessionLocal() as session:
            resource = await session.get(catalog.Resource, resource_id)
            if not resource:
                await tools.storage_file_delete(type="resource", path=target_path)
                raise standarts.NotFoundError(
                    detail="Resource not found",
                    instance=str(request.url),
                )

            old_url = str(resource.url or "")
            update_values = {
                "url": f"local/{target_path}",
                "date_event": datetime.now(),
            }
            if resource_size is not None:
                update_values["size"] = resource_size
            for key, value in update_values.items():
                setattr(resource, key, value)
            await session.commit()

        if callback_action == "resource_edit" and old_url.startswith("local/"):
            old_path = old_url.replace("local/", "", 1)
            if old_path != target_path:
                await tools.storage_file_delete(type="resource", path=old_path)
        return PlainTextResponse(status_code=200, content="OK")

    raise standarts.BadRequestError(detail="Invalid payload", instance=str(request.url))


@router.post(
    MAIN_URL + "/storage/transfer/complete",
    include_in_schema=False,
)
async def storage_transfer_complete(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise standarts.UnauthorizedError(
            detail="Token not found",
            instance=str(request.url),
        )
    token = authorization.split(" ", 1)[1]
    payload = tools.decode_transfer_jwt(token, audience="manager")
    if not payload:
        raise standarts.ForbiddenError(
            detail="Access denied",
            instance=str(request.url),
        )

    transfer_kind = str(payload.get("transfer_kind") or "archive").strip().lower()
    if transfer_kind == "img":
        return await _storage_transfer_complete_img(request=request, payload=payload)

    status = payload.get("status")
    job_id = payload.get("job_id")
    mod_id = payload.get("mod_id")
    pack_format = payload.get("pack_format", "zip")
    update_only = bool(payload.get("update_only") or payload.get("keep_condition"))

    if not job_id or not mod_id:
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )
    try:
        mod_id = int(mod_id)
    except (TypeError, ValueError):
        raise standarts.BadRequestError(
            detail="Invalid payload",
            instance=str(request.url),
        )

    if status != "success":
        logger.warning("transfer failed job_id=%s status=%s", job_id, status)
        return PlainTextResponse(status_code=202, content="Transfer failed")

    logger.info(
        "transfer callback received job_id=%s mod_id=%s bytes=%s unpacked=%s update_only=%s",
        job_id,
        mod_id,
        payload.get("bytes"),
        payload.get("unpacked_bytes"),
        update_only,
    )
    logger.info(
        "transfer callback flags job_id=%s mod_id=%s update_only_raw=%r keep_condition_raw=%r",
        job_id,
        mod_id,
        payload.get("update_only"),
        payload.get("keep_condition"),
    )
    ext = "zip" if pack_format == "zip" else pack_format
    dest_path = f"mods/{mod_id}/main.{ext}"

    move_start = datetime.now()
    try:
        move_code, move_payload, move_ok = await tools.storage_job_move(
            job_id=job_id, type="archive", path=dest_path
        )
    except Exception:
        logger.exception("transfer move exception job_id=%s mod_id=%s", job_id, mod_id)
        raise standarts.GatewayTimeoutError(
            detail="Move timeout",
            instance=str(request.url),
        )
    if not move_ok:
        logger.warning(
            "transfer move failed job_id=%s status=%s body=%s",
            job_id,
            move_code,
            move_payload,
        )
        raise standarts.InternalServerError(
            detail="Move failed",
            instance=str(request.url),
        )
    move_duration = (datetime.now() - move_start).total_seconds()
    logger.info(
        "transfer move done job_id=%s mod_id=%s duration=%.2fs",
        job_id,
        mod_id,
        move_duration,
    )

    final_size = None
    if isinstance(move_payload, dict):
        final_size = move_payload.get("final_bytes")
    if final_size is None:
        final_size = payload.get("bytes", 0)
    try:
        final_size = int(final_size)
    except (TypeError, ValueError):
        final_size = 0
    if final_size < 0:
        final_size = 0

    unpacked_size = payload.get("unpacked_bytes")
    try:
        unpacked_size = int(unpacked_size) if unpacked_size is not None else None
    except (TypeError, ValueError):
        unpacked_size = None
    if unpacked_size is not None and unpacked_size < 0:
        unpacked_size = None

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if not mod:
            raise standarts.NotFoundError(
                detail="Mod not found",
                instance=str(request.url),
            )
        if update_only:
            update_values = {
                "size": final_size,
                "date_update_file": datetime.now(),
            }
            if unpacked_size is not None:
                update_values["size_unpacked"] = unpacked_size
            await session.execute(
                update(catalog.Mod).where(catalog.Mod.id == mod_id).values(**update_values)
            )
            await session.commit()
            return PlainTextResponse(status_code=200, content="OK")

        if mod.condition == 0:
            return PlainTextResponse(status_code=200, content="Already finalized")

        if mod.source != "local" and mod.source_id is not None and mod.source_id > 0:
            source_conflict = await session.scalar(
                select(catalog.Mod.id).where(
                    catalog.Mod.id != mod_id,
                    catalog.Mod.condition == 0,
                    catalog.Mod.source == mod.source,
                    catalog.Mod.source_id == mod.source_id,
                )
            )
            if source_conflict:
                logger.warning(
                    "transfer finalize conflict job_id=%s mod_id=%s source=%s source_id=%s conflict_mod_id=%s",
                    job_id,
                    mod_id,
                    mod.source,
                    mod.source_id,
                    source_conflict,
                )

                await session.execute(
                    delete(catalog.mods_dependencies).where(
                        (catalog.mods_dependencies.c.mod_id == mod_id)
                        | (catalog.mods_dependencies.c.dependence == mod_id)
                    )
                )
                await session.execute(
                    delete(catalog.mods_tags).where(catalog.mods_tags.c.mod_id == mod_id)
                )
                await session.execute(delete(catalog.Mod).where(catalog.Mod.id == mod_id))
                await session.commit()

                async with account.AsyncSessionLocal() as asession:
                    await asession.execute(
                        delete(account.mod_and_author).where(
                            account.mod_and_author.c.mod_id == mod_id
                        )
                    )
                    await asession.commit()

                raise standarts.PreconditionFailedError(
                    detail="Такая source-связка уже существует!",
                    instance=str(request.url),
                )

        update_values = {
            "condition": 0,
            "size": final_size,
        }
        if unpacked_size is not None:
            update_values["size_unpacked"] = unpacked_size
        await session.execute(
            update(catalog.Mod).where(catalog.Mod.id == mod_id).values(**update_values)
        )
        await session.execute(
            update(catalog.Game)
            .where(catalog.Game.id == mod.game)
            .values(
                {
                    catalog.Game.mods_count: func.coalesce(
                        catalog.Game.mods_count, 0
                    )
                    + 1
                }
            )
        )
        await session.commit()

    return PlainTextResponse(status_code=200, content="OK")


@router.get(
    MAIN_URL + "/mods/{mod_id}/download",
    tags=["Mod"],
    summary="Скачивание мода",
    status_code=307,
    responses={
        307: {
            "description": "Перенаправление на фактический адрес скачивания мода",
        },
        404: {
            "description": "Мод не найден",
        },
    },
)
async def download_mod(
    request: Request,
    mod_id: int = Path(description="ID мода"),
):
    """
    Функция скачивания мода и учета количества скачиваний.

    Не рекомендую на уровне пользователя использовать фактический адрес, т.к. он может менятся, и данная функци доп. уровень абстракции.
    """
    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            raise standarts.NotFoundError(
                detail="Not found",
                instance=str(request.url),
            )

        raw_name = mod.name or ""
        await session.execute(
            update(catalog.Mod)
            .where(catalog.Mod.id == mod_id)
            .values({catalog.Mod.downloads: catalog.Mod.downloads + 1})
        )
        await session.execute(
            update(catalog.Game)
            .where(catalog.Game.id == mod.game)
            .values({catalog.Game.mods_downloads: catalog.Game.mods_downloads + 1})
        )
        await session.commit()

    await statistics.update("mod", mod_id, "download")

    safe_name_chars = []
    for ch in raw_name:
        if ch in ALLOWED_FILENAME_CHARS:
            safe_name_chars.append(ch)
        elif ch.isspace():
            safe_name_chars.append("_")
    safe_name = "".join(safe_name_chars) or f"mod_{mod_id}"

    redirect_url = (
        f"{config.STORAGE_URL}/download/archive/mods/{mod_id}/main.zip"
        f"?filename={safe_name}"
    )

    return RedirectResponse(url=redirect_url)


@router.get(
    MAIN_URL + "/mods/access/{ids_array}",
    tags=["Mod"],
    summary="Проверка прав доступа к модам",
    status_code=200,
    responses={
        200: {
            "description": "Массив ID модов",
            "content": {"application/json": {"example": [1, 2, 3]}},
        },
        403: {
            "description": "Нет доступа (не админ И не передан правильный токен)",
            "content": {"text/plain": {"example": "Access denied"}},
        },
    },
)
async def access_to_mods(
    response: Response,
    request: Request,
    ids_array=Path(description="Массив ID модов"),
    edit: bool = Query(False, description="Фильтр на edit доступ"),
    user: int = Query(-1, description="ID пользователя"),
    authorization: str = Header(
        "",
        alias="Authorization",
        description="Bearer token для проверки прав других пользователей, аналог токена - админские права просящего",
    ),
):
    """
    Принимает массив ID модов, возвращает этот же массив в котором ID модов к которым есть read (или выше) доступ.

    Используется в Storage для проверки правомерности доступа к архиву мода.
    """
    ids_array = tools.str_to_list(ids_array)
    if user >= 0:
        if user <= 0:  # Проверка неавторизованного доступа
            if edit:
                return (
                    []
                )  # Неавторизованные пользователи не имеют edit прав, нет нужды обращаться к базе

            async with catalog.AsyncSessionLocal() as session:
                result = await session.execute(
                    select(catalog.Mod.id).where(
                        catalog.Mod.id.in_(ids_array), catalog.Mod.public <= 1
                    )
                )
                mods_ids = result.scalars().all()
            return mods_ids
        elif await tools.check_token(
            token_name="access_mods_check_anonymous",
            token=_bearer_token(authorization),
        ) or await tools.access_admin(request=request):
            return await tools.anonymous_access_mods(
                user_id=user, mods_ids=ids_array, edit=edit, check_mode=True
            )
        else:
            raise standarts.ForbiddenError(
                detail="Access denied",
                instance=str(request.url),
            )
    else:
        return await tools.access_mods(
            request=request,
            mods_ids=ids_array,
            edit=edit,
            check_mode=True,
        )


@router.get(
    MAIN_URL + "/mods/public/{ids_array}",
    tags=["Mod"],
    summary="Список публичных модов",
    status_code=200,
    responses={
        200: {
            "description": "Массив ID модов",
            "content": {"application/json": {"example": [1, 2, 3]}},
        },
        413: {
            "description": "Слишком большой массив ID модов",
            "content": {
                "text/plain": {"example": "the size of the array is not correct"}
            },
        },
    },
)
async def public_mods(
    request: Request,
    ids_array=Path(description="Массив ID модов (максимум 50 штук)"),
    in_catalog: bool = Query(
        False, description="Возвращает только полностью публичные моды"
    ),
):
    ids_array = tools.str_to_list(ids_array)

    if (
        len(ids_array) < LIMITS.mod.public_ids_min
        or len(ids_array) > LIMITS.mod.public_ids_max
    ):
        raise standarts.PayloadTooLargeError(
            detail="the size of the array is not correct",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Mod.id).where(catalog.Mod.id.in_(ids_array))
        if in_catalog:
            stmt = stmt.where(catalog.Mod.public == 0)
        else:
            stmt = stmt.where(catalog.Mod.public <= 1)
        result = await session.execute(stmt)
        output = result.scalars().all()

    return output


@router.get(
    MAIN_URL + "/mods",
    tags=["Mod"],
    summary="Список модов",
    status_code=200,
    responses={
        200: {
            "description": "Массив словарей с информацией о модах",
            "content": {
                "application/json": {
                    "example": {
                        "database_size": 123,
                        "offset": 123,
                        "results": [
                            {
                                "id": 1,
                                "name": "name",
                                "date_creation": "1984-01-01 00:00:00",
                                "date_update": "1984-01-01 00:00:00",
                            },
                            "Access denied (hide info)",
                            {
                                "id": 3,
                                "name": "name",
                                "date_creation": "1984-01-01 00:00:00",
                                "date_update": "1984-01-01 00:00:00",
                            },
                        ],
                    }
                }
            },
        },
        413: {
            "description": "Слишком сложный запрос ИЛИ page_size вне диапазона.",
        },
        400: {
            "description": (
                "Некорректный диапазон размера мода, распакованного размера "
                "или количества плагинов."
            ),
        },
    },
)
async def mod_list(
    response: Response,
    request: Request,
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    sort: str = Query(
        "DOWNLOADS", description="Сортировка. Подробнее в полном описании функции."
    ),
    tags=Query([], description="Массив ID тегов", examples=["[1, 2, 3]"]),
    excluded_tags=Query(
        [],
        description="Массив ID тегов, которых не должно быть у результата.",
        examples=["[1, 2, 3]"],
    ),
    game: int = Query(-1, description="ID игры."),
    allowed_ids=Query([], description="Массив ID разрешенных модов.", examples=["[1, 2, 3]"]),
    independents: bool = Query(
        False, description="Не передавать моды с зависимостями."
    ),
    dependencies=Query(
        [],
        description=(
            "Массив ID модов, которые должны быть в зависимостях у результата."
            " Применяется по логике И."
        ),
        examples=["[1, 2, 3]"],
    ),
    excluded_dependencies=Query(
        [],
        description="Массив ID модов, которых не должно быть в зависимостях результата.",
        examples=["[1, 2, 3]"],
    ),
    dependents_count_min: int | None = Query(
        None,
        ge=0,
        description=(
            "Минимальное количество плагинов, у которых этот мод находится в зависимостях."
        ),
    ),
    dependents_count_max: int | None = Query(
        None,
        ge=0,
        description=(
            "Максимальное количество плагинов, у которых этот мод находится в зависимостях."
        ),
    ),
    primary_sources=Query(
        [],
        description="Массив разрешенных источников.",
        examples=["['local', 'steam']"],
    ),
    allowed_sources_ids=Query(
        [],
        description="Массив ID модов в разрешенных источниках. Обязательно передать `primary_sources`.",
        examples=["[1, 2, 3]"],
    ),
    size_min: int | None = Query(
        None,
        ge=0,
        description="Минимальный размер мода в байтах.",
    ),
    size_max: int | None = Query(
        None,
        ge=0,
        description="Максимальный размер мода в байтах.",
    ),
    size_unpacked_min: int | None = Query(
        None,
        ge=0,
        description="Минимальный распакованный размер мода в байтах.",
    ),
    size_unpacked_max: int | None = Query(
        None,
        ge=0,
        description="Максимальный распакованный размер мода в байтах.",
    ),
    name: str = Query("", description="Поиск по названию."),
    user: int = Query(
        0, description="Фильтрация по модам определенного автора, 0 <= не фильтровать."
    ),
    user_owner: int = Query(
        -1,
        description="Фильтрация по роли пользователя в разработке модов (работает если активен user параметр). -1 <= не фильтровать, 0 - владелец, 1 - разработчик",
    ),
    show_not_public: bool = Query(
        False,
        description="Показывать непубличные моды пользователя *(только при фильтре `user` и если запрашивает этот пользователь или админ).*",
    ),
    short_description: bool = Query(
        False, description="Включать ли в ответ короткое описание модов."
    ),
    description: bool = Query(
        False, description="Включать ли в ответ полное описание модов."
    ),
    dates: bool = Query(
        False,
        description=(
            "Включать ли в ответ даты создания, редактирования и обновления модов."
        ),
    ),
    general: bool = Query(
        True,
        description="Включать ли в ответ общую информацию о моде (название, размер, источник, кол-во скачиваний).",
    ),
):
    """
    Возвращает список модов с возможностью многочисленных опциональных фильтров и настрое.
    Не до конца провалидированные моды и не полностью публичные моды* в список не попадают.

    **Если идет фильтрация по пользователю и включен `show_not_public`, то будут возвращены моды с любой публичностью. `show_not_public` доступен
    только при фильтре `user` и если запрашивает этот пользователь либо админ. Если доступа нет, будет возвращена ошибка 401/403.**

    О сортировке:
    Префикс `i` указывает что сортировка должна быть инвертированной.
    По умолчанию от меньшего к большему, с `i` от большего к меньшему.
    1. NAME - сортировка по имени.
    2. SIZE - сортировка по размеру.
    3. CREATION_DATE - сортировка по дате создания.
    4. UPDATE_DATE - сортировка по дате обновления.
    5. EDIT_DATE - сортировка по дате редактирования.
    6. SOURCE - сортировка по источнику.
    7. MOD_DOWNLOADS - сортировка по количеству загрузок.
    8. PLUGINS_COUNT - сортировка по количеству плагинов, у которых этот мод находится в зависимостях.
    Для обратного порядка используйте префикс `i`.
    Для совместимости поддерживается старое значение `DOWNLOADS`.
    Также поддерживаются `iMOD_DOWNLOADS` и `iPLUGINS_COUNT`.

    О фильтрации по тегам и зависимостям:
    `tags` и `dependencies` принимают массивы ID и применяют логику `И`.
    `excluded_tags` и `excluded_dependencies` исключают моды, у которых
    встречаются указанные значения.
    Одновременное использование `dependencies` и `independents=true` запрещено.

    О фильтрации по размеру:
    `size_min` и `size_max` задают диапазон в байтах для поля `size`.
    `size_unpacked_min` и `size_unpacked_max` задают диапазон в байтах
    для поля `size_unpacked`.
    Можно передать только одну границу или обе сразу.

    О фильтрации по количеству плагинов:
    `dependents_count_min` и `dependents_count_max` задают диапазон по числу
    модов, у которых этот мод указан в зависимостях. Это удобно для поиска
    модов-фреймворков с разной популярностью среди плагинов.
    """
    tags = tools.str_to_list(tags)
    excluded_tags = tools.str_to_list(excluded_tags)
    dependencies = tools.str_to_list(dependencies)
    excluded_dependencies = tools.str_to_list(excluded_dependencies)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)
    allowed_sources_ids = tools.str_to_list(allowed_sources_ids)

    if len(dependencies) > 0:
        try:
            dependencies = [int(dependence_id) for dependence_id in dependencies]
        except (TypeError, ValueError):
            raise standarts.BadRequestError(
                detail="dependencies filter should contain integer IDs",
                instance=str(request.url),
                context={"error_id": 3},
            )
        dependencies = list(dict.fromkeys(dependencies))

    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 1},
        )
    elif (
        len(tags)
        + len(excluded_tags)
        + len(dependencies)
        + len(excluded_dependencies)
        + len(primary_sources)
        + len(allowed_ids)
        + len(allowed_sources_ids)
    ) > LIMITS.mod.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 90 elements in sum",
            instance=str(request.url),
            context={"error_id": 2},
        )
    elif independents and len(dependencies) > 0:
        raise standarts.BadRequestError(
            detail="independents filter conflicts with dependencies filter",
            instance=str(request.url),
            context={"error_id": 4},
        )
    elif size_min is not None and size_max is not None and size_min > size_max:
        raise standarts.BadRequestError(
            detail="Минимальный размер мода не может быть больше максимального!",
            instance=str(request.url),
            context={"error_id": 5},
        )
    elif (
        size_unpacked_min is not None
        and size_unpacked_max is not None
        and size_unpacked_min > size_unpacked_max
    ):
        raise standarts.BadRequestError(
            detail="Минимальный распакованный размер мода не может быть больше максимального!",
            instance=str(request.url),
            context={"error_id": 6},
        )
    elif (
        dependents_count_min is not None
        and dependents_count_max is not None
        and dependents_count_min > dependents_count_max
    ):
        raise standarts.BadRequestError(
            detail="Минимальное количество плагинов не может быть больше максимального!",
            instance=str(request.url),
            context={"error_id": 7},
        )

    want_not_public = show_not_public and user > 0
    if want_not_public:
        if user <= 0:
            raise standarts.ForbiddenError(instance=str(request.url))

        access_result = await account.check_access(request=request)
        req_user_id = access_result.get("owner_id", -1) if access_result else -1
        if req_user_id < 0:
            raise standarts.UnauthorizedError(instance=str(request.url))

        if req_user_id != user:
            if not access_result.admin:
                raise standarts.ForbiddenError(instance=str(request.url))

    only_publics = not want_not_public

    async with catalog.AsyncSessionLocal() as session:
        dependent_mod = aliased(catalog.Mod)
        dependent_filters = [
            catalog.mods_dependencies.c.dependence == catalog.Mod.id,
            dependent_mod.condition == 0,
        ]
        if only_publics:
            dependent_filters.append(dependent_mod.public == 0)
        dependents_count_stmt = (
            select(func.count(func.distinct(catalog.mods_dependencies.c.mod_id)))
            .select_from(
                catalog.mods_dependencies.join(
                    dependent_mod, dependent_mod.id == catalog.mods_dependencies.c.mod_id
                )
            )
            .where(*dependent_filters)
            .correlate(catalog.Mod)
            .scalar_subquery()
        )

        stmt = select(catalog.Mod).order_by(
            tools.sort_mods(sort, dependents_count_stmt)
        )
        stmt = stmt.where(catalog.Mod.condition == 0)
        if only_publics:
            stmt = stmt.where(catalog.Mod.public == 0)

        if len(allowed_ids) > 0:
            stmt = stmt.where(catalog.Mod.id.in_(allowed_ids))

        if game > 0:
            stmt = stmt.where(catalog.Mod.game == game)

        if len(primary_sources) > 0:
            stmt = stmt.where(catalog.Mod.source.in_(primary_sources))
            if len(allowed_sources_ids) > 0:
                stmt = stmt.where(catalog.Mod.source_id.in_(allowed_sources_ids))

        if independents:
            stmt = stmt.outerjoin(
                catalog.mods_dependencies,
                catalog.Mod.id == catalog.mods_dependencies.c.mod_id,
            ).where(catalog.mods_dependencies.c.mod_id.is_(None))
        elif len(dependencies) > 0:
            mods_with_dependencies = (
                select(catalog.mods_dependencies.c.mod_id)
                .where(catalog.mods_dependencies.c.dependence.in_(dependencies))
                .group_by(catalog.mods_dependencies.c.mod_id)
                .having(
                    func.count(func.distinct(catalog.mods_dependencies.c.dependence))
                    == len(dependencies)
                )
                .subquery()
            )
            stmt = stmt.join(
                mods_with_dependencies,
                catalog.Mod.id == mods_with_dependencies.c.mod_id,
            )

        if len(name) > 0:
            logger.debug("Filtering mods by name length=%s", len(name))
            stmt = stmt.where(catalog.Mod.name.ilike(f"%{name}%"))

        if size_min is not None:
            stmt = stmt.where(catalog.Mod.size >= size_min)
        if size_max is not None:
            stmt = stmt.where(catalog.Mod.size <= size_max)
        if size_unpacked_min is not None:
            stmt = stmt.where(catalog.Mod.size_unpacked >= size_unpacked_min)
        if size_unpacked_max is not None:
            stmt = stmt.where(catalog.Mod.size_unpacked <= size_unpacked_max)

        if len(tags) > 0:
            for tag in tags:
                stmt = stmt.where(catalog.Mod.tags.any(catalog.Tag.id == tag))

        if len(excluded_tags) > 0:
            stmt = stmt.where(
                ~select(1)
                .where(
                    catalog.mods_tags.c.mod_id == catalog.Mod.id,
                    catalog.mods_tags.c.tag_id.in_(excluded_tags),
                )
                .exists()
            )

        if user > 0:
            stmt = stmt.join(
                account.mod_and_author, account.mod_and_author.c.mod_id == catalog.Mod.id
            )
            stmt = stmt.where(account.mod_and_author.c.user_id == user)

            if user_owner in [0, 1]:
                stmt = stmt.where(account.mod_and_author.c.owner == (user_owner == 0))

        if len(excluded_dependencies) > 0:
            stmt = stmt.where(
                ~select(1)
                .where(
                    catalog.mods_dependencies.c.mod_id == catalog.Mod.id,
                    catalog.mods_dependencies.c.dependence.in_(excluded_dependencies),
                )
                .exists()
            )
        if dependents_count_min is not None:
            stmt = stmt.where(dependents_count_stmt >= dependents_count_min)
        if dependents_count_max is not None:
            stmt = stmt.where(dependents_count_stmt <= dependents_count_max)

        mods_count = await session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        mods_count = int(mods_count or 0)
        offset = page_size * page
        mods = (await session.execute(stmt.offset(offset).limit(page_size))).scalars().all()

    result_access_mods: list[int] = []
    if not only_publics:
        result_access_mods = await tools.access_mods(
            request=request,
            mods_ids=[mod.id for mod in mods],
            check_mode=True,
        )

    output_mods = []
    for mod in mods:

        def append_mod():
            out = {"id": mod.id}
            if description:
                out["description"] = mod.description
            if short_description:
                out["short_description"] = mod.short_description
            if dates:
                out["date_update_file"] = mod.date_update_file
                out["date_creation"] = mod.date_creation
                out["date_edit"] = mod.date_edit
            if general:
                out["name"] = mod.name
                out["size"] = mod.size
                out["size_unpacked"] = mod.size_unpacked
                out["source"] = mod.source
                out["source_id"] = mod.source_id
                out["downloads"] = mod.downloads

            output_mods.append(out)

        if only_publics:
            append_mod()
        else:
            if mod.id in result_access_mods:
                append_mod()
            else:
                output_mods.append("Access denied (hide info)")
                mods_count -= 1

    # Вывод результатов
    return {"database_size": mods_count, "offset": offset, "results": output_mods}


@router.get(
    MAIN_URL + "/mods/feed",
    tags=["Mod"],
    summary="Диапазон размеров модов и распакованных размеров по игре",
    status_code=200,
    responses={
        200: {
            "description": "OK",
            "content": {
                "application/json": {
                    "example": {
                        "database_size": 123,
                        "size_min": 1024,
                        "size_max": 1048576,
                        "size_unpacked_min": 2048,
                        "size_unpacked_max": 2097152,
                    }
                }
            },
        }
    },
)
async def mod_feed(
    game: int = Query(-1, description="ID игры."),
):
    """
    Возвращает диапазоны размеров публичных модов и их распакованных версий
    для настройки фильтров и слайдеров. Если передан `game`, диапазоны
    считаются только по модам этой игры.
    Если модов в каталоге нет, все min/max поля будут `null`.
    """
    async with catalog.AsyncSessionLocal() as session:
        visibility_clause = (
            (catalog.Mod.condition == 0) & (catalog.Mod.public == 0)
        )
        count_stmt = select(func.count()).select_from(catalog.Mod).where(visibility_clause)
        min_stmt = select(func.min(catalog.Mod.size)).where(visibility_clause)
        max_stmt = select(func.max(catalog.Mod.size)).where(visibility_clause)
        unpacked_min_stmt = select(func.min(catalog.Mod.size_unpacked)).where(
            visibility_clause
        )
        unpacked_max_stmt = select(func.max(catalog.Mod.size_unpacked)).where(
            visibility_clause
        )

        if game > 0:
            count_stmt = count_stmt.where(catalog.Mod.game == game)
            min_stmt = min_stmt.where(catalog.Mod.game == game)
            max_stmt = max_stmt.where(catalog.Mod.game == game)
            unpacked_min_stmt = unpacked_min_stmt.where(catalog.Mod.game == game)
            unpacked_max_stmt = unpacked_max_stmt.where(catalog.Mod.game == game)

        mods_count = int((await session.scalar(count_stmt)) or 0)
        size_min = await session.scalar(min_stmt)
        size_max = await session.scalar(max_stmt)
        size_unpacked_min = await session.scalar(unpacked_min_stmt)
        size_unpacked_max = await session.scalar(unpacked_max_stmt)

    return {
        "database_size": mods_count,
        "size_min": int(size_min) if size_min is not None else None,
        "size_max": int(size_max) if size_max is not None else None,
        "size_unpacked_min": (
            int(size_unpacked_min) if size_unpacked_min is not None else None
        ),
        "size_unpacked_max": (
            int(size_unpacked_max) if size_unpacked_max is not None else None
        ),
    }


@router.get(
    MAIN_URL + "/mods/{mod_id}",
    tags=["Mod"],
    summary="Информация о моде",
    status_code=200,
    responses={
        200: {
            "description": "OK",
            "content": {
                "application/json": {
                    "example": {
                        "dependencies": [1, 2, 3],
                        "dependencies_count": 3,
                        "authors": {1: {"owner": True}, 2: {"owner": False}},
                        "result": {
                            "condition": 0,
                            "description": "Some description",
                            "short_description": "Some short description",
                            "date_update_file": "1984-05-22T02:42:42",
                            "date_edit": "1984-07-12T15:77:12",
                            "date_creation": "1984-01-01T15:11:40",
                            "name": "Some name",
                            "size": 123456789,
                            "source": "local",
                            "source_id": None,
                            "downloads": 42,
                            "public": 0,
                            "game": {"id": 1, "name": "game"},
                        },
                    }
                }
            },
        },
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {
            "description": "Not found",
            "content": {"text/plain": {"example": "Mod not found."}},
        },
    },
)
async def info_mod(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    dependencies: bool = Query(False, description="Передать ли список зависимостей."),
    short_description: bool = Query(
        False, description="Передать ли краткое описание мода."
    ),
    description: bool = Query(False, description="Передать ли описание мода."),
    dates: bool = Query(
        False, description="Передать ли дату обновления и создания мода."
    ),
    general: bool = Query(True, description="Передать ли основные данные о моде."),
    game: bool = Query(False, description="Передать ли информацию о игре мода."),
    authors: bool = Query(False, description="Передать ли список авторов мода."),
):
    response_payload: dict[str, object] = {}

    async with catalog.AsyncSessionLocal() as session:
        pre_result = await session.get(catalog.Mod, mod_id)
        if pre_result is None:
            raise standarts.NotFoundError(
                detail="Mod not found.",
                instance=str(request.url),
            )

        if pre_result.public >= 2:
            result_access = await tools.access_mods(request=request, mods_ids=mod_id, edit=False)
            if not result_access:
                return result_access

        if dependencies:
            count = await session.scalar(
                select(func.count()).select_from(catalog.mods_dependencies).where(
                    catalog.mods_dependencies.c.mod_id == mod_id
                )
            )
            result = await session.execute(
                select(catalog.mods_dependencies.c.dependence)
                .where(catalog.mods_dependencies.c.mod_id == mod_id)
                .limit(100)
            )
            response_payload["dependencies"] = result.scalars().all()
            response_payload["dependencies_count"] = int(count or 0)

        game_payload: dict[str, object] | None = None
        if game:
            game_name = await session.scalar(
                select(catalog.Game.name).where(catalog.Game.id == pre_result.game)
            )
            game_payload = {"id": pre_result.game, "name": game_name}

        result_payload: dict[str, object] = {"condition": pre_result.condition}
        response_payload["result"] = result_payload

        if description:
            result_payload["description"] = pre_result.description
        if short_description:
            result_payload["short_description"] = pre_result.short_description
        if dates:
            strformattime = "%Y-%m-%dT%H:%M:%S"

            if pre_result.date_update_file is not None:
                result_payload["date_update_file"] = pre_result.date_update_file.strftime(
                    strformattime
                )
            if pre_result.date_edit is not None:
                result_payload["date_edit"] = pre_result.date_edit.strftime(strformattime)
            if pre_result.date_creation is not None:
                result_payload["date_creation"] = pre_result.date_creation.strftime(
                    strformattime
                )
        if general:
            result_payload["name"] = pre_result.name
            result_payload["size"] = pre_result.size
            result_payload["size_unpacked"] = pre_result.size_unpacked
            result_payload["source"] = pre_result.source
            result_payload["source_id"] = pre_result.source_id
            result_payload["downloads"] = pre_result.downloads
            result_payload["public"] = pre_result.public
        if game and game_payload is not None:
            result_payload["game"] = game_payload

        if authors:
            async with account.AsyncSessionLocal() as session_account:
                row_results = (
                    await session_account.execute(
                        select(
                            account.mod_and_author.c.user_id,
                            account.mod_and_author.c.owner,
                        ).where(account.mod_and_author.c.mod_id == mod_id).limit(100)
                    )
                ).all()

                authors_payload: dict[int, dict[str, bool]] = {}
                for user_id, owner in row_results:
                    authors_payload[int(user_id)] = {"owner": bool(owner)}
                response_payload["authors"] = authors_payload

    if dependencies:
        response_payload.setdefault("dependencies", [])
        response_payload.setdefault("dependencies_count", 0)

    await statistics.update("mod", mod_id, "page_view")
    return JSONResponse(status_code=200, content=response_payload)


@router.get(
    MAIN_URL + "/mods/{mod_id}/resources",
    tags=["Mod", "Resource"],
    summary="Ресурсы мода",
    status_code=200,
    responses={
        200: {"description": "OK"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Мод не найден."},
        413: {"description": "Неккоректный диапазон параметров *(размеров)*."},
    },
)
async def mod_resources(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    resources_list_id=Query(
        [],
        description="Список ID-ресурсов.",
        examples=["[1, 2, 3]"],
    ),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        examples=['["logo", "screenshot"]'],
    ),
    only_urls: bool = Query(
        False, description="Возвращать только ссылки или полную информацию."
    ),
):
    resources_list_id = tools.str_to_list(resources_list_id)
    types_resources = tools.str_to_list(types_resources)

    if len(types_resources) + len(resources_list_id) > LIMITS.resource.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="the maximum complexity of filters is 120 elements in sum",
            instance=str(request.url),
            context={"error_id": 1},
        )
    elif page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page size",
            instance=str(request.url),
            context={"error_id": 2},
        )
    elif page < 0:
        raise standarts.PayloadTooLargeError(
            detail="incorrect page",
            instance=str(request.url),
            context={"error_id": 3},
        )

    async with catalog.AsyncSessionLocal() as session:
        mod_exists = await session.get(catalog.Mod, mod_id)
    if not mod_exists:
        raise standarts.NotFoundError(
            detail="Mod not found.",
            instance=str(request.url),
        )

    access_result = await tools.access_mods(request=request, mods_ids=[mod_id])
    if access_result is not True:
        return access_result

    async with catalog.AsyncSessionLocal() as session:
        stmt = select(catalog.Resource).where(
            catalog.Resource.owner_type == "mods",
            catalog.Resource.owner_id == mod_id,
        )
        if len(resources_list_id) > 0:
            stmt = stmt.where(catalog.Resource.id.in_(resources_list_id))
        if len(types_resources) > 0:
            stmt = stmt.where(catalog.Resource.type.in_(types_resources))

        resources_count = await session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        resources_count = int(resources_count or 0)
        offset = page_size * page
        resources = (
            await session.execute(stmt.offset(offset).limit(page_size))
        ).scalars().all()

    real_resources = await tools.resources_serialize(
        resources=resources, only_urls=only_urls
    )
    return {
        "database_size": resources_count,
        "offset": offset,
        "results": real_resources,
    }


@router.get(
    MAIN_URL + "/mods/{mod_id}/tags",
    tags=["Mod", "Tag"],
    summary="Теги мода",
    status_code=200,
    responses={
        200: {"description": "OK"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Мод не найден."},
    },
)
async def mod_tags(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    only_ids: bool = Query(False, description="Если True вернет только ID тегов."),
):
    async with catalog.AsyncSessionLocal() as session:
        mod_exists = await session.get(catalog.Mod, mod_id)
    if not mod_exists:
        raise standarts.NotFoundError(
            detail="Mod not found.",
            instance=str(request.url),
        )

    access_result = await tools.access_mods(request=request, mods_ids=[mod_id])
    if access_result is not True:
        return access_result

    async with catalog.AsyncSessionLocal() as session:
        tags = (
            await session.execute(
                select(catalog.Tag)
                .join(catalog.mods_tags)
                .where(catalog.mods_tags.c.mod_id == mod_id)
            )
        ).scalars().all()

    if only_ids:
        return [tag.id for tag in tags]
    return [{"id": tag.id, "name": tag.name} for tag in tags]


@router.get(
    MAIN_URL + "/mods/{mod_id}/dependencies",
    tags=["Mod"],
    summary="Зависимости мода",
    status_code=200,
    responses={
        200: {"description": "OK"},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        404: {"description": "Мод не найден."},
    },
)
async def mod_dependencies(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
):
    async with catalog.AsyncSessionLocal() as session:
        mod_exists = await session.get(catalog.Mod, mod_id)
    if not mod_exists:
        raise standarts.NotFoundError(
            detail="Mod not found.",
            instance=str(request.url),
        )

    access_result = await tools.access_mods(request=request, mods_ids=[mod_id])
    if access_result is not True:
        return access_result

    async with catalog.AsyncSessionLocal() as session:
        dependencies = (
            await session.execute(
                select(catalog.mods_dependencies.c.dependence).where(
                    catalog.mods_dependencies.c.mod_id == mod_id
                )
            )
        ).scalars().all()

    return {"count": len(dependencies), "results": dependencies}


async def edit_mod(
    response: Response,
    request: Request,
    mod_id: int = Form(..., description="ID мода для редактирования."),
    mod_name: str = Form(
        None, description="Название мода.", max_length=LIMITS.mod.name_max
    ),
    mod_short_description: str = Form(
        None, description="Краткое описание мода.", max_length=LIMITS.mod.short_desc_max
    ),
    mod_description: str = Form(
        None, description="Полное описание мода.", max_length=LIMITS.mod.desc_max
    ),
    mod_source: str = Form(
        None,
        description="Источник мода. Так же обязательно передать и `mod_source_id`, даже если его данные не изменились!",
        max_length=LIMITS.mod.source_max,
    ),
    mod_source_id: int = Form(None, description="ID мода в первоисточнике."),
    mod_game: int = Form(None, description="ID игры-владельца."),
    mod_public: int = Form(
        None, description="Публичный ли мод? 0-да, 1-только по ссылке, 2-нет."
    ),
):
    access_result = await tools.access_mods(request=request, mods_ids=mod_id, edit=True)
    if access_result is True:
        body: dict[str, object] = {}
        if mod_name is not None:
            if len(mod_name) > LIMITS.mod.name_edit_max:
                raise standarts.PayloadTooLargeError(
                    detail="Название слишком длинное!",
                    instance=str(request.url),
                )
            elif len(mod_name) < LIMITS.mod.name_min:
                raise standarts.PreconditionRequiredError(
                    detail="Название слишком короткое!",
                    instance=str(request.url),
                )
            body["name"] = mod_name
        if mod_short_description is not None:
            if (
                len(re.sub(r"\s+", " ", mod_short_description))
                > LIMITS.mod.short_desc_max
            ):
                raise standarts.PayloadTooLargeError(
                    detail="Короткое описание слишком длинное!",
                    instance=str(request.url),
                )
            body["short_description"] = mod_short_description
        if mod_description is not None:
            if len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
                raise standarts.PayloadTooLargeError(
                    detail="Описание слишком длинное!",
                    instance=str(request.url),
                )
            body["description"] = mod_description
        if mod_source is not None:
            body["source"] = mod_source
            if (
                mod_source_id is not None
                and mod_source_id > 0
                and mod_source != "local"
            ):
                body["source_id"] = mod_source_id
            else:
                body["source_id"] = None

            async with catalog.AsyncSessionLocal() as session:
                result = await session.scalar(
                    select(catalog.Mod).where(
                        catalog.Mod.source == mod_source,
                        catalog.Mod.source_id == body["source_id"],
                    )
                )
            if result:
                raise standarts.PreconditionFailedError(
                    detail="Такая source-связка уже существует!",
                    instance=str(request.url),
                )
        if mod_game is not None:
            if not await tools.check_game_exists(mod_game):
                raise standarts.PreconditionFailedError(
                    detail="Такой игры не существует!",
                    instance=str(request.url),
                )
            body["game"] = mod_game
        if mod_public is not None:
            if mod_public in [0, 1, 2]:
                body["public"] = mod_public

        if len(body) <= 0:
            raise standarts.PreconditionRequiredError(
                detail="Ничего не было изменено!",
                instance=str(request.url),
            )

        if len(body) > 0:
            body["date_edit"] = datetime.now()

        async with catalog.AsyncSessionLocal() as session:
            await session.execute(
                update(catalog.Mod).where(catalog.Mod.id == mod_id).values(**body)
            )
            await session.commit()
        return PlainTextResponse(status_code=201, content="OK")
    else:
        return access_result


@router.patch(
    MAIN_URL + "/mods/{mod_id}",
    tags=["Mod"],
    summary="Редактирование мода",
    status_code=201,
    responses={
        201: {"description": "Изменения успешно выполнены."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        411: routers_edit_mod_response[411],
        412: {
            "description": "Такой игры не существует или такая source-связка занята."
        },
        413: routers_edit_mod_response[413],
        500: routers_edit_mod_response[500],
    },
)
async def edit_mod_rest(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода для редактирования."),
    mod_name: str = Form(
        None, description="Название мода.", max_length=LIMITS.mod.name_max
    ),
    mod_short_description: str = Form(
        None, description="Краткое описание мода.", max_length=LIMITS.mod.short_desc_max
    ),
    mod_description: str = Form(
        None, description="Полное описание мода.", max_length=LIMITS.mod.desc_max
    ),
    mod_source: str = Form(
        None,
        description="Источник мода. Так же обязательно передать и `mod_source_id`, даже если его данные не изменились!",
        max_length=LIMITS.mod.source_max,
    ),
    mod_source_id: int = Form(None, description="ID мода в первоисточнике."),
    mod_game: int = Form(None, description="ID игры-владельца."),
    mod_public: int = Form(
        None, description="Публичный ли мод? 0-да, 1-только по ссылке, 2-нет."
    ),
):
    return await edit_mod(
        response=response,
        request=request,
        mod_id=mod_id,
        mod_name=mod_name,
        mod_short_description=mod_short_description,
        mod_description=mod_description,
        mod_source=mod_source,
        mod_source_id=mod_source_id,
        mod_game=mod_game,
        mod_public=mod_public,
    )


@router.patch(
    MAIN_URL + "/mods/{mod_id}/authors",
    tags=["Mod"],
    summary="Редактирование авторов мода",
    status_code=202,
    responses={
        200: {"description": "Изменения успешно выполнены."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
    },
)
async def edit_authors_mod(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода для редактирования."),
    mode: bool = Form(..., description="Добавить*(True)* или удалить*(False)* автора?"),
    author: int = Form(..., description="ID автора."),
    owner: bool = Form(
        False,
        description="Владелец ли? Текущий владелец если он есть станет участником.",
    ),
):
    mod_access = await tools.access_mod_action(
        request=request,
        mod_id=mod_id,
        author_id=author,
        mode=mode,
    )
    if not mod_access.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not mod_access.edit.authors.value:
        raise standarts.ForbiddenError(
            detail=mod_access.edit.authors.reason,
            instance=str(request.url),
            context={"reason_code": mod_access.edit.authors.reason_code},
        )

    async with account.AsyncSessionLocal() as session:
        user_add = await session.get(account.Account, author)
        if not user_add:
            raise standarts.ForbiddenError(instance=str(request.url))

        if mode:
            has_owner = await session.scalar(
                select(account.mod_and_author.c.owner).where(
                    account.mod_and_author.c.mod_id == mod_id,
                    account.mod_and_author.c.owner.is_(True),
                )
            )
            if owner and has_owner:
                await session.execute(
                    update(account.mod_and_author)
                    .where(
                        account.mod_and_author.c.mod_id == mod_id,
                        account.mod_and_author.c.owner.is_(True),
                    )
                    .values(owner=False)
                )
                await session.commit()

            has_target = await session.scalar(
                select(account.mod_and_author.c.owner).where(
                    account.mod_and_author.c.mod_id == mod_id,
                    account.mod_and_author.c.user_id == author,
                )
            )
            if has_target is not None:
                await session.execute(
                    update(account.mod_and_author)
                    .where(
                        account.mod_and_author.c.mod_id == mod_id,
                        account.mod_and_author.c.user_id == author,
                    )
                    .values(owner=owner)
                )
            else:
                await session.execute(
                    insert(account.mod_and_author).values(
                        user_id=author, owner=owner, mod_id=mod_id
                    )
                )
            await session.commit()
        else:
            await session.execute(
                delete(account.mod_and_author).where(
                    account.mod_and_author.c.mod_id == mod_id,
                    account.mod_and_author.c.user_id == author,
                )
            )
            await session.commit()

        return JSONResponse(status_code=200, content="Выполнено")


@router.delete(
    MAIN_URL + "/mods/{mod_id}",
    tags=["Mod"],
    summary="Удаление мода",
    status_code=200,
    responses={
        200: {"description": "Мод успешно удален."},
        401: standarts.UNAUTHORIZED_RESPONSE_SPEC,
        403: standarts.FORBIDDEN_RESPONSE_SPEC,
        500: {
            "description": "Не удалось удалить архив/ресурсы мода с файлового хранилища *(поробовать еще раз попозже)*.",
            "content": {"text/plain": {"example": "Не удалось удалить мод!"}},
        },
    },
)
async def delete_mod(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода для удаления."),
):
    mod_access = await tools.access_mod_action(
        request=request,
        mod_id=mod_id,
    )
    logger.info("Delete mod request received mod_id=%s", mod_id)

    if not mod_access.authenticated:
        logger.info("Delete mod denied: invalid session mod_id=%s", mod_id)
        raise standarts.UnauthorizedError(instance=str(request.url))
    user_id = mod_access.owner_id
    logger.info("Delete mod auth ok mod_id=%s user_id=%s", mod_id, user_id)

    if not mod_access.delete.value:
        logger.info(
            "Delete mod denied by permissions mod_id=%s user_id=%s",
            mod_id,
            user_id,
        )
        raise standarts.ForbiddenError(
            detail=mod_access.delete.reason,
            instance=str(request.url),
            context={"reason_code": mod_access.delete.reason_code},
        )

    # Удаление ресурсов
    logger.info("Delete mod removing resources mod_id=%s", mod_id)
    resource_delete_result = await tools.delete_resources(
        owner_type="mods", owner_id=mod_id
    )
    logger.info(
        "Delete mod resources result mod_id=%s ok=%s",
        mod_id,
        resource_delete_result,
    )
    logger.info("Delete mod removing archive mod_id=%s", mod_id)
    storage_delete_result = await tools.storage_file_delete(
        type="archive", path=f"mods/{mod_id}/main.zip"
    )
    logger.info(
        "Delete mod archive delete result mod_id=%s ok=%s",
        mod_id,
        storage_delete_result,
    )

    if not (resource_delete_result and storage_delete_result):
        logger.warning(
            "Delete mod failed external delete mod_id=%s resources_ok=%s archive_ok=%s",
            mod_id,
            resource_delete_result,
            storage_delete_result,
        )
        raise standarts.InternalServerError(
            detail="Не удалось удалить мод!",
            instance=str(request.url),
        )

    async with catalog.AsyncSessionLocal() as session:
        mod_obj = await session.get(catalog.Mod, mod_id)
        if not mod_obj:
            raise standarts.NotFoundError(
                detail="Мод не найден",
                instance=str(request.url),
            )

        game_id = mod_obj.game

        await session.execute(delete(catalog.Mod).where(catalog.Mod.id == mod_id))
        await session.execute(
            delete(catalog.mods_dependencies).where(
                catalog.mods_dependencies.c.mod_id == mod_id
            )
        )
        await session.execute(
            delete(catalog.mods_tags).where(catalog.mods_tags.c.mod_id == mod_id)
        )
        await session.execute(
            update(catalog.Game)
            .where(catalog.Game.id == game_id)
            .values({catalog.Game.mods_count: catalog.Game.mods_count - 1})
        )
        await session.commit()

    return PlainTextResponse(status_code=200, content="Удалено")
