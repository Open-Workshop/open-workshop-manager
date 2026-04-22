import datetime
import json
import logging
from io import BytesIO
from typing import Literal, Sequence, overload

import aiohttp
import bcrypt
import jwt
from fastapi import HTTPException, Request
from sqlalchemy import delete, desc, select

from open_workshop_manager import access_client
from open_workshop_manager import settings as config
from open_workshop_manager import standarts
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

logger = logging.getLogger(__name__)

TRANSFER_JWT_ALG = "HS256"


async def check_token(token_name: str, token: str) -> bool:
    """
    Check if the provided token matches the stored token hash for the given token name.

    Args:
        token_name (str): The name of the token to check.
        token (str): The token to compare with the stored token hash.

    Returns:
        bool: True if the provided token matches the stored token hash, False otherwise.
    """
    # Получаем значение хеша токена из config по имени token_name
    stored_token_hash = getattr(config, token_name, None)

    if stored_token_hash is None:
        logger.warning("Токен `%s` не найден в config!", token_name)
        return False

    stored_token = str(stored_token_hash)
    if not stored_token:
        return False

    if stored_token.startswith("$2"):
        try:
            return bcrypt.checkpw(token.encode(), stored_token.encode())
        except ValueError:
            return False

    return token == stored_token


def create_transfer_jwt(
    payload: dict,
    audience: str,
    ttl_seconds: int,
    issuer: str = "manager",
) -> str | None:
    secret = getattr(config, "TRANSFER_JWT_SECRET", None)
    if not secret:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = dict(payload)
    claims.update(
        {
            "aud": audience,
            "iss": issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + datetime.timedelta(seconds=ttl_seconds)).timestamp()),
        }
    )
    return jwt.encode(claims, secret, algorithm=TRANSFER_JWT_ALG)


def decode_transfer_jwt(token: str, audience: str) -> dict | None:
    secret = getattr(config, "TRANSFER_JWT_SECRET", None)
    if not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=[TRANSFER_JWT_ALG], audience=audience)
    except jwt.PyJWTError:
        return None


def _normalize_mod_ids(mods_ids: list[int] | int) -> list[int]:
    if isinstance(mods_ids, int):
        return [mods_ids]
    return [int(mod_id) for mod_id in mods_ids]


def _raise_access_service_error(
    instance: str,
    exc: Exception,
) -> None:
    problem = getattr(exc, "problem", None)
    if problem is not None:
        raise HTTPException(
            status_code=problem.status,
            detail=problem.model_dump(mode="json", exclude_none=True),
        ) from exc

    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 504}:
        raise standarts.GatewayTimeoutError(
            detail="Access service timeout",
            instance=instance,
        ) from exc
    if status_code is not None:
        detail = getattr(exc, "response_text", None) or "Access service rejected request"
        raise HTTPException(status_code=status_code, detail=detail) from exc
    raise standarts.InternalServerError(
        detail="Access service unavailable",
        instance=instance,
    ) from exc


def _mod_status_allowed(status: access_client.ModResponse, *, edit: bool) -> bool:
    if edit:
        return bool(status.edit.title.value)
    return bool(status.download.value)


def _allowed_mod_ids(
    access_result: dict[int, access_client.ModResponse],
    normalized_mod_ids: list[int],
    *,
    edit: bool,
) -> list[int]:
    allowed_ids: list[int] = []
    for mod_id in normalized_mod_ids:
        status = access_result.get(mod_id)
        if status is None:
            continue
        if _mod_status_allowed(status, edit=edit):
            allowed_ids.append(mod_id)
    return allowed_ids


async def access_admin(request: Request) -> bool:
    """
    Asynchronously checks if the user has admin access.

    Args:
        request (Request): The request object.

    Returns:
        bool: True when the current session belongs to an admin user.

    Raises:
        standarts.UnauthorizedError: If the session is invalid.
        standarts.AdminRequiredError: If the session is valid but the user is not an admin.
    """
    access_result = await account.check_access(request=request)
    if not access_result or access_result.get("owner_id", -1) < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    if access_result.admin:
        return True

    raise standarts.AdminRequiredError(instance=str(request.url))


