from __future__ import annotations

import datetime
import pathlib
import sys
import types
import unittest
from importlib import import_module
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Delete, Insert, Update

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if "aiomysql" not in sys.modules:
    aiomysql_stub = types.ModuleType("aiomysql")
    aiomysql_stub.__version__ = "0"
    aiomysql_stub.paramstyle = "pyformat"
    aiomysql_stub.connect = lambda *args, **kwargs: None  # pragma: no cover
    aiomysql_stub.Warning = type("Warning", (Exception,), {})
    aiomysql_stub.Error = type("Error", (Exception,), {})
    aiomysql_stub.InterfaceError = type("InterfaceError", (Exception,), {})
    aiomysql_stub.DataError = type("DataError", (Exception,), {})
    aiomysql_stub.DatabaseError = type("DatabaseError", (Exception,), {})
    aiomysql_stub.OperationalError = type("OperationalError", (Exception,), {})
    aiomysql_stub.IntegrityError = type("IntegrityError", (Exception,), {})
    aiomysql_stub.ProgrammingError = type("ProgrammingError", (Exception,), {})
    aiomysql_stub.InternalError = type("InternalError", (Exception,), {})
    aiomysql_stub.NotSupportedError = type("NotSupportedError", (Exception,), {})
    aiomysql_stub.Cursor = type("Cursor", (), {})
    aiomysql_stub.SSCursor = type("SSCursor", (), {})
    aiomysql_cursors_stub = types.ModuleType("aiomysql.cursors")
    aiomysql_cursors_stub.SSCursor = aiomysql_stub.SSCursor
    sys.modules["aiomysql.cursors"] = aiomysql_cursors_stub
    sys.modules["aiomysql"] = aiomysql_stub


class _DummyResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_DummyResult":
        return self

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


class _RecordingSession:
    def __init__(
        self,
        *,
        rows: list[object] | None = None,
        scalar_values: list[object] | None = None,
        get_value: object | None = None,
        allow_writes: bool = False,
    ) -> None:
        self.rows = rows or []
        self.scalar_values = list(scalar_values or [])
        self.get_value = get_value
        self.allow_writes = allow_writes
        self.execute_statements: list[object] = []
        self.scalar_statements: list[object] = []
        self.commit_count = 0
        self.flush_count = 0

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object:
        self.scalar_statements.append(stmt)
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return 0

    async def execute(self, stmt) -> _DummyResult:
        if isinstance(stmt, (Insert, Update, Delete)) and not self.allow_writes:
            raise AssertionError(f"Unexpected write statement: {stmt!r}")
        self.execute_statements.append(stmt)
        return _DummyResult(self.rows)

    async def get(self, *args, **kwargs) -> object | None:
        return self.get_value

    async def commit(self) -> None:
        if not self.allow_writes:
            raise AssertionError("Unexpected commit")
        self.commit_count += 1

    async def flush(self) -> None:
        if not self.allow_writes:
            raise AssertionError("Unexpected flush")
        self.flush_count += 1


def _mod(
    *,
    mod_id: int = 7,
    name: str = "Sized Mod",
    short_description: str = "Short",
    description: str = "Long",
    source: str = "local",
    source_id: int = 11,
    game: int | None = None,
    public: int = 0,
    adult: bool = False,
    condition: int = 0,
    downloads: int = 42,
    size: int = 150,
    size_unpacked: int | None = 320,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=mod_id,
        name=name,
        short_description=short_description,
        description=description,
        source=source,
        source_id=source_id,
        game=game,
        public=public,
        adult=adult,
        condition=condition,
        downloads=downloads,
        size=size,
        size_unpacked=size_unpacked,
        date_creation=datetime.datetime(2026, 4, 27, 12, 0, 0),
        date_update_file=datetime.datetime(2026, 4, 27, 12, 5, 0),
        date_edit=datetime.datetime(2026, 4, 27, 12, 10, 0),
    )


def _game(
    *,
    game_id: int = 1,
    name: str = "Project Zomboid",
    type_: str = "game",
    source: str = "steam",
    source_id: int = 108600,
    mods_count: int = 123,
    mods_downloads: int = 4567,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=game_id,
        name=name,
        short_description="Short",
        description="Long",
        type=type_,
        source=source,
        source_id=source_id,
        mods_count=mods_count,
        mods_downloads=mods_downloads,
        creation_date=datetime.datetime(2026, 4, 27, 12, 0, 0),
    )


