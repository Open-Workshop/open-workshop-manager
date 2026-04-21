import datetime
import json
import logging
from io import BytesIO
from typing import Literal, Sequence, overload

import aiohttp
import bcrypt
import jwt
from fastapi import Request, Response
from sqlalchemy import delete, desc, select

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

    # Хеш из config должен быть строкой, конвертируем в байты
    stored_token_hash = stored_token_hash.encode()

    # Хешируем переданный токен с использованием bcrypt и проверяем соответствие
    return bcrypt.checkpw(token.encode(), stored_token_hash)


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


async def access_admin(response: Response, request: Request) -> bool:
    """
    Asynchronously checks if the user has admin access.

    Args:
        response (Response): The response object.
        request (Request): The request object.

    Returns:
        bool: True when the current session belongs to an admin user.

    Raises:
        standarts.UnauthorizedError: If the session is invalid.
        standarts.AdminRequiredError: If the session is valid but the user is not an admin.
    """
    access_result = await account.check_access(request=request, response=response)
    if not access_result or access_result.get("owner_id", -1) < 0:
        raise standarts.UnauthorizedError(instance=str(request.url))

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Account).where(
                account.Account.id == access_result.get("owner_id", -1)
            )
        )
        row_result = result.scalar_one_or_none()
        if row_result and row_result.admin:
            return True
        if row_result is None:
            raise standarts.UnauthorizedError(instance=str(request.url))
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
    if isinstance(mods_ids, int):
        mods_ids = [mods_ids]

    async with account.AsyncSessionLocal() as session:
        result = await session.execute(
            select(account.Account).where(account.Account.id == user_id)
        )
        user_req = result.scalar_one_or_none()
        if user_req is None:
            if edit:
                return [] if check_mode else False
            async with catalog.AsyncSessionLocal() as session_catalog:
                result_mods = await session_catalog.execute(
                    select(catalog.Mod.id).where(
                        catalog.Mod.id.in_(mods_ids), catalog.Mod.public <= 1
                    )
                )
                public_mod_ids: list[int] = list(result_mods.scalars().all())
                if check_mode:
                    return public_mod_ids
                return len(mods_ids) == len(public_mod_ids)

        async def mini() -> list[int]:
            if user_req.admin:
                return mods_ids
            if edit and (
                user_req.mute_until and user_req.mute_until > datetime.datetime.now()
            ):
                return []

            result_links = await session.execute(
                select(account.mod_and_author.c.mod_id, account.mod_and_author.c.owner).where(
                    account.mod_and_author.c.user_id == user_id,
                    account.mod_and_author.c.mod_id.in_(mods_ids),
                )
            )
            mods_to_user = {row.mod_id: row.owner for row in result_links.all()}

            async with catalog.AsyncSessionLocal() as session_catalog:
                result_mods = await session_catalog.execute(
                    select(catalog.Mod.id, catalog.Mod.public).where(
                        catalog.Mod.id.in_(mods_ids)
                    )
                )
                mods = result_mods.all()

            output_check: list[int] = []
            if len(mods) == 0:
                return output_check

            for mod in mods:
                if mod.id in mods_to_user:
                    if edit and (
                        not user_req.change_self_mods or not mods_to_user.get(mod.id, False)
                    ):
                        continue
                elif mod.public > 1 or (edit and not user_req.change_mods):
                    continue

                output_check.append(mod.id)
            return output_check

        if user_id > 0 and user_req:
            mini_result = await mini()
            return mini_result if check_mode else len(mini_result) == len(mods_ids)

        if edit:
            return [] if check_mode else False

        async with catalog.AsyncSessionLocal() as session_catalog:
            result_mods = await session_catalog.execute(
                select(catalog.Mod.id).where(
                    catalog.Mod.id.in_(mods_ids), catalog.Mod.public <= 1
                )
            )
            allowed_public_mod_ids: list[int] = list(result_mods.scalars().all())
            if check_mode:
                if len(allowed_public_mod_ids) == 0:
                    return []
                return allowed_public_mod_ids
            return len(mods_ids) == len(allowed_public_mod_ids)


@overload
async def access_mods(
    response: Response,
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[True],
) -> list[int]: ...


@overload
async def access_mods(
    response: Response,
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: Literal[False] = False,
) -> bool: ...


async def access_mods(
    response: Response,
    request: Request,
    mods_ids: list[int] | int,
    edit: bool = False,
    *,
    check_mode: bool = False,
) -> bool | list[int]:
    """
    Asynchronously checks the access permissions for a set of mods.

    Args:
        response (Response): The response object.
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
    if isinstance(mods_ids, int):
        mods_ids = [mods_ids]

    access_result = await account.check_access(request=request, response=response)
    uid = access_result.get("owner_id", -1) if access_result else -1

    if not edit or (access_result and uid >= 0):
        if check_mode:
            allowed_mod_ids = await anonymous_access_mods(
                user_id=uid, mods_ids=mods_ids, edit=edit, check_mode=True
            )
            return allowed_mod_ids

        has_access = await anonymous_access_mods(
            user_id=uid, mods_ids=mods_ids, edit=edit, check_mode=False
        )

        if has_access:
            return True

        raise standarts.ForbiddenError(instance=str(request.url))

    if check_mode:
        return []

    raise standarts.UnauthorizedError(instance=str(request.url))


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