def str_to_list(string: str | list) -> list:
    """
    Convert a string representation of a list to an actual list.

    Parameters:
        string (str): The string representation of the list.

    Returns:
        list: The converted list. If the conversion fails, an empty list is returned.
    """
    if isinstance(string, list):
        return string
    try:
        parsed = json.loads(string)
    except (TypeError, json.JSONDecodeError):
        return []

    return parsed if isinstance(parsed, list) else []


async def resources_serialize(
    resources: Sequence[catalog.Resource], only_urls: bool = False
) -> list[dict] | list[str]:
    """
    Serializes a list of `catalog.Resource` objects into a list of dictionaries or a list of strings.

    Args:
        resources (list[catalog.Resource]): A list of `catalog.Resource` objects to be serialized.
        only_urls (bool, optional): If set to `True`, only the `real_url` attribute of each resource will be included in the serialized list. Defaults to `False`.

    Returns:
        list[dict] | list[str]: A list of dictionaries containing the serialized resource information, or a list of strings if `only_urls` is `True`.
    """
    if only_urls:
        real_urls: list[str] = []
        for resource in resources:
            real_urls.append(resource.real_url)
        return real_urls

    real_resources: list[dict[str, object]] = []
    for resource in resources:
        real_resources.append(
            {
                "id": resource.id,
                "type": resource.type,
                "url": resource.real_url,
                "size": resource.size,
                "owner_id": resource.owner_id,
                "owner_type": resource.owner_type,
                "date_event": resource.date_event,
            }
        )
    return real_resources


@overload
async def anonymous_access_mods(
    user_id: int,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[True],
) -> list[int]: ...


@overload
async def anonymous_access_mods(
    user_id: int,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[False] = False,
) -> bool: ...


async def anonymous_access_mods(
    user_id: int,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: bool = False,
) -> bool | list[int]:
    """
    Asynchronously checks if the given user has access to modify the specified mods.

    Parameters:
        user_id (int): The ID of the user.
        mods_ids (list[int]): A list of mod IDs.
        edit (bool, optional): Whether the user is allowed to edit the mods. Defaults to False.
        check_mode (bool, optional): Whether to return a list of mod IDs that the user has access to. Defaults to False.

    Returns:
        bool or list[int]: If check_mode is True, returns a list of mod IDs that the user has access to. Otherwise, returns True if the user has access, False otherwise.
    """
    normalized_mod_ids = _normalize_mod_ids(mods_ids)

    try:
        access_result = await access_client.resolve_mods(
            mods_ids=normalized_mod_ids,
        )
    except access_client.AccessServiceError as exc:
        _raise_access_service_error("anonymous_access_mods", exc)

    allowed_ids = _allowed_mod_ids(access_result, normalized_mod_ids, edit=edit)

    if check_mode:
        return allowed_ids

    return len(allowed_ids) == len(normalized_mod_ids)


@overload
async def access_mods(
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[True],
) -> list[int]: ...


@overload
async def access_mods(
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[False] = False,
) -> bool: ...


async def access_mods(
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: bool = False,
) -> bool | list[int]:
    """
    Asynchronously checks the access permissions for a set of mods.

    Args:
        request (Request): The request object.
        mods_ids (list[int]): The list of mod IDs to check access for.
        edit (bool, optional): Whether to check for edit access. Defaults to False (read access).
        check_mode (bool, optional): Whether to check in check mode. Defaults to False.

    Returns:
        If check_mode is True:
            - Returns a list of mod IDs that the user has access to.
            - Denied or unauthenticated access is represented by an empty list.
        If check_mode is False:
            - If access is granted: Returns True.
            - If access is denied: Raises `standarts.ForbiddenError`.
            - If the session key is invalid: Raises `standarts.UnauthorizedError`.
    """
    normalized_mod_ids = _normalize_mod_ids(mods_ids)

    if edit:
        access_context = await account.check_access(request=request)
        if (
            not access_context
            or not access_context.authenticated
            or access_context.owner_id < 0
        ):
            raise standarts.UnauthorizedError(instance=str(request.url))

    try:
        access_result = await access_client.resolve_mods(
            request=request,
            mods_ids=normalized_mod_ids,
        )
    except access_client.AccessServiceError as exc:
        _raise_access_service_error(str(request.url), exc)

    allowed_ids = _allowed_mod_ids(access_result, normalized_mod_ids, edit=edit)

    if check_mode:
        return allowed_ids

    if len(allowed_ids) == len(normalized_mod_ids):
        return True

    raise standarts.ForbiddenError(instance=str(request.url))


