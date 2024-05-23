from fastapi import FastAPI

from ow_config import MAIN_URL

from api_game import router as game_router
from api_mod import router as mod_router
from api_genre import router as genre_router
from api_tag import router as tag_router
from api_resource import router as resource_router
from api_association import router as association_router
from api_profile import router as profile_router
from api_session import router as session_router
from api_reaction import router as reaction_router
from api_black_list import router as black_list_router
from api_forum import router as forum_router
from api_forum_comment import router as forum_comment_router


app = FastAPI(
    title="Open Workshop Accounts",
    openapi_url=MAIN_URL+"/openapi.json",
    contact={
        "name": "GitHub",
        "url": "https://github.com/Open-Workshop/open-workshop-accounts"
    },
    license_info={
        "name": "MPL-2.0 license",
        "identifier": "MPL-2.0",
    },
    redoc_url="/"#MAIN_URL
)

app.include_router(game_router)
app.include_router(mod_router)
app.include_router(genre_router)
app.include_router(tag_router)
app.include_router(resource_router)
app.include_router(association_router)
app.include_router(profile_router)
app.include_router(session_router)
app.include_router(reaction_router)
app.include_router(black_list_router)
app.include_router(forum_router)
app.include_router(forum_comment_router)


# TODO переименнованые объекты в catalog_sql.py учитывать во всех остальных файлах
# TODO логика скачивания модов с сервера
# TODO использовать MAIN_URL
