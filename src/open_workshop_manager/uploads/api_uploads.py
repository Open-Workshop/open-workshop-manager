"""Unified upload command routes."""

from __future__ import annotations

import datetime
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import delete, func, select, update

from open_workshop_manager import mod_events
from open_workshop_manager import settings as config, standarts, tools
from open_workshop_manager.api_models import UploadCreate, UploadRead
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_JOBS: dict[str, UploadRead] = {}

VALID_UPLOAD_KINDS = {"mod_archive", "resource_image", "profile_avatar"}
VALID_UPLOAD_MODES = {"create", "replace"}
VALID_RESOURCE_OWNER_TYPES = {"mods", "games"}
VALID_IMAGE_CALLBACK_ACTIONS = {"avatar_set", "resource_add", "resource_edit"}
VALID_IMAGE_STORAGE_TYPES = {"avatar", "resource"}


def _raise_not_found(request: Request, code: str, detail: str) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail=detail,
        code=code,
        instance=str(request.url),
    )


def _raise_bad_request(request: Request, detail: str, code: str = "BAD_REQUEST") -> None:
    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail=detail,
        code=code,
        instance=str(request.url),
    )


def _transfer_payload(job_id: str) -> dict[str, object]:
    return {
        "job_id": job_id,
        "aud": "storage",
        "iss": "manager",
    }


def _make_transfer_urls(job_id: str, token: str) -> tuple[str, str]:
    transfer_url = f"{config.STORAGE_URL}/transfer/upload?token={quote(token)}&job_id={job_id}"
    ws_url = f"{config.STORAGE_URL}/transfer/ws/{job_id}?token={quote(token)}"
    return transfer_url, ws_url


def _store_job(job: UploadRead) -> UploadRead:
    UPLOAD_JOBS[job.id] = job
    return job


def _upload_row(job: UploadRead) -> catalog.UploadJob:
    return catalog.UploadJob(
        id=job.id,
        kind=job.kind,
        status=job.status,
        transfer_url=job.transfer_url,
        ws_url=job.ws_url,
        expires_at=job.expires_at,
        owner_type=job.owner_type,
        owner_id=job.owner_id,
        mode=job.mode,
        resource_id=job.resource_id,
    )


async def _load_job(job_id: str) -> UploadRead | None:
    job = UPLOAD_JOBS.get(job_id)
    if job is None:
        async with catalog.AsyncSessionLocal() as session:
            row = await session.get(catalog.UploadJob, job_id)
            if row is None:
                return None
            job = UploadRead.model_validate(row)
            UPLOAD_JOBS[job_id] = job
    return job


async def _update_job_status(job_id: str, status: str) -> None:
    job = UPLOAD_JOBS.get(job_id)
    if job is not None:
        UPLOAD_JOBS[job_id] = job.model_copy(update={"status": status})

    async with catalog.AsyncSessionLocal() as session:
        row = await session.get(catalog.UploadJob, job_id)
        if row is None:
            return
        row.status = status
        await session.commit()


def _coerce_int(value: object | None, default: int = 0) -> int:
    try:
        if value is None:
            return default
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _coerce_optional_int(value: object | None) -> int | None:
    try:
        if value is None:
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


async def _require_mod_access(request: Request, mod_id: int) -> None:
    await tools.access_mods(request=request, mods_ids=[mod_id], edit=True)


async def _require_profile_avatar_access(request: Request, profile_id: int) -> None:
    access_result = await tools.access_profile(request=request, profile_id=profile_id)
    if not access_result.authenticated:
        raise standarts.UnauthorizedError(instance=str(request.url))
    if not access_result.edit.avatar.value:
        raise standarts.ForbiddenError(
            detail=access_result.edit.avatar.reason,
            instance=str(request.url),
            context={"reason_code": access_result.edit.avatar.reason_code},
        )


async def _require_resource_owner_access(
    request: Request,
    owner_type: str,
    owner_id: int,
) -> None:
    if owner_type == "mods":
        await tools.access_mods(request=request, mods_ids=[owner_id], edit=True)
        return
    if owner_type == "games":
        await tools.access_admin(request=request)
        return
    raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))


def _invalid_upload_payload(request: Request) -> None:
    _raise_bad_request(request, "Invalid upload payload.", code="INVALID_UPLOAD_PAYLOAD")


def _unsupported_upload_kind(request: Request) -> None:
    _raise_bad_request(request, "Unsupported upload kind.", code="UNSUPPORTED_UPLOAD_KIND")