async def access_mod_add(
    request: Request,
) -> access_client.ModAddResponse:
    try:
        return await access_client.resolve_mod_add(
            request=request,
        )
    except access_client.AccessServiceError as exc:
        _raise_access_service_error(str(request.url), exc)


async def access_profile(
    request: Request,
    profile_id: int,
) -> access_client.ProfileResponse:
    try:
        return await access_client.resolve_profile(
            request=request,
            profile_id=profile_id,
        )
    except access_client.AccessServiceError as exc:
        _raise_access_service_error(str(request.url), exc)


async def access_mod_action(
    request: Request,
    mod_id: int,
    *,
    author_id: int | None = None,
    mode: bool | None = None,
) -> access_client.ModResponse:
    try:
        return await access_client.resolve_mod(
            request=request,
            mod_id=mod_id,
            author_id=author_id,
            mode=mode,
        )
    except access_client.AccessServiceError as exc:
        _raise_access_service_error(str(request.url), exc)


async def check_game_exists(game_id: int) -> bool:
    """
    Asynchronously checks if a game with the given ID exists in the catalog.

    Parameters:
        game_id (int): The ID of the game to check.

    Returns:
        bool: True if a game with the given ID exists, False otherwise.
    """
    async with catalog.AsyncSessionLocal() as session:
        result = await session.get(catalog.Game, game_id)
        return bool(result)


async def storage_file_upload(
    type: str, path: str, file: BytesIO, file_kind: str = "bin"
) -> tuple[int, str, bool]:
    """
    Uploads a file to the storage service.

    Args:
        type (str): The type of the file.
        path (str): Path of the file to be uploaded.
        file (BytesIO): The file content to be uploaded.

    Returns:
        bool | str: False if the file upload failed.
                    If the file was uploaded successfully, the response body is returned as a path to the uploaded file.
    """

    real_url = f"{config.STORAGE_URL}/upload"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            real_url,
            data={
                "file": file,
                "type": type,
                "path": path,
                "file_kind": file_kind,
                "token": config.storage_upload_token,
            },
        ) as resp:
            return resp.status, str(await resp.text()), resp.status == 201


async def storage_file_delete(type: str, path: str) -> bool:
    """
    Deletes a file from the storage.

    Args:
        type (str): The type of the file.
        path (str): Path to the file to be deleted.

    Returns:
        bool: True if the file was successfully deleted, False otherwise.
    """

    real_url = f"{config.STORAGE_URL}/delete"

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            real_url,
            data={
                "type": type,
                "path": path,
                "token": config.storage_delete_token,
            },
        ) as resp:
            if resp.status in [404, 200]:
                logger.info(
                    "Storage delete result type=%s path=%s status=%s",
                    type,
                    path,
                    resp.status,
                )
                return True

            body = await resp.text()
            logger.warning(
                "Storage delete failed type=%s path=%s status=%s body=%s",
                type,
                path,
                resp.status,
                body,
            )
            return False


async def storage_job_repack(
    job_id: str, pack_format: str = "zip", pack_level: int = 3
) -> tuple[int, dict | str, bool]:
    real_url = f"{config.STORAGE_URL}/transfer/repack"
    timeout_raw = getattr(config, "STORAGE_TIMEOUT_SECONDS", 1800)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_seconds = 1800
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            real_url,
            data={
                "job_id": job_id,
                "format": pack_format,
                "compression_level": pack_level,
                "token": config.storage_manage_token,
            },
        ) as resp:
            body = await resp.text()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = body
            return resp.status, payload, resp.status == 200


async def storage_job_move(
    job_id: str, type: str, path: str
) -> tuple[int, dict | str, bool]:
    real_url = f"{config.STORAGE_URL}/transfer/move"
    timeout_raw = getattr(config, "STORAGE_TIMEOUT_SECONDS", 1800)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_seconds = 1800
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            real_url,
            data={
                "job_id": job_id,
                "type": type,
                "path": path,
                "token": config.storage_manage_token,
            },
        ) as resp:
            body = await resp.text()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = body
            return resp.status, payload, resp.status == 200


