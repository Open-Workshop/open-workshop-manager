from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ow_config import MAIN_URL
import ow_config as config

from games.api_game import router as game_router
from mods.api_mod import router as mod_router
from games.api_genre import router as genre_router
from mods.api_tag import router as tag_router
from mods.api_resource import router as resource_router
from association.api_association_control import router as association_control_router
from association.api_association_getter import router as association_getter_router
from social.api_profile import router as profile_router
from social.api_session import router as session_router
from social.api_reaction import router as reaction_router
from social.api_black_list import router as black_list_router
from social.api_forum import router as forum_router
from social.api_forum_comment import router as forum_comment_router
from starlette.types import ASGIApp, Receive, Scope, Send

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
    openapi_url=MAIN_URL+"/openapi.json",
    contact={
        "name": "Contacts",
        "url": "https://github.com/Open-Workshop/open-workshop-manager",
        "email": "miskler@yandex.ru"
    },
    license_info={
        "name": "MPL-2.0 license",
        "identifier": "MPL-2.0",
    },
    description="""
    OpenWorkshop.Manager - это оркестратор "сервисного монолита" OpenWorkshop. Через него выполняются все операции чтения/записи каталога.

    Оркестратор имеет зависимые микросервисы: MySQL *(заблокирован для использования вне оркестратора)*, Storage *(файловый сервер к которому можно обращаться напрямую)*.
    """,
    redoc_url=MAIN_URL+"/",
    docs_url=MAIN_URL+"/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        lambda: list(
            dict.fromkeys(
                list(
                    getattr(
                        config,
                        "CORS_ORIGINS",
                        ["https://openworkshop.miskler.ru", "https://api.openworkshop.miskler.ru"],
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
    allow_methods=["*"],     # Разрешить все методы
    allow_headers=["*"],     # Разрешить все заголовки
    expose_headers=["Content-Type", "Content-Disposition"]  # Какие заголовки доступны JS
)
app.add_middleware(CookieDefaultsMiddleware)

app.include_router(game_router)
app.include_router(mod_router)
app.include_router(genre_router)
app.include_router(tag_router)
app.include_router(resource_router)
app.include_router(association_control_router)
app.include_router(association_getter_router)
app.include_router(profile_router)
app.include_router(session_router)
app.include_router(reaction_router)
app.include_router(black_list_router)
app.include_router(forum_router)
app.include_router(forum_comment_router)