def _completion_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _job_id_from_payload(request: Request, payload: dict[str, object]) -> str:
    token_job_id = str(payload.get("job_id") or "")
    query_job_id = request.query_params.get("job_id") or ""
    if query_job_id and token_job_id and query_job_id != token_job_id:
        raise standarts.ForbiddenError(instance=str(request.url))
    return query_job_id or token_job_id


async def _handle_archive_completion(
    request: Request,
    payload: dict[str, object],
    job_id: str,
) -> Response:
    mod_id = _coerce_int(payload.get("mod_id"), default=-1)
    if mod_id <= 0:
        _invalid_upload_payload(request)

    status = str(payload.get("status") or "").strip().lower()
    if status != "success":
        logger.warning("transfer failed job_id=%s status=%s", job_id, status or "-")
        await _update_job_status(job_id, "failed")
        return Response(status_code=202, content="Transfer failed")

    pack_format = str(payload.get("pack_format") or "zip").strip() or "zip"
    update_only = bool(payload.get("update_only") or payload.get("keep_condition"))
    destination_path = f"mods/{mod_id}/main.{pack_format}"

    try:
        move_code, move_payload, move_ok = await tools.storage_job_move(
            job_id=job_id,
            type="archive",
            path=destination_path,
        )
    except Exception:
        logger.exception("transfer move exception job_id=%s mod_id=%s", job_id, mod_id)
        await _update_job_status(job_id, "failed")
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
        await _update_job_status(job_id, "failed")
        raise standarts.InternalServerError(
            detail="Move failed",
            instance=str(request.url),
        )

    final_size = None
    unpacked_size = None
    if isinstance(move_payload, dict):
        final_size = move_payload.get("final_bytes")
        unpacked_size = move_payload.get("unpacked_bytes")
    if final_size is None:
        final_size = payload.get("bytes", 0)
    if unpacked_size is None:
        unpacked_size = payload.get("unpacked_bytes")

    final_size_value = _coerce_int(final_size, default=0)
    unpacked_size_value = _coerce_optional_int(unpacked_size)

    async with catalog.AsyncSessionLocal() as session:
        mod = await session.get(catalog.Mod, mod_id)
        if mod is None:
            await _update_job_status(job_id, "failed")
            raise standarts.NotFoundError(
                detail="Mod not found",
                instance=str(request.url),
            )

        if update_only:
            update_values: dict[str, object] = {
                "size": final_size_value,
                "date_update_file": datetime.datetime.now(),
            }
            if unpacked_size_value is not None:
                update_values["size_unpacked"] = unpacked_size_value
            await session.execute(
                update(catalog.Mod).where(catalog.Mod.id == mod_id).values(**update_values)
            )
            await session.commit()
            await mod_events.publish_mod_event(
                mod_events.MOD_EVENT_CHANGED,
                mod_id,
                getattr(mod, "name", ""),
                getattr(mod, "description", None),
                getattr(mod, "public", 0),
            )
            await _update_job_status(job_id, "completed")
            return Response(status_code=200)

        if int(getattr(mod, "condition", 0) or 0) == 0:
            await _update_job_status(job_id, "completed")
            return Response(status_code=200)

        if (
            getattr(mod, "source", "local") != "local"
            and getattr(mod, "source_id", None) is not None
            and int(getattr(mod, "source_id", 0) or 0) > 0
        ):
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

                await _update_job_status(job_id, "failed")
                raise standarts.PreconditionFailedError(
                    detail="Такая source-связка уже существует!",
                    instance=str(request.url),
                )

        update_values = {
            "condition": 0,
            "size": final_size_value,
        }
        if unpacked_size_value is not None:
            update_values["size_unpacked"] = unpacked_size_value
        await session.execute(
            update(catalog.Mod).where(catalog.Mod.id == mod_id).values(**update_values)
        )
        if getattr(mod, "game", None) is not None:
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

    await mod_events.publish_mod_event(
        mod_events.MOD_EVENT_ADDED,
        mod_id,
        getattr(mod, "name", ""),
        getattr(mod, "description", None),
        getattr(mod, "public", 0),
    )
    await _update_job_status(job_id, "completed")
    return Response(status_code=200)