async def delete_resources(
    owner_type: str, resources_ids: list[int] | None = None, owner_id: int = -1
) -> bool:
    """
    Deletes resources based on the owner type and resource IDs or owner ID.
    If resources_ids is not empty, the resources with the specified IDs will be deleted. If owner_id is not -1, the resources of the specified owner will be deleted.
    If both resources_ids and owner_id are empty, return False (call error).

    Args:
        owner_type (str): The type of the owner.
        resources_ids (list[int], optional): A list of resource IDs to delete. Defaults to an empty list.
        owner_id (int, optional): The ID of the owner. Defaults to -1.

    Returns:
        bool: True if the resources are successfully deleted, False otherwise.
    """
    # Нужно обязательно передать либо resources_ids либо owner_id (сами фильтры не противоречат друг другу, но не рекомендую использовать одновременно).
    # Если resources_ids будут удаляться конкретные ресурсы, а если owner_id, то ресурсы овнера (если без переданного списка, то все).

    if resources_ids is None:
        resources_ids = []

    if len(resources_ids) <= 0 and owner_id <= 0:
        return False

    logger.debug(
        "Delete resources start owner_type=%s owner_id=%s ids_count=%s",
        owner_type,
        owner_id,
        len(resources_ids),
    )
    async with catalog.AsyncSessionLocal() as session:
        query = select(catalog.Resource).where(catalog.Resource.owner_type == owner_type)

        if owner_id > 0:
            query = query.where(catalog.Resource.owner_id == owner_id)
        if len(resources_ids) > 0:
            query = query.where(catalog.Resource.id.in_(resources_ids))

        resources = {
            resource.id: resource.url
            for resource in (await session.execute(query)).scalars().all()
        }

    logger.debug("Delete resources found=%s", len(resources))
    deleted = []
    for resource in resources.keys():
        url = resources[resource]
        if url.startswith("local/"):
            delete_result = await storage_file_delete(
                type="resource", path=url.replace("local/", "")
            )

            if delete_result:
                deleted.append(resource)
            else:
                logger.warning(
                    "Delete Resources: Error: resource not deleted (%s)", resource
                )
        else:
            deleted.append(resource)

    if len(deleted) > 0:
        async with catalog.AsyncSessionLocal() as session:
            await session.execute(
                delete(catalog.Resource).where(catalog.Resource.id.in_(deleted))
            )
            await session.commit()
    else:
        logger.info("Delete Resources: No resources deleted")

    failed_count = len(resources) - len(deleted)
    logger.info(
        "Delete Resources: done total=%s deleted=%s failed=%s",
        len(resources),
        len(deleted),
        failed_count,
    )
    return True


def sort_mods(sort_by: str):
    match sort_by:
        case "NAME":
            return catalog.Mod.name
        case "iNAME":
            return desc(catalog.Mod.name)
        case "SIZE":
            return catalog.Mod.size
        case "iSIZE":
            return desc(catalog.Mod.size)
        case "CREATION_DATE":
            return catalog.Mod.date_creation
        case "iCREATION_DATE":
            return desc(catalog.Mod.date_creation)
        case "UPDATE_DATE":
            return catalog.Mod.date_update_file
        case "iUPDATE_DATE":
            return desc(catalog.Mod.date_update_file)
        case "EDIT_DATE":
            return catalog.Mod.date_edit
        case "iEDIT_DATE":
            return desc(catalog.Mod.date_edit)
        case "SOURCE":
            return catalog.Mod.source
        case "iSOURCE":
            return desc(catalog.Mod.source)
        case "DOWNLOADS":
            return desc(catalog.Mod.downloads)
        case _:
            return catalog.Mod.downloads  # По умолчанию сортируем по загрузкам


def sort_games(sort_by: str):
    match sort_by:
        case "NAME":
            return catalog.Game.name
        case "iNAME":
            return desc(catalog.Game.name)
        case "TYPE":
            return catalog.Game.type
        case "iTYPE":
            return desc(catalog.Game.type)
        case "CREATION_DATE":
            return catalog.Game.creation_date
        case "iCREATION_DATE":
            return desc(catalog.Game.creation_date)
        case "SOURCE":
            return catalog.Game.source
        case "iSOURCE":
            return desc(catalog.Game.source)
        case "MODS_COUNT":
            return catalog.Game.mods_count
        case "iMODS_COUNT":
            return desc(catalog.Game.mods_count)
        case "DOWNLOADS":
            return desc(catalog.Game.mods_downloads)
        case _:
            return catalog.Game.mods_downloads
