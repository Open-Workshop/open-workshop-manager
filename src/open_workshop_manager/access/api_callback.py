from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Cookie, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from open_workshop_manager import standarts, tools
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


class AccessModEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    mod_id: int
    public: int = 0
    condition: int = 0
    owner: bool = False
    member: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class AccessCallbackRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    mods_ids: list[int] = Field(default_factory=list)


class AccessCallbackContext(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    authenticated: bool = False
    owner_id: int = -1
    login_method: str | None = None

    admin: bool = False
    write_comments: bool = False
    set_reactions: bool = False
    create_reactions: bool = False
    mute_until: datetime.datetime | None = None
    mute_users: bool = False

    publish_mods: bool = False
    change_authorship_mods: bool = False
    change_self_mods: bool = False
    change_mods: bool = False
    delete_self_mods: bool = False
    delete_mods: bool = False

    create_forums: bool = False
    change_authorship_forums: bool = False
    change_self_forums: bool = False
    change_forums: bool = False
    delete_self_forums: bool = False
    delete_forums: bool = False

    change_username: bool = False
    change_about: bool = False
    change_avatar: bool = False
    vote_for_reputation: bool = False

    last_username_reset: datetime.datetime | None = None
    last_password_reset: datetime.datetime | None = None
    password_change_available_at: datetime.datetime | None = None
    username_change_available_at: datetime.datetime | None = None

    mods: list[AccessModEntry] | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def _bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _context_from_account(
    row: account.Account | None,
    *,
    authenticated: bool,
    login_method: str | None = None,
) -> AccessCallbackContext:
    if row is None:
        return AccessCallbackContext(
            authenticated=authenticated,
            owner_id=-1,
            login_method=login_method,
        )

    password_change_available_at = (
        row.last_password_reset + datetime.timedelta(minutes=5)
        if row.last_password_reset
        else None
    )
    username_change_available_at = (
        row.last_username_reset + datetime.timedelta(days=30)
        if row.last_username_reset
        else None
    )
    return AccessCallbackContext(
        authenticated=authenticated,
        owner_id=row.id,
        login_method=login_method,
        admin=bool(row.admin),
        write_comments=bool(row.write_comments),
        set_reactions=bool(row.set_reactions),
        create_reactions=bool(row.create_reactions),
        mute_until=row.mute_until,
        mute_users=bool(row.mute_users),
        publish_mods=bool(row.publish_mods),
        change_authorship_mods=bool(row.change_authorship_mods),
        change_self_mods=bool(row.change_self_mods),
        change_mods=bool(row.change_mods),
        delete_self_mods=bool(row.delete_self_mods),
        delete_mods=bool(row.delete_mods),
        create_forums=bool(row.create_forums),
        change_authorship_forums=bool(row.change_authorship_forums),
        change_self_forums=bool(row.change_self_forums),
        change_forums=bool(row.change_forums),
        delete_self_forums=bool(row.delete_self_forums),
        delete_forums=bool(row.delete_forums),
        change_username=bool(row.change_username),
        change_about=bool(row.change_about),
        change_avatar=bool(row.change_avatar),
        vote_for_reputation=bool(row.vote_for_reputation),
        last_username_reset=row.last_username_reset,
        last_password_reset=row.last_password_reset,
        password_change_available_at=password_change_available_at,
        username_change_available_at=username_change_available_at,
    )


async def _load_mods(
    owner_id: int,
    mod_ids: list[int],
) -> list[AccessModEntry]:
    if not mod_ids:
        return []

    unique_ids = list(dict.fromkeys(int(mod_id) for mod_id in mod_ids if int(mod_id) > 0))
    if not unique_ids:
        return []

    async with catalog.AsyncSessionLocal() as catalog_session:
        result = await catalog_session.execute(
            select(catalog.Mod.id, catalog.Mod.public, catalog.Mod.condition).where(
                catalog.Mod.id.in_(unique_ids)
            )
        )
        mod_rows = {int(row.id): row for row in result.all()}

    relation_map: dict[int, bool] = {}
    if owner_id > 0:
        async with account.AsyncSessionLocal() as account_session:
            result = await account_session.execute(
                select(
                    account.mod_and_author.c.mod_id,
                    account.mod_and_author.c.owner,
                ).where(
                    account.mod_and_author.c.user_id == owner_id,
                    account.mod_and_author.c.mod_id.in_(unique_ids),
                )
            )
            relation_map = {
                int(row.mod_id): bool(row.owner)
                for row in result.all()
            }

    output: list[AccessModEntry] = []
    for mod_id in unique_ids:
        row = mod_rows.get(mod_id)
        if row is None:
            continue
        relation = relation_map.get(mod_id)
        output.append(
            AccessModEntry(
                mod_id=mod_id,
                public=int(getattr(row, "public", 0) or 0),
                condition=int(getattr(row, "condition", 0) or 0),
                owner=bool(relation is True),
                member=bool(relation is False),
            )
        )
    return output


@router.post(
    MAIN_URL + "/access/callback/context",
    tags=["Access"],
    summary="Trusted static access context",
    response_model=AccessCallbackContext,
    response_model_exclude_none=True,
)
async def callback_context(
    request: Request,
    payload: AccessCallbackRequest | None = None,
    access_token: str | None = Cookie(None, alias="accessToken"),
    refresh_token: str | None = Cookie(None, alias="refreshToken"),
    authorization: str = Header("", alias="Authorization"),
):
    if not await tools.check_token(
        "ACCESS_CALLBACK_TOKEN", _bearer_token(authorization)
    ):
        raise standarts.ForbiddenError(instance=str(request.url))

    session_context = AccessCallbackContext(authenticated=False)
    session_owner_id = -1

    async with account.AsyncSessionLocal() as session:
        session_row = None
        account_row = None
        if access_token and refresh_token:
            result = await session.execute(
                select(account.Session).where(
                    account.Session.access_token == access_token,
                    account.Session.refresh_token == refresh_token,
                    account.Session.broken.is_(None),
                )
            )
            session_row = result.scalar_one_or_none()
            if session_row is not None and session_row.owner_id is not None:
                account_row = await session.get(account.Account, session_row.owner_id)
                if account_row is not None:
                    session_owner_id = account_row.id
                    session_context = _context_from_account(
                        account_row,
                        authenticated=True,
                        login_method=session_row.login_method,
                    )
                    session_row.last_request_date = datetime.datetime.now()
                    await session.commit()

    if account_row is None and session_owner_id < 0:
        session_context = AccessCallbackContext(authenticated=False, owner_id=-1)

    mods_ids = list(payload.mods_ids) if payload is not None else []
    session_context.mods = await _load_mods(session_owner_id, mods_ids) if mods_ids else None
    return session_context