async def _handle_image_completion(
    request: Request,
    payload: dict[str, object],
    job_id: str,
) -> Response:
    status = str(payload.get("status") or "").strip().lower()
    callback_action = str(payload.get("callback_action") or "").strip().lower()
    storage_type = str(payload.get("storage_type") or "").strip().lower()
    target_path = str(payload.get("target_path") or "").strip()
    callback_context = payload.get("callback_context")
    if not target_path or not callback_action or not storage_type:
        _invalid_upload_payload(request)
    if callback_action not in VALID_IMAGE_CALLBACK_ACTIONS:
        _invalid_upload_payload(request)
    if storage_type not in VALID_IMAGE_STORAGE_TYPES:
        _invalid_upload_payload(request)
    if not isinstance(callback_context, dict):
        _invalid_upload_payload(request)
    if callback_action == "avatar_set" and storage_type != "avatar":
        _invalid_upload_payload(request)
    if callback_action in {"resource_add", "resource_edit"} and storage_type != "resource":
        _invalid_upload_payload(request)

    resource_id_value = _coerce_int(callback_context.get("resource_id"), default=0)
    user_id_value = _coerce_int(callback_context.get("user_id"), default=0)

    if status != "success":
        logger.warning(
            "transfer img failed job_id=%s action=%s status=%s",
            job_id,
            callback_action,
            status or "-",
        )
        if callback_action == "resource_add" and resource_id_value > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(catalog.Resource.id == resource_id_value)
                )
                await session.commit()
        await _update_job_status(job_id, "failed")
        return Response(status_code=202, content="Transfer failed")

    try:
        move_code, move_payload, move_ok = await tools.storage_job_move(
            job_id=job_id,
            type=storage_type,
            path=target_path,
        )
    except Exception:
        logger.exception(
            "transfer img move exception job_id=%s action=%s path=%s",
            job_id,
            callback_action,
            target_path,
        )
        if callback_action == "resource_add" and resource_id_value > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(catalog.Resource.id == resource_id_value)
                )
                await session.commit()
        await _update_job_status(job_id, "failed")
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
        if callback_action == "resource_add" and resource_id_value > 0:
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(catalog.Resource.id == resource_id_value)
                )
                await session.commit()
        await _update_job_status(job_id, "failed")
        raise standarts.InternalServerError(
            detail="Move failed",
            instance=str(request.url),
        )

    resource_size = None
    if isinstance(move_payload, dict):
        resource_size = move_payload.get("final_bytes")
    resource_size_value = _coerce_optional_int(resource_size)

    if callback_action == "avatar_set":
        if user_id_value <= 0:
            _invalid_upload_payload(request)

        async with account.AsyncSessionLocal() as session:
            user = await session.get(account.Account, user_id_value)
            if user is None:
                await tools.storage_file_delete(type="avatar", path=target_path)
                await _update_job_status(job_id, "failed")
                raise standarts.NotFoundError(
                    detail="User not found",
                    instance=str(request.url),
                )

            old_avatar_url = str(getattr(user, "avatar_url", "") or "")
            user.avatar_url = "local.webp"
            await session.commit()

        if old_avatar_url.startswith("local"):
            old_ext = old_avatar_url.split(".", 1)[1] if "." in old_avatar_url else "webp"
            old_path = f"{user_id_value}.{old_ext}"
            if old_path != target_path:
                await tools.storage_file_delete(type="avatar", path=old_path)

        await _update_job_status(job_id, "completed")
        return Response(status_code=200)

    if resource_id_value <= 0:
        _invalid_upload_payload(request)

    if resource_size_value is None:
        logger.warning(
            "resource transfer rejected (invalid final_bytes) job_id=%s action=%s resource_id=%s target=%s move_payload=%s",
            job_id,
            callback_action,
            resource_id_value,
            target_path,
            move_payload,
        )
        await tools.storage_file_delete(type="resource", path=target_path)
        if callback_action == "resource_add":
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(
                    delete(catalog.Resource).where(catalog.Resource.id == resource_id_value)
                )
                await session.commit()
        await _update_job_status(job_id, "failed")
        return Response(status_code=202, content="Invalid file size")

    async with catalog.AsyncSessionLocal() as session:
        resource = await session.get(catalog.Resource, resource_id_value)
        if resource is None:
            await tools.storage_file_delete(type="resource", path=target_path)
            await _update_job_status(job_id, "failed")
            raise standarts.NotFoundError(
                detail="Resource not found",
                instance=str(request.url),
            )

        old_url = str(getattr(resource, "url", "") or "")
        resource.url = f"local/{target_path}"
        resource.date_event = datetime.datetime.now()
        resource.size = resource_size_value
        await session.commit()

    if callback_action == "resource_edit" and old_url.startswith("local/"):
        old_path = old_url.replace("local/", "", 1)
        if old_path != target_path:
            await tools.storage_file_delete(type="resource", path=old_path)

    await _update_job_status(job_id, "completed")
    return Response(status_code=200)