def _resource(
    *,
    resource_id: int = 55,
    owner_type: str = "games",
    owner_id: int = 1,
    type_: str = "screenshot",
    url: str = "https://example.com/image.webp",
    size: int | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=resource_id,
        owner_type=owner_type,
        owner_id=owner_id,
        type=type_,
        url=url,
        size=size,
        date_event=datetime.datetime(2026, 4, 27, 12, 0, 0),
        real_url=url,
    )


class ModListSizeFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        standarts = import_module("open_workshop_manager.standarts")
        cls.api_mod = import_module("open_workshop_manager.mods.api_mod")
        cls.api_game = import_module("open_workshop_manager.games.api_game")
        cls.api_resource = import_module("open_workshop_manager.mods.api_resource")
        cls.api_profile = import_module("open_workshop_manager.social.api_profile")
        settings = import_module("open_workshop_manager.settings")
        cls.main_url = ""
        cls.storage_url = settings.STORAGE_URL

        cls.standarts = standarts
        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(cls.api_mod.router)
        app.include_router(cls.api_game.router)
        app.include_router(cls.api_resource.router)
        app.include_router(cls.api_profile.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_mod_list_returns_items_and_pagination(self) -> None:
        session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"page": 0, "page_size": 20, "sort": "-downloads"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"], {
            "page": 0,
            "page_size": 20,
            "offset": 0,
            "total": 1,
            "has_next": False,
            "has_previous": False,
        })
        self.assertEqual(body["items"][0]["id"], 7)
        self.assertEqual(body["items"][0]["size"], 150)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_mod_list_rejects_invalid_size_range(self) -> None:
        response = self.client.get(
            f"{self.main_url}/mods",
            params={"size_min": 200, "size_max": 100},
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "INVALID_SIZE_RANGE")
        self.assertEqual(body["status"], 400)
        self.assertTrue(body["instance"].endswith("/mods?size_min=200&size_max=100"))

    def test_mod_list_rejects_unknown_sort_field(self) -> None:
        response = self.client.get(f"{self.main_url}/mods", params={"sort": "unknown"})

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "UNSUPPORTED_SORT_FIELD")
        self.assertEqual(body["context"]["field"], "unknown")

    def test_mod_feed_returns_range_bounds(self) -> None:
        session = _RecordingSession(scalar_values=[17, 1024, 4096, 2048, 8192])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/mods/feed", params={"game": 7})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 17)
        self.assertEqual(body["size"], {"min": 1024, "max": 4096})
        self.assertEqual(body["size_unpacked"], {"min": 2048, "max": 8192})
        self.assertEqual(len(session.scalar_statements), 5)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_mod_info_includes_dependency_collection(self) -> None:
        session = _RecordingSession(rows=[1, 2, 3], get_value=_mod())

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods/7",
                params={"include": ["dependencies"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["dependencies"], {"count": 3, "items": [1, 2, 3]})
        self.assertNotIn("dependencies_count", body)

    def test_mod_dependencies_endpoint_returns_count_and_items(self) -> None:
        session = _RecordingSession(rows=[1, 2, 3], get_value=_mod())
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.get(f"{self.main_url}/mods/7/dependencies")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body, {"count": 3, "items": [1, 2, 3]})
        access_mods.assert_awaited_once()

    def test_mod_download_url_registers_download_and_returns_storage_url(self) -> None:
        session = _RecordingSession(get_value=_mod(name="Downloadable Mod"), allow_writes=True)
        access_mods = AsyncMock(return_value=True)
        publish_event = AsyncMock(return_value=None)

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mods,
        ), patch.object(self.api_mod.mod_events, "publish_mod_event", publish_event):
            response = self.client.post(f"{self.main_url}/mods/7/download-url")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertNotIn("id", body)
        self.assertEqual(body["mod_id"], 7)
        self.assertEqual(body["filename"], "Downloadable_Mod")
        self.assertEqual(
            body["download_url"],
            f"{self.storage_url}/download/archive/mods/7/main.zip?filename=Downloadable_Mod",
        )
        self.assertEqual(session.commit_count, 1)
        self.assertTrue(any(isinstance(stmt, Update) for stmt in session.execute_statements))
        access_mods.assert_awaited_once()
        publish_event.assert_awaited_once()

    def test_games_list_returns_items_and_pagination(self) -> None:
        session = _RecordingSession(rows=[_game()], scalar_values=[1])

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/games",
                params={
                    "page": 0,
                    "page_size": 20,
                    "sort": "-mods_downloads",
                    "types": ["game"],
                    "sources": ["steam"],
                    "include": ["short_description", "statistics"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["items"][0]["short_description"], "Short")
        self.assertNotIn("description", body["items"][0])
        self.assertEqual(body["items"][0]["mods_downloads"], 4567)
        self.assertEqual(body["items"][0]["source"], "steam")
        self.assertEqual(session.commit_count, 0)

    def test_games_list_omits_short_description_by_default(self) -> None:
        session = _RecordingSession(rows=[_game()], scalar_values=[1])

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/games",
                params={
                    "page": 0,
                    "page_size": 20,
                    "sort": "-mods_downloads",
                    "types": ["game"],
                    "sources": ["steam"],
                    "include": ["statistics"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("short_description", body["items"][0])
        self.assertNotIn("description", body["items"][0])
        self.assertEqual(body["items"][0]["mods_downloads"], 4567)

    def test_game_info_returns_description_on_demand(self) -> None:
        session = _RecordingSession(get_value=_game())

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/games/1",
                params={"include": ["short_description", "description"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["short_description"], "Short")
        self.assertEqual(body["description"], "Long")
        self.assertNotIn("mods_count", body)
        self.assertNotIn("mods_downloads", body)

    def test_game_info_omits_optional_fields_by_default(self) -> None:
        session = _RecordingSession(get_value=_game())

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/games/1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("short_description", body)
        self.assertNotIn("description", body)
        self.assertNotIn("mods_count", body)
        self.assertNotIn("mods_downloads", body)
        self.assertNotIn("created_at", body)

    def test_resources_list_is_get_safe(self) -> None:
        session = _RecordingSession(rows=[_resource()], scalar_values=[1])

        with patch.object(self.api_resource.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/resources",
                params={
                    "owner_type": "games",
                    "owner_ids": [1],
                    "types": ["screenshot"],
                    "page": 0,
                    "page_size": 20,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"][0]["owner_type"], "games")
        self.assertEqual(body["items"][0]["url"], "https://example.com/image.webp")
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_profile_avatar_get_is_get_safe(self) -> None:
        session = _RecordingSession(scalar_values=["local/avatar.webp"])

        with patch.object(self.api_profile.account, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/profiles/123/avatar", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertIn(f"{self.storage_url}/download/avatar/123.webp", response.headers["location"])
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_openapi_documents_public_operations(self) -> None:
        schema = self.client.app.openapi()
        missing: list[str] = []
        for path, path_item in schema.get("paths", {}).items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                    continue
                if not operation.get("summary") or not operation.get("description"):
                    missing.append(f"{method.upper()} {path}")

        self.assertEqual(missing, [])

        def include_enum(path: str, method: str) -> set[str]:
            for parameter in schema["paths"][path][method]["parameters"]:
                if parameter["name"] == "include":
                    return set(parameter["schema"]["items"]["enum"])
            self.fail(f"include parameter missing for {method.upper()} {path}")

        self.assertEqual(
            include_enum("/games", "get"),
            {"short_description", "description", "dates", "statistics", "genres", "tags", "resources"},
        )
        self.assertEqual(
            include_enum("/games/{game_id}", "get"),
            {"short_description", "description", "dates", "statistics", "genres", "tags", "resources"},
        )
        self.assertEqual(
            include_enum("/mods", "get"),
            {"short_description", "description", "dates", "game", "tags", "dependencies", "authors", "resources"},
        )
        self.assertEqual(
            include_enum("/mods/{mod_id}", "get"),
            {"short_description", "description", "dates", "game", "tags", "dependencies", "authors", "resources"},
        )
        self.assertEqual(
            include_enum("/profiles/{user_id}", "get"),
            {"general", "rights", "private"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
