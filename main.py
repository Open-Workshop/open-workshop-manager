from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ow_config import MAIN_URL

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
    docs_url=MAIN_URL+"/docs"
)

app.config.update(
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_DOMAIN='.openworkshop.miskler.ru',
    REMEMBER_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_DOMAIN='.openworkshop.miskler.ru'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://openworkshop.miskler.ru",
        "https://api.openworkshop.miskler.ru", # сам API
    ],
    allow_credentials=True,  # КРИТИЧЕСКИ ВАЖНО для кук
    allow_methods=["*"],     # Разрешить все методы
    allow_headers=["*"],     # Разрешить все заголовки
    expose_headers=["Content-Type", "Content-Disposition"]  # Какие заголовки доступны JS
)

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