@router.post(
    "/uploads",
    tags=["Upload"],
    status_code=201,
    response_model=UploadRead,
    response_model_exclude_none=True,
)
async def create_upload(response: Response, request: Request, payload: UploadCreate) -> UploadRead:
    if not getattr(config, "TRANSFER_JWT_SECRET", ""):
        raise standarts.InternalServerError(
            detail="JWT secret missing.",
            instance=str(request.url),
            code="STORAGE_UNAVAILABLE",
        )

    kind = (payload.kind or "").strip().lower()
    mode = (payload.mode or "").strip().lower()
    if kind not in VALID_UPLOAD_KINDS:
        _unsupported_upload_kind(request)
    if mode not in VALID_UPLOAD_MODES:
        _invalid_upload_payload(request)

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=ttl_seconds
    )

    response.headers["Location"] = f"/uploads/{job_id}"

    if kind == "mod_archive":
        if payload.owner_type != "mod" or payload.owner_id is None:
            _invalid_upload_payload(request)
        await _require_mod_access(request, payload.owner_id)

        token = tools.create_transfer_jwt(
            {
                **_transfer_payload(job_id),
                "transfer_kind": "archive",
                "mod_id": payload.owner_id,
                "pack_format": payload.format or "zip",
                "pack_level": _coerce_int(payload.compression_level, default=3),
                "update_only": mode == "replace",
                "mode": mode,
            },
            audience="storage",
            ttl_seconds=ttl_seconds,
        )
        if not token:
            raise standarts.InternalServerError(
                detail="JWT secret missing.",
                instance=str(request.url),
                code="STORAGE_UNAVAILABLE",
            )

        transfer_url, ws_url = _make_transfer_urls(job_id, token)
        job = UploadRead(
            id=job_id,
            kind=kind,
            status="created",
            transfer_url=transfer_url,
            ws_url=ws_url,
            expires_at=expires_at,
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
            mode=mode,
        )
        async with catalog.AsyncSessionLocal() as session:
            session.add(_upload_row(job))
            await session.commit()
        return _store_job(job)

    if kind == "resource_image":
        if payload.owner_type != "resource":
            _invalid_upload_payload(request)

        if mode == "create":
            if payload.resource_owner_type is None or payload.resource_owner_id is None:
                _invalid_upload_payload(request)
            if payload.resource_owner_type not in VALID_RESOURCE_OWNER_TYPES:
                raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))
            if payload.resource_type is None:
                _invalid_upload_payload(request)
            await _require_resource_owner_access(
                request,
                payload.resource_owner_type,
                payload.resource_owner_id,
            )

            async with catalog.AsyncSessionLocal() as session:
                resource = catalog.Resource(
                    type=payload.resource_type,
                    url="",
                    size=None,
                    date_event=datetime.datetime.now(),
                    owner_type=payload.resource_owner_type,
                    owner_id=payload.resource_owner_id,
                )
                session.add(resource)
                await session.flush()
                token = tools.create_transfer_jwt(
                    {
                        **_transfer_payload(job_id),
                        "transfer_kind": "img",
                        "storage_type": "resource",
                        "callback_action": "resource_add",
                        "callback_context": {"resource_id": resource.id},
                        "target_path": f"{payload.resource_owner_type}/{payload.resource_owner_id}/{resource.id}.webp",
                    },
                    audience="storage",
                    ttl_seconds=ttl_seconds,
                )
                if not token:
                    await session.rollback()
                    raise standarts.InternalServerError(
                        detail="JWT secret missing.",
                        instance=str(request.url),
                        code="STORAGE_UNAVAILABLE",
                    )

                transfer_url, ws_url = _make_transfer_urls(job_id, token)
                job = UploadRead(
                    id=job_id,
                    kind=kind,
                    status="created",
                    transfer_url=transfer_url,
                    ws_url=ws_url,
                    expires_at=expires_at,
                    owner_type=payload.owner_type,
                    owner_id=payload.resource_owner_id,
                    mode=mode,
                    resource_id=resource.id,
                )
                session.add(_upload_row(job))
                await session.commit()
            return _store_job(job)

        if payload.owner_id is None:
            _invalid_upload_payload(request)

        async with catalog.AsyncSessionLocal() as session:
            resource = await session.get(catalog.Resource, payload.owner_id)
            if resource is None:
                _raise_not_found(request, "RESOURCE_NOT_FOUND", "Resource not found.")

            if payload.resource_owner_type is not None and payload.resource_owner_type != resource.owner_type:
                _invalid_upload_payload(request)
            if (
                payload.resource_owner_id is not None
                and int(payload.resource_owner_id) != int(resource.owner_id)
            ):
                _invalid_upload_payload(request)

            await _require_resource_owner_access(
                request,
                str(resource.owner_type),
                int(resource.owner_id),
            )

            if payload.resource_type is not None:
                resource.type = payload.resource_type

            target_owner_type = str(resource.owner_type)
            target_owner_id = int(resource.owner_id)
            resource_id = int(resource.id)

            token = tools.create_transfer_jwt(
                {
                    **_transfer_payload(job_id),
                    "transfer_kind": "img",
                    "storage_type": "resource",
                    "callback_action": "resource_edit",
                    "callback_context": {"resource_id": resource_id},
                    "target_path": f"{target_owner_type}/{target_owner_id}/{resource_id}.webp",
                },
                audience="storage",
                ttl_seconds=ttl_seconds,
            )
            if not token:
                await session.rollback()
                raise standarts.InternalServerError(
                    detail="JWT secret missing.",
                    instance=str(request.url),
                    code="STORAGE_UNAVAILABLE",
                )

            transfer_url, ws_url = _make_transfer_urls(job_id, token)
            job = UploadRead(
                id=job_id,
                kind=kind,
                status="created",
                transfer_url=transfer_url,
                ws_url=ws_url,
                expires_at=expires_at,
                owner_type=payload.owner_type,
                owner_id=target_owner_id,
                mode=mode,
                resource_id=resource_id,
            )
            session.add(_upload_row(job))
            await session.commit()
        return _store_job(job)

    if kind == "profile_avatar":
        if payload.owner_type != "profile" or payload.owner_id is None:
            _invalid_upload_payload(request)
        await _require_profile_avatar_access(request, payload.owner_id)

        token = tools.create_transfer_jwt(
            {
                **_transfer_payload(job_id),
                "transfer_kind": "img",
                "storage_type": "avatar",
                "callback_action": "avatar_set",
                "callback_context": {"user_id": payload.owner_id},
                "target_path": f"{payload.owner_id}.webp",
            },
            audience="storage",
            ttl_seconds=ttl_seconds,
        )
        if not token:
            raise standarts.InternalServerError(
                detail="JWT secret missing.",
                instance=str(request.url),
                code="STORAGE_UNAVAILABLE",
            )

        transfer_url, ws_url = _make_transfer_urls(job_id, token)
        job = UploadRead(
            id=job_id,
            kind=kind,
            status="created",
            transfer_url=transfer_url,
            ws_url=ws_url,
            expires_at=expires_at,
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
            mode=mode,
        )
        async with catalog.AsyncSessionLocal() as session:
            session.add(_upload_row(job))
            await session.commit()
        return _store_job(job)

    _unsupported_upload_kind(request)


