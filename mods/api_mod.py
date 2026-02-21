from fastapi import (
    APIRouter,
    Request,
    Response,
    Form,
    Path,
    Query,
    Header,
)
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sql_logic import sql_account as account
import tools
import logging
import re
import uuid
from urllib.parse import urlparse, quote
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert, func
from typing import Optional
from sql_logic import sql_catalog as catalog
from sql_logic import sql_statistics as statistics
from ow_config import MAIN_URL
import ow_config as config
from limits import LIMITS
import standarts

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


@router.post(
    MAIN_URL + "/mods/from-file",
    tags=["Mod"],
    summary="Добавление мода (файл напрямую на Storage)",
    status_code=307,
    responses={
        307: {"description": "Перенаправление на Storage для загрузки"},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    access_result = await account.check_access(request=request, response=response)
    if isinstance(access_result, bool):
        return JSONResponse(status_code=403, content="Нет кук доступа!")
    user_id = access_result.get("owner_id", -1)

    if access_result and user_id >= 0:
        logger.debug(
            "Mod short description length=%s", len(mod_short_description or "")
        )
        if len(re.sub(r"\s+", " ", mod_short_description)) > LIMITS.mod.short_desc_max:
            return PlainTextResponse(
                status_code=413, content="Короткое описание слишком длинное!"
            )
        elif len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
            return PlainTextResponse(
                status_code=413, content="Описание слишком длинное!"
            )
        elif len(mod_name) > LIMITS.mod.name_max:
            return PlainTextResponse(
                status_code=413, content="Название слишком длинное!"
            )
        elif len(mod_name) < LIMITS.mod.name_min:
            return PlainTextResponse(
                status_code=411, content="Название слишком короткое!"
            )
        elif not await tools.check_game_exists(mod_game):
            return PlainTextResponse(
                status_code=412, content="Такой игры не существует!"
            )

        if pack_format != "zip":
            return PlainTextResponse(status_code=400, content="Unsupported format")

        if not getattr(config, "TRANSFER_JWT_SECRET", None):
            return PlainTextResponse(status_code=500, content="JWT secret missing")

        session = sessionmaker(bind=account.engine)()
        user_req = session.query(account.Account).filter_by(id=user_id).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if without_author:
                    return False
                elif user_req.mute_until and user_req.mute_until > datetime.now():
                    return False
                elif user_req.publish_mods:
                    return True
            return False

        if await mini():
            session.close()

            if mod_public not in [0, 1, 2]:
                mod_public = 0

            Session = sessionmaker(bind=catalog.engine)
            session = Session()
            insert_statement = insert(catalog.Mod)
            insert_statement = insert_statement.values(
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
                insert_statement = insert_statement.values(source_id=mod_source_id)

                tsession = sessionmaker(bind=catalog.engine)()
                source_conflicts = (
                    tsession.query(catalog.Mod)
                    .filter_by(source=mod_source, source_id=mod_source_id)
                    .all()
                )
                tsession.close()

                for conflict_mod in source_conflicts:
                    # Игнорируем конфликт только для незавершенного мода того же автора.
                    if conflict_mod.condition != 0:
                        asession = sessionmaker(bind=account.engine)()
                        same_author = (
                            asession.query(account.mod_and_author)
                            .filter_by(mod_id=conflict_mod.id, user_id=user_id)
                            .first()
                        )
                        asession.close()
                        if same_author:
                            continue

                    session.close()
                    return PlainTextResponse(
                        status_code=412, content="Такая source-связка уже существует!"
                    )

            result = session.execute(insert_statement)
            rid = result.lastrowid
            session.commit()

            if not without_author:
                session = sessionmaker(bind=account.engine)()
                session.execute(
                    account.mod_and_author.insert().values(
                        mod_id=rid, user_id=user_id, owner=True
                    )
                )
                session.commit()
                session.close()

            session.close()

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
                return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        else:
            session.close()
            return PlainTextResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")


@router.post(
    MAIN_URL + "/mods/{mod_id}/file",
    tags=["Mod"],
    summary="Обновление файла мода (файл напрямую на Storage)",
    status_code=307,
    responses={
        307: {"description": "Перенаправление на Storage для загрузки"},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    access_result = await tools.access_mods(
        response=response, request=request, mods_ids=mod_id, edit=True
    )
    if access_result is not True:
        return access_result

    session = sessionmaker(bind=catalog.engine)()
    mod_exists = session.query(catalog.Mod.id).filter_by(id=mod_id).first()
    session.close()
    if not mod_exists:
        return PlainTextResponse(status_code=404, content="Mod not found")

    if pack_format != "zip":
        return PlainTextResponse(status_code=400, content="Unsupported format")

    if not getattr(config, "TRANSFER_JWT_SECRET", None):
        return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    access_result = await account.check_access(request=request, response=response)
    if isinstance(access_result, bool):
        return JSONResponse(status_code=403, content="Нет кук доступа!")
    user_id = access_result.get("owner_id", -1)

    if access_result and user_id >= 0:
        logger.debug(
            "Mod short description length=%s", len(mod_short_description or "")
        )
        if len(re.sub(r"\s+", " ", mod_short_description)) > LIMITS.mod.short_desc_max:
            return PlainTextResponse(
                status_code=413, content="Короткое описание слишком длинное!"
            )
        elif len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
            return PlainTextResponse(
                status_code=413, content="Описание слишком длинное!"
            )
        elif len(mod_name) > LIMITS.mod.name_max:
            return PlainTextResponse(
                status_code=413, content="Название слишком длинное!"
            )
        elif len(mod_name) < LIMITS.mod.name_min:
            return PlainTextResponse(
                status_code=411, content="Название слишком короткое!"
            )
        elif not await tools.check_game_exists(mod_game):
            return PlainTextResponse(
                status_code=412, content="Такой игры не существует!"
            )

        parsed = urlparse(mod_url)
        if parsed.scheme not in {"http", "https"}:
            return PlainTextResponse(status_code=411, content="Некорректная ссылка!")

        if pack_format != "zip":
            return PlainTextResponse(status_code=400, content="Unsupported format")

        if not getattr(config, "TRANSFER_JWT_SECRET", None):
            return PlainTextResponse(status_code=500, content="JWT secret missing")

        # Проверка прав
        session = sessionmaker(bind=account.engine)()
        user_req = session.query(account.Account).filter_by(id=user_id).first()

        async def mini():
            if user_req.admin:
                return True
            else:
                if without_author:
                    return False
                elif user_req.mute_until and user_req.mute_until > datetime.now():
                    return False
                elif user_req.publish_mods:
                    return True
            return False

        if await mini():
            session.close()

            if mod_public not in [0, 1, 2]:
                mod_public = 0

            Session = sessionmaker(bind=catalog.engine)
            session = Session()
            insert_statement = insert(catalog.Mod)
            insert_statement = insert_statement.values(
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
                insert_statement = insert_statement.values(source_id=mod_source_id)

                tsession = sessionmaker(bind=catalog.engine)()
                result = (
                    tsession.query(catalog.Mod)
                    .filter_by(source=mod_source, source_id=mod_source_id)
                    .first()
                )
                tsession.close()
                if result:
                    return PlainTextResponse(
                        status_code=412, content="Такая source-связка уже существует!"
                    )

            result = session.execute(insert_statement)
            rid = result.lastrowid
            session.commit()

            if not without_author:
                session = sessionmaker(bind=account.engine)()
                session.execute(
                    account.mod_and_author.insert().values(
                        mod_id=rid, user_id=user_id, owner=True
                    )
                )
                session.commit()
                session.close()

            session.close()

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
                return PlainTextResponse(status_code=500, content="JWT secret missing")

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
        else:
            session.close()
            return PlainTextResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")


async def _storage_transfer_complete_img(payload: dict) -> PlainTextResponse:
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
            resource_id_cleanup = int(callback_context.get("resource_id"))
        except (TypeError, ValueError):
            resource_id_cleanup = 0

    if not job_id or not callback_action or not target_path:
        return PlainTextResponse(status_code=400, content="Invalid payload")
    if storage_type not in {"avatar", "resource"}:
        return PlainTextResponse(status_code=400, content="Invalid payload")
    if callback_action not in {"avatar_set", "resource_add", "resource_edit"}:
        return PlainTextResponse(status_code=400, content="Invalid payload")

    if callback_action == "avatar_set" and storage_type != "avatar":
        return PlainTextResponse(status_code=400, content="Invalid payload")
    if callback_action in {"resource_add", "resource_edit"} and storage_type != "resource":
        return PlainTextResponse(status_code=400, content="Invalid payload")

    if status != "success":
        logger.warning(
            "transfer img failed job_id=%s action=%s status=%s",
            job_id,
            callback_action,
            status,
        )
        if resource_id_cleanup > 0:
            session = sessionmaker(bind=catalog.engine)()
            session.query(catalog.Resource).filter_by(id=resource_id_cleanup).delete()
            session.commit()
            session.close()
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
            session = sessionmaker(bind=catalog.engine)()
            session.query(catalog.Resource).filter_by(id=resource_id_cleanup).delete()
            session.commit()
            session.close()
        return PlainTextResponse(status_code=504, content="Move timeout")
    if not move_ok:
        logger.warning(
            "transfer img move failed job_id=%s action=%s status=%s body=%s",
            job_id,
            callback_action,
            move_code,
            move_payload,
        )
        if resource_id_cleanup > 0:
            session = sessionmaker(bind=catalog.engine)()
            session.query(catalog.Resource).filter_by(id=resource_id_cleanup).delete()
            session.commit()
            session.close()
        return PlainTextResponse(status_code=500, content="Move failed")
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
        raw_resource_size = move_payload.get("final_bytes")
        try:
            parsed_resource_size = int(raw_resource_size)
        except (TypeError, ValueError):
            parsed_resource_size = None
        if parsed_resource_size is not None and parsed_resource_size > 0:
            resource_size = parsed_resource_size

    if callback_action == "avatar_set":
        user_id = callback_context.get("user_id")
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return PlainTextResponse(status_code=400, content="Invalid payload")

        session = sessionmaker(bind=account.engine)()
        user_query = session.query(account.Account).filter_by(id=user_id)
        user = user_query.first()
        if not user:
            session.close()
            await tools.storage_file_delete(type="avatar", path=target_path)
            return PlainTextResponse(status_code=404, content="User not found")
        old_avatar_url = str(user.avatar_url or "")
        user_query.update({"avatar_url": "local.webp"})
        session.commit()
        session.close()

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
        resource_id = callback_context.get("resource_id")
        try:
            resource_id = int(resource_id)
        except (TypeError, ValueError):
            return PlainTextResponse(status_code=400, content="Invalid payload")
        if resource_size is None:
            logger.warning(
                "resource size unresolved job_id=%s action=%s resource_id=%s target=%s move_payload=%s",
                job_id,
                callback_action,
                resource_id,
                target_path,
                move_payload,
            )

        session = sessionmaker(bind=catalog.engine)()
        resource_query = session.query(catalog.Resource).filter_by(id=resource_id)
        resource = resource_query.first()
        if not resource:
            session.close()
            await tools.storage_file_delete(type="resource", path=target_path)
            return PlainTextResponse(status_code=404, content="Resource not found")

        old_url = str(resource.url or "")
        update_values = {
            "url": f"local/{target_path}",
            "date_event": datetime.now(),
        }
        if resource_size is not None:
            update_values["size"] = resource_size
        resource_query.update(update_values)
        session.commit()
        session.close()

        if callback_action == "resource_edit" and old_url.startswith("local/"):
            old_path = old_url.replace("local/", "", 1)
            if old_path != target_path:
                await tools.storage_file_delete(type="resource", path=old_path)
        return PlainTextResponse(status_code=200, content="OK")

    return PlainTextResponse(status_code=400, content="Invalid payload")


@router.post(
    MAIN_URL + "/storage/transfer/complete",
    include_in_schema=False,
)
async def storage_transfer_complete(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return PlainTextResponse(status_code=401, content="Token not found")
    token = authorization.split(" ", 1)[1]
    payload = tools.decode_transfer_jwt(token, audience="manager")
    if not payload:
        return PlainTextResponse(status_code=403, content="Access denied")

    transfer_kind = str(payload.get("transfer_kind") or "archive").strip().lower()
    if transfer_kind == "img":
        return await _storage_transfer_complete_img(payload)

    status = payload.get("status")
    job_id = payload.get("job_id")
    mod_id = payload.get("mod_id")
    pack_format = payload.get("pack_format", "zip")
    update_only = bool(payload.get("update_only") or payload.get("keep_condition"))

    if not job_id or not mod_id:
        return PlainTextResponse(status_code=400, content="Invalid payload")
    try:
        mod_id = int(mod_id)
    except (TypeError, ValueError):
        return PlainTextResponse(status_code=400, content="Invalid payload")

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
        return PlainTextResponse(status_code=504, content="Move timeout")
    if not move_ok:
        logger.warning(
            "transfer move failed job_id=%s status=%s body=%s",
            job_id,
            move_code,
            move_payload,
        )
        return PlainTextResponse(status_code=500, content="Move failed")
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

    Session = sessionmaker(bind=catalog.engine)
    session = Session()
    mod = session.query(catalog.Mod).filter_by(id=mod_id).first()
    if not mod:
        session.close()
        return PlainTextResponse(status_code=404, content="Mod not found")
    if update_only:
        update_values = {
            "size": final_size,
            "date_update_file": datetime.now(),
        }
        if unpacked_size is not None:
            update_values["size_unpacked"] = unpacked_size
        session.query(catalog.Mod).filter_by(id=mod_id).update(update_values)
        session.commit()
        session.close()
        return PlainTextResponse(status_code=200, content="OK")

    if mod.condition == 0:
        session.close()
        return PlainTextResponse(status_code=200, content="Already finalized")

    if mod.source != "local" and mod.source_id is not None and mod.source_id > 0:
        source_conflict = (
            session.query(catalog.Mod.id)
            .filter(catalog.Mod.id != mod_id)
            .filter(catalog.Mod.condition == 0)
            .filter(catalog.Mod.source == mod.source)
            .filter(catalog.Mod.source_id == mod.source_id)
            .first()
        )
        if source_conflict:
            logger.warning(
                "transfer finalize conflict job_id=%s mod_id=%s source=%s source_id=%s conflict_mod_id=%s",
                job_id,
                mod_id,
                mod.source,
                mod.source_id,
                source_conflict.id,
            )

            session.execute(
                catalog.mods_dependencies.delete().where(
                    (catalog.mods_dependencies.c.mod_id == mod_id)
                    | (catalog.mods_dependencies.c.dependence == mod_id)
                )
            )
            session.execute(
                catalog.mods_tags.delete().where(catalog.mods_tags.c.mod_id == mod_id)
            )
            session.query(catalog.Mod).filter_by(id=mod_id).delete()
            session.commit()
            session.close()

            asession = sessionmaker(bind=account.engine)()
            asession.execute(
                account.mod_and_author.delete().where(
                    account.mod_and_author.c.mod_id == mod_id
                )
            )
            asession.commit()
            asession.close()

            return PlainTextResponse(
                status_code=412, content="Такая source-связка уже существует!"
            )

    update_values = {
        "condition": 0,
        "size": final_size,
    }
    if unpacked_size is not None:
        update_values["size_unpacked"] = unpacked_size
    session.query(catalog.Mod).filter_by(id=mod_id).update(update_values)
    session.query(catalog.Game).filter_by(id=mod.game).update(
        {catalog.Game.mods_count: func.coalesce(catalog.Game.mods_count, 0) + 1}
    )
    session.commit()
    session.close()

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
    mod_id: int = Path(description="ID мода"),
):
    """
    Функция скачивания мода и учета количества скачиваний.

    Не рекомендую на уровне пользователя использовать фактический адрес, т.к. он может менятся, и данная функци доп. уровень абстракции.
    """
    session = sessionmaker(bind=catalog.engine)()

    mod_query = session.query(catalog.Mod).filter(catalog.Mod.id == mod_id)
    mod = mod_query.first()
    if mod is None:
        session.close()
        return PlainTextResponse(status_code=404, content="Not found")
    else:
        raw_name = mod.name or ""
        mod_query.update({catalog.Mod.downloads: catalog.Mod.downloads + 1})
        session.query(catalog.Game).filter(catalog.Game.id == mod.game).update(
            {catalog.Game.mods_downloads: catalog.Game.mods_downloads + 1}
        )
        session.commit()

        session.close()

        statistics.update("mod", mod_id, "download")

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
    token: str = Header(
        "none",
        alias="x-token",
        description="Токен для проверки прав других пользователей, аналог токена - админские права просящего",
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

            session = sessionmaker(bind=catalog.engine)()

            # Выполнение запроса
            mods = session.query(catalog.Mod.id, catalog.Mod.public).filter(
                catalog.Mod.id.in_(ids_array)
            )
            mods = mods.filter(catalog.Mod.public <= 1).all()

            mods_ids = [i.id for i in mods]

            session.close()
            return mods_ids
        elif await tools.check_token(
            token_name="access_mods_check_anonymous", token=token
        ) or await tools.access_admin(response=response, request=request):
            return await tools.anonymous_access_mods(
                user_id=user, mods_ids=ids_array, edit=edit, check_mode=True
            )
        else:
            return PlainTextResponse(status_code=403, content="Access denied")
    else:
        return await tools.access_mods(
            response=response,
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
        return PlainTextResponse(
            status_code=413, content="the size of the array is not correct"
        )

    output = []

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod)
    if in_catalog:
        query = query.filter(catalog.Mod.public == 0)
    else:
        query = query.filter(catalog.Mod.public <= 1)

    query = query.filter(catalog.Mod.id.in_(ids_array))
    for i in query:
        output.append(i.id)

    session.close()
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
    tags=Query(
        [], description="Массив ID тегов", examples={"example": {"value": "[1, 2, 3]"}}
    ),
    game: int = Query(-1, description="ID игры."),
    allowed_ids=Query(
        [],
        description="Массив ID разрешенных модов.",
        examples={"example": {"value": "[1, 2, 3]"}},
    ),
    independents: bool = Query(
        False, description="Не передавать моды с зависимостями."
    ),
    dependencies=Query(
        [],
        description=(
            "Массив ID модов, которые должны быть в зависимостях у результата."
            " Применяется по логике И."
        ),
        examples={"example": {"value": "[1, 2, 3]"}},
    ),
    primary_sources=Query(
        [],
        description="Массив разрешенных источников.",
        examples={"example": {"value": "['local', 'steam']"}},
    ),
    allowed_sources_ids=Query(
        [],
        description="Массив ID модов в разрешенных источниках. Обязательно передать `primary_sources`.",
        examples={"example": {"value": "[1, 2, 3]"}},
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
    7. MOD_DOWNLOADS *(по умолчанию)* - сортировка по количеству загрузок.

    О фильтрации по зависимостям:
    `dependencies` принимает массив ID модов и применяет логику `И`.
    Одновременное использование `dependencies` и `independents=true` запрещено.
    """
    tags = tools.str_to_list(tags)
    dependencies = tools.str_to_list(dependencies)
    primary_sources = tools.str_to_list(primary_sources)
    allowed_ids = tools.str_to_list(allowed_ids)
    allowed_sources_ids = tools.str_to_list(allowed_sources_ids)

    if len(dependencies) > 0:
        try:
            dependencies = [int(dependence_id) for dependence_id in dependencies]
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=400,
                content={
                    "message": "dependencies filter should contain integer IDs",
                    "error_id": 3,
                },
            )
        dependencies = list(dict.fromkeys(dependencies))

    if page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        return JSONResponse(
            status_code=413, content={"message": "incorrect page size", "error_id": 1}
        )
    elif (
        len(tags)
        + len(dependencies)
        + len(primary_sources)
        + len(allowed_ids)
        + len(allowed_sources_ids)
    ) > LIMITS.mod.filters_max:
        return JSONResponse(
            status_code=413,
            content={
                "message": "the maximum complexity of filters is 90 elements in sum",
                "error_id": 2,
            },
        )
    elif independents and len(dependencies) > 0:
        return JSONResponse(
            status_code=400,
            content={
                "message": "independents filter conflicts with dependencies filter",
                "error_id": 4,
            },
        )

    want_not_public = show_not_public and user > 0
    if want_not_public:
        if user <= 0:
            return PlainTextResponse(status_code=403, content="Заблокировано!")

        access_result = await account.check_access(request=request, response=response)
        req_user_id = access_result.get("owner_id", -1) if access_result else -1
        if req_user_id < 0:
            return PlainTextResponse(
                status_code=401, content="Недействительный ключ сессии!"
            )

        if req_user_id != user:
            session_account = sessionmaker(bind=account.engine)()
            user_req = (
                session_account.query(account.Account.admin)
                .filter_by(id=req_user_id)
                .first()
            )
            session_account.close()

            if not user_req or not user_req.admin:
                return PlainTextResponse(status_code=403, content="Заблокировано!")

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod.id)
    if description:
        query = query.add_columns(catalog.Mod.description)
    if short_description:
        query = query.add_column(catalog.Mod.short_description)
    if dates:
        query = query.add_columns(
            catalog.Mod.date_update_file,
            catalog.Mod.date_creation,
            catalog.Mod.date_edit,
        )
    if general:
        query = query.add_columns(
            catalog.Mod.name,
            catalog.Mod.size,
            catalog.Mod.size_unpacked,
            catalog.Mod.source,
            catalog.Mod.source_id,
            catalog.Mod.downloads,
        )

    query = query.order_by(tools.sort_mods(sort))
    query = query.filter(catalog.Mod.condition == 0)
    only_publics = not want_not_public
    if only_publics:
        query = query.filter(catalog.Mod.public == 0)

    # Фильтрация по конкретным ID
    if len(allowed_ids) > 0:
        query = query.filter(catalog.Mod.id.in_(allowed_ids))

    # Фильтрация по играм
    if game > 0:
        query = query.filter(catalog.Mod.game == game)

    # Фильтрация по первоисточникам
    if len(primary_sources) > 0:
        query = query.filter(catalog.Mod.source.in_(primary_sources))
        if len(allowed_sources_ids) > 0:
            query = query.filter(catalog.Mod.source_id.in_(allowed_sources_ids))

    if independents:
        query = query.outerjoin(
            catalog.mods_dependencies,
            catalog.Mod.id == catalog.mods_dependencies.c.mod_id,
        ).filter(catalog.mods_dependencies.c.mod_id.is_(None))
    elif len(dependencies) > 0:
        mods_with_dependencies = (
            session.query(catalog.mods_dependencies.c.mod_id)
            .filter(catalog.mods_dependencies.c.dependence.in_(dependencies))
            .group_by(catalog.mods_dependencies.c.mod_id)
            .having(
                func.count(func.distinct(catalog.mods_dependencies.c.dependence))
                == len(dependencies)
            )
            .subquery()
        )
        query = query.join(
            mods_with_dependencies,
            catalog.Mod.id == mods_with_dependencies.c.mod_id,
        )

    # Фильтрация по имени
    if len(name) > 0:
        logger.debug("Filtering mods by name length=%s", len(name))
        query = query.filter(catalog.Mod.name.ilike(f"%{name}%"))

    # Фильтрация по тегам
    if len(tags) > 0:
        for tag in tags:
            query = query.filter(catalog.Mod.tags.any(catalog.Tag.id == tag))

    # Сортировка по пользователю
    if user > 0:
        query = query.join(
            account.mod_and_author, account.mod_and_author.c.mod_id == catalog.Mod.id
        )
        query = query.filter(account.mod_and_author.c.user_id == user)

        if user_owner in [0, 1]:
            query = query.filter(account.mod_and_author.c.owner == (user_owner == 0))

    mods_count = query.count()

    offset = page_size * page
    mods = query.offset(offset).limit(page_size).all()

    session.close()

    result_access_mods: list[int] = []
    if not only_publics:
        result_access_mods = await tools.access_mods(
            response=response,
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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    output = {}

    # Создание сессии
    session = sessionmaker(bind=catalog.engine)()

    # Выполнение запроса
    query = session.query(catalog.Mod.condition)
    if description:
        query = query.add_columns(catalog.Mod.description)
    if short_description:
        query = query.add_column(catalog.Mod.short_description)
    if dates:
        query = query.add_columns(
            catalog.Mod.date_update_file,
            catalog.Mod.date_creation,
            catalog.Mod.date_edit,
        )
    if general:
        query = query.add_columns(
            catalog.Mod.name,
            catalog.Mod.size,
            catalog.Mod.size_unpacked,
            catalog.Mod.source,
            catalog.Mod.source_id,
            catalog.Mod.downloads,
        )
    if game:
        query = query.add_columns(catalog.Mod.game)

    query = query.add_columns(catalog.Mod.public)
    query = query.filter(catalog.Mod.id == mod_id)
    output["pre_result"] = query.first()

    if not output["pre_result"]:
        return PlainTextResponse(status_code=404, content="Mod not found.")

    if output["pre_result"].public >= 2:
        result_access = await tools.access_mods(
            response=response, request=request, mods_ids=mod_id, edit=False
        )
        if not result_access:
            return result_access

    if dependencies:
        query = session.query(catalog.mods_dependencies.c.dependence)
        query = query.filter(catalog.mods_dependencies.c.mod_id == mod_id)

        count = query.count()
        result = query.limit(100).all()
        output["dependencies"] = [row[0] for row in result]
        output["dependencies_count"] = count

    if game:
        result = (
            session.query(catalog.Game.name)
            .filter_by(id=output["pre_result"].game)
            .first()
        )

        output["game"] = {"id": output["pre_result"].game, "name": result.name}

    # Закрытие сессии
    session.close()

    output["result"] = {"condition": output["pre_result"].condition}
    if description:
        output["result"]["description"] = output["pre_result"].description
    if short_description:
        output["result"]["short_description"] = output["pre_result"].short_description
    if dates:
        strformattime = "%Y-%m-%dT%H:%M:%S"

        output["result"]["date_update_file"] = output[
            "pre_result"
        ].date_update_file.strftime(strformattime)
        output["result"]["date_edit"] = output["pre_result"].date_edit.strftime(
            strformattime
        )
        output["result"]["date_creation"] = output["pre_result"].date_creation.strftime(
            strformattime
        )
    if general:
        output["result"]["name"] = output["pre_result"].name
        output["result"]["size"] = output["pre_result"].size
        output["result"]["size_unpacked"] = output["pre_result"].size_unpacked
        output["result"]["source"] = output["pre_result"].source
        output["result"]["source_id"] = output["pre_result"].source_id
        output["result"]["downloads"] = output["pre_result"].downloads
        output["result"]["public"] = output["pre_result"].public
    if game:
        output["result"]["game"] = output["game"]
        del output["game"]
    del output["pre_result"]

    if authors:
        # Создание сессии
        session_account = sessionmaker(bind=account.engine)()

        # Исполнение
        row = session_account.query(account.mod_and_author).filter_by(mod_id=mod_id)
        row = row.limit(100)

        row_results = row.all()

        output["authors"] = {}
        for i in row_results:
            output["authors"][i.user_id] = {"owner": i.owner}

        session_account.close()

    statistics.update("mod", mod_id, "page_view")
    return JSONResponse(status_code=200, content=output)


@router.get(
    MAIN_URL + "/mods/{mod_id}/resources",
    tags=["Mod", "Resource"],
    summary="Ресурсы мода",
    status_code=200,
    responses={
        200: {"description": "OK"},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
        examples={"example": {"value": "[1, 2, 3]"}},
    ),
    page_size: int = Query(
        LIMITS.page.default,
        description="Размер 1 страницы. Диапазон - 1...50 элементов.",
    ),
    page: int = Query(0, description="Номер страницы. Не должна быть отрицательной."),
    types_resources=Query(
        [],
        description="Фильтрация по типу ресурсов *(массив типов)*.",
        examples={"example": {"value": '["logo", "screenshot"]'}},
    ),
    only_urls: bool = Query(
        False, description="Возвращать только ссылки или полную информацию."
    ),
):
    resources_list_id = tools.str_to_list(resources_list_id)
    types_resources = tools.str_to_list(types_resources)

    if len(types_resources) + len(resources_list_id) > LIMITS.resource.filters_max:
        return JSONResponse(
            status_code=413,
            content={
                "message": "the maximum complexity of filters is 120 elements in sum",
                "error_id": 1,
            },
        )
    elif page_size > LIMITS.page.max or page_size < LIMITS.page.min:
        return JSONResponse(
            status_code=413, content={"message": "incorrect page size", "error_id": 2}
        )
    elif page < 0:
        return JSONResponse(
            status_code=413, content={"message": "incorrect page", "error_id": 3}
        )

    session = sessionmaker(bind=catalog.engine)()
    mod_exists = session.query(catalog.Mod.id).filter_by(id=mod_id).first()
    session.close()
    if not mod_exists:
        return PlainTextResponse(status_code=404, content="Mod not found.")

    access_result = await tools.access_mods(
        response=response, request=request, mods_ids=[mod_id]
    )
    if access_result is not True:
        return access_result

    session = sessionmaker(bind=catalog.engine)()
    query = session.query(catalog.Resource)
    query = query.filter_by(owner_type="mods", owner_id=mod_id)
    if len(resources_list_id) > 0:
        query = query.filter(catalog.Resource.id.in_(resources_list_id))
    if len(types_resources) > 0:
        query = query.filter(catalog.Resource.type.in_(types_resources))

    resources_count = query.count()
    offset = page_size * page
    resources = query.offset(offset).limit(page_size).all()
    session.close()

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        404: {"description": "Мод не найден."},
    },
)
async def mod_tags(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
    only_ids: bool = Query(False, description="Если True вернет только ID тегов."),
):
    session = sessionmaker(bind=catalog.engine)()
    mod_exists = session.query(catalog.Mod.id).filter_by(id=mod_id).first()
    session.close()
    if not mod_exists:
        return PlainTextResponse(status_code=404, content="Mod not found.")

    access_result = await tools.access_mods(
        response=response, request=request, mods_ids=[mod_id]
    )
    if access_result is not True:
        return access_result

    session = sessionmaker(bind=catalog.engine)()
    query = session.query(catalog.Tag).join(catalog.mods_tags)
    query = query.filter(catalog.mods_tags.c.mod_id == mod_id)
    tags = query.all()
    session.close()

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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
        404: {"description": "Мод не найден."},
    },
)
async def mod_dependencies(
    response: Response,
    request: Request,
    mod_id: int = Path(description="ID мода"),
):
    session = sessionmaker(bind=catalog.engine)()
    mod_exists = session.query(catalog.Mod.id).filter_by(id=mod_id).first()
    session.close()
    if not mod_exists:
        return PlainTextResponse(status_code=404, content="Mod not found.")

    access_result = await tools.access_mods(
        response=response, request=request, mods_ids=[mod_id]
    )
    if access_result is not True:
        return access_result

    session = sessionmaker(bind=catalog.engine)()
    query = session.query(catalog.mods_dependencies.c.dependence)
    query = query.filter(catalog.mods_dependencies.c.mod_id == mod_id)
    dependencies = [row[0] for row in query.all()]
    session.close()

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
    access_result = await tools.access_mods(
        response=response, request=request, mods_ids=mod_id, edit=True
    )
    if access_result is True:
        body: dict[str, object] = {}
        if mod_name is not None:
            if len(mod_name) > LIMITS.mod.name_edit_max:
                return PlainTextResponse(
                    status_code=413, content="Название слишком длинное!"
                )
            elif len(mod_name) < LIMITS.mod.name_min:
                return PlainTextResponse(
                    status_code=411, content="Название слишком короткое!"
                )
            body["name"] = mod_name
        if mod_short_description is not None:
            if (
                len(re.sub(r"\s+", " ", mod_short_description))
                > LIMITS.mod.short_desc_max
            ):
                return PlainTextResponse(
                    status_code=413, content="Короткое описание слишком длинное!"
                )
            body["short_description"] = mod_short_description
        if mod_description is not None:
            if len(re.sub(r"\s+", " ", mod_description)) > LIMITS.mod.desc_max:
                return PlainTextResponse(
                    status_code=413, content="Описание слишком длинное!"
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

            session = sessionmaker(bind=catalog.engine)()
            result = (
                session.query(catalog.Mod)
                .filter_by(source=mod_source, source_id=body["source_id"])
                .first()
            )
            session.close()
            if result:
                return PlainTextResponse(
                    status_code=412, content="Такая source-связка уже существует!"
                )
        if mod_game is not None:
            if not await tools.check_game_exists(mod_game):
                return PlainTextResponse(
                    status_code=412, content="Такой игры не существует!"
                )
            body["game"] = mod_game
        if mod_public is not None:
            if mod_public in [0, 1, 2]:
                body["public"] = mod_public

        if len(body) <= 0:
            return PlainTextResponse(
                status_code=411, content="Ничего не было изменено!"
            )

        if len(body) > 0:
            body["date_edit"] = datetime.now()

        session = sessionmaker(bind=catalog.engine)()
        session.query(catalog.Mod).filter_by(id=mod_id).update(body)
        session.commit()
        session.close()
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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    access_result = await account.check_access(request=request, response=response)

    if access_result and access_result.get("owner_id", -1) >= 0:
        # Создание сессии
        Session = sessionmaker(bind=account.engine)
        session = Session()

        req_user_id = access_result.get("owner_id", -1)
        user_req = session.query(account.Account).filter_by(id=req_user_id).first()
        user_add = session.query(account.Account).filter_by(id=author).first()

        async def mini():
            if not user_add:
                return False
            elif user_req.admin:
                return True
            else:
                if user_req.mute_until and user_req.mute_until > datetime.now():
                    return False

                in_mod = (
                    session.query(account.mod_and_author)
                    .filter_by(mod_id=mod_id, user_id=req_user_id)
                    .first()
                )

                if in_mod:
                    if in_mod.owner:
                        if req_user_id == author and not mode:
                            return False

                        return True
                    elif req_user_id == author and not mode:
                        return True
                elif user_req.change_authorship_mods:
                    return True
            return False

        if await mini():
            if mode:
                has_owner = (
                    session.query(account.mod_and_author)
                    .filter_by(mod_id=mod_id, owner=True)
                    .first()
                )
                if owner and has_owner:
                    session.query(account.mod_and_author).filter_by(
                        mod_id=mod_id, owner=True
                    ).update({"owner": False})
                    session.commit()

                has_target = (
                    session.query(account.mod_and_author)
                    .filter_by(mod_id=mod_id, user_id=author)
                    .first()
                )
                if has_target:
                    session.query(account.mod_and_author).filter_by(
                        mod_id=mod_id, user_id=author
                    ).update({"owner": owner})
                else:
                    insert_statement = insert(account.mod_and_author).values(
                        user_id=author, owner=owner, mod_id=mod_id
                    )
                    session.execute(insert_statement)
                session.commit()
            else:
                delete_member = account.mod_and_author.delete().where(
                    account.mod_and_author.c.mod_id == mod_id,
                    account.mod_and_author.c.user_id == author,
                )
                # Выполнение операции DELETE
                session.execute(delete_member)
                session.commit()

            session.close()
            return JSONResponse(status_code=200, content="Выполнено")
        else:
            session.close()
            return JSONResponse(status_code=403, content="Заблокировано!")
    else:
        return JSONResponse(status_code=401, content="Недействительный ключ сессии!")


@router.delete(
    MAIN_URL + "/mods/{mod_id}",
    tags=["Mod"],
    summary="Удаление мода",
    status_code=200,
    responses={
        200: {"description": "Мод успешно удален."},
        401: standarts.responses[401],
        403: standarts.responses["non-admin"][403],
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
    access_result = await account.check_access(request=request, response=response)
    logger.info("Delete mod request received mod_id=%s", mod_id)

    if not access_result or access_result.get("owner_id", -1) < 0:
        logger.info("Delete mod denied: invalid session mod_id=%s", mod_id)
        return PlainTextResponse(
            status_code=401, content="Недействительный ключ сессии!"
        )
    user_id = access_result.get("owner_id", -1)
    logger.info("Delete mod auth ok mod_id=%s user_id=%s", mod_id, user_id)

    # Создание сессии для аккаунтов
    Session = sessionmaker(bind=account.engine)
    session = Session()

    try:
        user_req = (
            session.query(account.Account)
            .filter_by(id=access_result.get("owner_id"))
            .first()
        )
        if not user_req:
            return PlainTextResponse(status_code=403, content="Пользователь не найден!")

        async def mini():
            if user_req.admin:
                return True
            if user_req.mute_until and user_req.mute_until > datetime.now():
                return False

            in_mod = (
                session.query(account.mod_and_author)
                .filter_by(mod_id=mod_id, user_id=user_id)
                .first()
            )

            if in_mod and user_req.delete_self_mods and in_mod.owner:
                return True
            if user_req.delete_mods:
                return True

            return False

        if not await mini():
            logger.info(
                "Delete mod denied by permissions mod_id=%s user_id=%s",
                mod_id,
                user_id,
            )
            return PlainTextResponse(status_code=403, content="Заблокировано!")
    finally:
        session.close()

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
        return PlainTextResponse(status_code=500, content="Не удалось удалить мод!")

    # Создание сессии для базы модов
    session = sessionmaker(bind=catalog.engine)()
    try:
        mod_obj = session.query(catalog.Mod).filter_by(id=mod_id).first()
        if not mod_obj:
            return PlainTextResponse(status_code=404, content="Мод не найден")

        game_id = mod_obj.game

        # Удаление записей
        session.query(catalog.Mod).filter_by(id=mod_id).delete()
        session.query(catalog.mods_dependencies).filter_by(mod_id=mod_id).delete()
        session.query(catalog.mods_tags).filter_by(mod_id=mod_id).delete()
        session.commit()

        # Обновление количества модов в игре
        session.query(catalog.Game).filter_by(id=game_id).update(
            {catalog.Game.mods_count: catalog.Game.mods_count - 1}
        )
        session.commit()

    finally:
        session.close()

    return PlainTextResponse(status_code=200, content="Удалено")
