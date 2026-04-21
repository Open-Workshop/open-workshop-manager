import logging
import time
import asyncio
import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from open_workshop_manager.settings import MAIN_URL
from open_workshop_manager import settings as config

from open_workshop_manager.games.api_game import router as game_router
from open_workshop_manager.mods.api_mod import router as mod_router
from open_workshop_manager.games.api_genre import router as genre_router
from open_workshop_manager.mods.api_tag import router as tag_router
from open_workshop_manager.mods.api_resource import router as resource_router
from open_workshop_manager.association.api_association_control import (
    router as association_control_router,
)
from open_workshop_manager.association.api_association_getter import (
    router as association_getter_router,
)
from open_workshop_manager.social.api_profile import router as profile_router
from open_workshop_manager.social.api_session import router as session_router
from open_workshop_manager.app.api_catalog_statistics import (
    router as catalog_statistics_router,
)
from starlette.types import ASGIApp, Receive, Scope, Send
from open_workshop_manager.logging_setup import setup_logging
from open_workshop_manager.telemetry import setup_uptrace_telemetry
from open_workshop_manager.sql_logic import sql_catalog as catalog
from open_workshop_manager.sql_logic import sql_account as account
from sqlalchemy.orm import sessionmaker

setup_logging()
logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 600
CLEANUP_STALE_SECONDS = 2 * 60 * 60
_cleanup_task: asyncio.Task | None = None


async def _cleanup_stale_mods_once() -> None:
    cutoff = datetime.datetime.now() - datetime.timedelta(seconds=CLEANUP_STALE_SECONDS)
    session = sessionmaker(bind=catalog.engine)()
    try:
        stale = (
            session.query(catalog.Mod.id)
            .filter(catalog.Mod.condition == 1)
            .filter(catalog.Mod.date_creation < cutoff)
            .all()
        )
        stale_ids = [row.id for row in stale]
    finally:
        session.close()

    if not stale_ids:
        return

    session = sessionmaker(bind=catalog.engine)()
    try:
        session.query(catalog.Mod).filter(catalog.Mod.id.in_(stale_ids)).delete(
            synchronize_session=False
        )
        session.query(catalog.mods_dependencies).filter(
            catalog.mods_dependencies.c.mod_id.in_(stale_ids)
        ).delete(synchronize_session=False)
        session.query(catalog.mods_tags).filter(
            catalog.mods_tags.c.mod_id.in_(stale_ids)
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()

    session = sessionmaker(bind=account.engine)()
    try:
        session.query(account.mod_and_author).filter(
            account.mod_and_author.c.mod_id.in_(stale_ids)
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()

    logger.info("Cleanup stale mods deleted count=%s", len(stale_ids))


async def _cleanup_stale_mods_loop() -> None:
    while True:
        try:
            await _cleanup_stale_mods_once()
        except Exception:
            logger.exception("Cleanup stale mods failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


class CookieDefaultsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                new_headers = []
                cookie_domain = getattr(config, "COOKIE_DOMAIN", None)
                cookie_samesite = getattr(config, "COOKIE_SAMESITE", None)
                cookie_secure = bool(getattr(config, "COOKIE_SECURE", False))
                for name, value in headers:
                    if name.lower() == b"set-cookie":
                        cookie_str = value.decode("latin-1")
                        # Add Domain if not present
                        if cookie_domain and "Domain=" not in cookie_str:
                            cookie_str += f"; Domain={cookie_domain}"
                        # Optionally add SameSite if not present (though Starlette defaults to Lax)
                        if cookie_samesite and "SameSite=" not in cookie_str:
                            cookie_str += f"; SameSite={cookie_samesite}"
                        if cookie_secure and "Secure" not in cookie_str:
                            cookie_str += "; Secure"
                        value = cookie_str.encode("latin-1")
                    new_headers.append((name, value))
                message["headers"] = new_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(
    title="OpenWorkshop.Manager",
    openapi_url=MAIN_URL + "/openapi.json",
    contact={
        "name": "Contacts",
        "url": "https://github.com/Open-Workshop/open-workshop-manager",
        "email": "miskler@yandex.ru",
    },
    license_info={
        "name": "MPL-2.0 license",
        "identifier": "MPL-2.0",
    },
    description="""
    OpenWorkshop.Manager - это оркестратор "сервисного монолита" OpenWorkshop. Через него выполняются все операции чтения/записи каталога.

    Оркестратор имеет зависимые микросервисы: MySQL *(заблокирован для использования вне оркестратора)*, Storage *(файловый сервер к которому можно обращаться напрямую)*.
    """,
    redoc_url=MAIN_URL + "/",
    docs_url=MAIN_URL + "/docs",
)
#setup_uptrace_telemetry(app)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.exception(
            "HTTP %s %s -> 500 (%.2fms)",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000
    client = request.client.host if request.client else "-"
    logger.info(
        "HTTP %s %s -> %s (%.2fms) client=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        client,
    )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        lambda: list(
            dict.fromkeys(
                list(
                    getattr(
                        config,
                        "CORS_ORIGINS",
                        [
                            "https://openworkshop.miskler.ru",
                            "https://api.openworkshop.miskler.ru",
                        ],
                    )
                )
                + (
                    list(
                        getattr(
                            config,
                            "LOCALHOST_CORS_ORIGINS",
                            [
                                "http://localhost:3000",
                                "http://127.0.0.1:3000",
                                "http://localhost:5173",
                                "http://127.0.0.1:5173",
                                "http://localhost:8080",
                                "http://127.0.0.1:8080",
                            ],
                        )
                    )
                    if bool(getattr(config, "ALLOW_LOCALHOST_CORS", False))
                    else []
                )
            )
        )
    )(),
    allow_credentials=True,  # КРИТИЧЕСКИ ВАЖНО для кук
    allow_methods=["*"],  # Разрешить все методы
    allow_headers=["*"],  # Разрешить все заголовки
    expose_headers=[
        "Content-Type",
        "Content-Disposition",
        "Location",
        "X-Upload-Job",
        "X-Progress-WS",
    ],  # Какие заголовки доступны JS
)
app.add_middleware(CookieDefaultsMiddleware)


@app.on_event("startup")
async def _start_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = asyncio.create_task(_cleanup_stale_mods_loop())


@app.on_event("shutdown")
async def _stop_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None

app.include_router(game_router)
app.include_router(mod_router)
app.include_router(genre_router)
app.include_router(tag_router)
app.include_router(resource_router)
app.include_router(association_control_router)
app.include_router(association_getter_router)
app.include_router(profile_router)
app.include_router(session_router)
app.include_router(catalog_statistics_router)

setup_uptrace_telemetry(app)