@router.get(
    "/uploads/{upload_id}",
    tags=["Upload"],
    status_code=200,
    response_model=UploadRead,
    response_model_exclude_none=True,
)
async def get_upload(request: Request, upload_id: str) -> UploadRead:
    job = await _load_job(upload_id)
    if job is None:
        _raise_not_found(request, "UPLOAD_NOT_FOUND", "Upload not found.")
    return job


@router.post(
    "/internal/storage/transfer-completions",
    tags=["Upload"],
    status_code=200,
    include_in_schema=False,
)
async def storage_transfer_completion(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Response:
    token = _completion_bearer_token(authorization)
    if not token:
        raise standarts.UnauthorizedError(instance=str(request.url))

    token_data = tools.decode_transfer_jwt(token, audience="manager")
    if not token_data:
        raise standarts.ForbiddenError(
            detail="Access denied",
            instance=str(request.url),
        )

    job_id = _job_id_from_payload(request, token_data)
    if not job_id:
        _invalid_upload_payload(request)

    transfer_kind = str(token_data.get("transfer_kind") or "archive").strip().lower()
    if transfer_kind == "img":
        return await _handle_image_completion(
            request=request,
            payload=token_data,
            job_id=job_id,
        )
    return await _handle_archive_completion(
        request=request,
        payload=token_data,
        job_id=job_id,
    )
