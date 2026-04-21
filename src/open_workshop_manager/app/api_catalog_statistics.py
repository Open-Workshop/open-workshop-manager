from fastapi import APIRouter
from sqlalchemy import func
from sqlalchemy import select

from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


@router.get(
    MAIN_URL + "/catalog/statistics",
    tags=["Catalog Statistics"],
    summary="Anonymous aggregated catalog statistics",
    status_code=200,
)
async def get_catalog_statistics():
    async with catalog.AsyncSessionLocal() as catalog_session:
        mods_count = (
            await catalog_session.scalar(
                select(func.count(catalog.Mod.id)).where(catalog.Mod.condition == 0)
            )
            or 0
        )

        mods_size = (
            await catalog_session.scalar(
                select(func.coalesce(func.sum(catalog.Mod.size), 0)).where(
                    catalog.Mod.condition == 0
                )
            )
            or 0
        )

        mods_size_unpacked = (
            await catalog_session.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            func.coalesce(catalog.Mod.size_unpacked, catalog.Mod.size, 0)
                        ),
                        0,
                    )
                ).where(catalog.Mod.condition == 0)
            )
            or 0
        )

        resources_size = (
            await catalog_session.scalar(select(func.coalesce(func.sum(catalog.Resource.size), 0)))
            or 0
        )

    async with account.AsyncSessionLocal() as account_session:
        users_count = await account_session.scalar(
            select(func.count(account.Account.id))
        )
        users_count = users_count or 0

    return {
        "mods_count": int(mods_count),
        "users_count": int(users_count),
        "database_size_bytes": int(mods_size),
        "database_size_unpacked_bytes": int(mods_size_unpacked),
        "resources_size_bytes": int(resources_size),
    }
