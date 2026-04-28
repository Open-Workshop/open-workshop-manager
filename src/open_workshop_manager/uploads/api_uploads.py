"""Unified upload command routes."""

from __future__ import annotations

import datetime
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from sqlalchemy import delete

from open_workshop_manager import settings as config, standarts, tools
from open_workshop_manager.api_models import UploadCreate, UploadRead
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_JOBS: dict[str, UploadRead] = {}


def _raise_not_found(request: Request, code: str, detail: str) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
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


async def _require_owner_access(request: Request, owner_type: str, owner_id: int) -> None:
    if owner_type == "mod":
        await tools.access_mods(request=request, mods_ids=[owner_id], edit=True)
    elif owner_type == "resource":
        await tools.access_mods(request=request, mods_ids=[owner_id], edit=True)
    elif owner_type == "profile":
        access_result = await tools.access_profile(request=request, profile_id=owner_id)
        if not access_result.authenticated or not access_result.edit.avatar.value:
            raise standarts.ForbiddenError(
                detail="Access denied.",
                instance=str(request.url),
            )
    else:
        raise standarts.UnsupportedOwnerTypeError(instance=str(request.url))


@router.post(
    "/uploads",
    tags=["Upload"],
    status_code=201,
    response_model=UploadRead,
    response_model_exclude_none=True,
)
async def create_upload(request: Request, payload: UploadCreate) -> UploadRead:
    if not getattr(config, "TRANSFER_JWT_SECRET", ""):
        raise standarts.InternalServerError(
            detail="JWT secret missing.",
            instance=str(request.url),
            code="STORAGE_UNAVAILABLE",
        )

    job_id = uuid.uuid4().hex
    ttl_raw = getattr(config, "TRANSFER_JWT_TTL_SECONDS", 900)
    try:
        ttl_seconds = int(ttl_raw)
    except (TypeError, ValueError):
        ttl_seconds = 900

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=ttl_seconds)

    if payload.kind == "mod_archive":
        if payload.owner_type != "mod" or payload.owner_id is None:
            raise standarts.StandardAPIError(
                status_code=400,
                title="Bad Request",
                detail="Invalid upload payload.",
                code="INVALID_UPLOAD_PAYLOAD",
                instance=str(request.url),
            )
        await _require_owner_access(request, payload.owner_type, payload.owner_id)
        token = tools.create_transfer_jwt(
            {
                **_transfer_payload(job_id),
                "transfer_kind": "archive",
                "mod_id": payload.owner_id,
                "pack_format": payload.format or "zip",
                "pack_level": int(payload.compression_level or 3),
                "update_only": payload.mode == "replace",
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
            kind=payload.kind,
            status="created",
            transfer_url=transfer_url,
            ws_url=ws_url,
            expires_at=expires_at,
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
            mode=payload.mode,
        )
        return _store_job(job)

    if payload.kind == "resource_image":
        if payload.owner_type != "resource":
            raise standarts.StandardAPIError(
                status_code=400,
                title="Bad Request",
                detail="Invalid upload payload.",
                code="INVALID_UPLOAD_PAYLOAD",
                instance=str(request.url),
            )
        if (
            payload.resource_owner_type is None
            or payload.resource_owner_id is None
            or payload.resource_type is None
        ):
            raise standarts.StandardAPIError(
                status_code=400,
                title="Bad Request",
                detail="Invalid upload payload.",
                code="INVALID_UPLOAD_PAYLOAD",
                instance=str(request.url),
            )
        await _require_owner_access(request, payload.resource_owner_type, payload.resource_owner_id)
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
            await session.commit()

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
            async with catalog.AsyncSessionLocal() as session:
                await session.execute(delete(catalog.Resource).where(catalog.Resource.id == resource.id))
                await session.commit()
            raise standarts.InternalServerError(
                detail="JWT secret missing.",
                instance=str(request.url),
                code="STORAGE_UNAVAILABLE",
            )
        transfer_url, ws_url = _make_transfer_urls(job_id, token)
        job = UploadRead(
            id=job_id,
            kind=payload.kind,
            status="created",
            transfer_url=transfer_url,
            ws_url=ws_url,
            expires_at=expires_at,
            owner_type=payload.owner_type,
            owner_id=payload.resource_owner_id,
            mode=payload.mode,
            resource_id=resource.id,
        )
        return _store_job(job)

    if payload.kind == "profile_avatar":
        if payload.owner_type != "profile" or payload.owner_id is None:
            raise standarts.StandardAPIError(
                status_code=400,
                title="Bad Request",
                detail="Invalid upload payload.",
                code="INVALID_UPLOAD_PAYLOAD",
                instance=str(request.url),
            )
        await _require_owner_access(request, payload.owner_type, payload.owner_id)
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
            kind=payload.kind,
            status="created",
            transfer_url=transfer_url,
            ws_url=ws_url,
            expires_at=expires_at,
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
            mode=payload.mode,
        )
        return _store_job(job)

    raise standarts.StandardAPIError(
        status_code=400,
        title="Bad Request",
        detail="Unsupported upload kind.",
        code="UNSUPPORTED_UPLOAD_KIND",
        instance=str(request.url),
    )


@router.get(
    "/uploads/{upload_id}",
    tags=["Upload"],
    status_code=200,
    response_model=UploadRead,
    response_model_exclude_none=True,
)
async def get_upload(request: Request, upload_id: str) -> UploadRead:
    job = UPLOAD_JOBS.get(upload_id)
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
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    token_data = tools.decode_transfer_jwt(token, audience="storage") if token else None
    if not token_data:
        raise standarts.UnauthorizedError(instance=str(request.url))

    token_job_id = str(token_data.get("job_id") or "")
    job_id = request.query_params.get("job_id") or token_job_id
    if request.query_params.get("job_id") and token_job_id and request.query_params.get("job_id") != token_job_id:
        raise standarts.ForbiddenError(instance=str(request.url))
    job = UPLOAD_JOBS.get(job_id)
    if job is None:
        _raise_not_found(request, "UPLOAD_NOT_FOUND", "Upload not found.")

    UPLOAD_JOBS[job_id] = job.model_copy(update={"status": "completed"})
    logger.info(
        "storage transfer completion job_id=%s kind=%s owner_type=%s owner_id=%s status=%s",
        job_id,
        job.kind,
        job.owner_type,
        job.owner_id,
        "completed",
    )
    return Response(status_code=200)
