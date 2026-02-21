from fastapi import APIRouter
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from ow_config import MAIN_URL
from sql_logic import sql_account as account
from sql_logic import sql_catalog as catalog

router = APIRouter()


@router.get(
    MAIN_URL + "/catalog/statistics",
    tags=["Catalog Statistics"],
    summary="Anonymous aggregated catalog statistics",
    status_code=200,
)
async def get_catalog_statistics():
    catalog_session = sessionmaker(bind=catalog.engine)()
    account_session = sessionmaker(bind=account.engine)()
    try:
        mods_count = (
            catalog_session.query(func.count(catalog.Mod.id))
            .filter(catalog.Mod.condition == 0)
            .scalar()
            or 0
        )

        mods_size = (
            catalog_session.query(func.coalesce(func.sum(catalog.Mod.size), 0))
            .filter(catalog.Mod.condition == 0)
            .scalar()
            or 0
        )

        mods_size_unpacked = (
            catalog_session.query(
                func.coalesce(
                    func.sum(
                        func.coalesce(catalog.Mod.size_unpacked, catalog.Mod.size, 0)
                    ),
                    0,
                )
            )
            .filter(catalog.Mod.condition == 0)
            .scalar()
            or 0
        )

        resources_size = (
            catalog_session.query(func.coalesce(func.sum(catalog.Resource.size), 0))
            .scalar()
            or 0
        )

        users_count = (
            account_session.query(func.count(account.Account.id)).scalar() or 0
        )
    finally:
        catalog_session.close()
        account_session.close()

    return {
        "mods_count": int(mods_count),
        "users_count": int(users_count),
        "database_size_bytes": int(mods_size),
        "database_size_unpacked_bytes": int(mods_size_unpacked),
        "resources_size_bytes": int(resources_size),
    }
