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
        selected_columns = list(getattr(stmt, "selected_columns", []))
        if len(selected_columns) == 1 and getattr(selected_columns[0], "name", None) == "id":
            return _DummyResult([int(getattr(row, "id", row)) for row in self.rows])
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


def _account(
    *,
    account_id: int = 123,
    username: str = "Author",
    author_mods: int = 0,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=account_id,
        username=username,
        author_mods=author_mods,
    )


def _profile(
    *,
    profile_id: int = 123,
    username: str = "Author",
    grade: str = "VIP",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=profile_id,
        username=username,
        about="About",
        avatar_url="local.webp",
        grade=grade,
        comments=7,
        author_mods=3,
        registration_date=datetime.datetime(2026, 4, 27, 12, 0, 0),
        reputation=42,
        mute_until=None,
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
    sort_order: int = 0,
    url: str = "https://example.com/image.webp",
    size: int | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=resource_id,
        owner_type=owner_type,
        owner_id=owner_id,
        type=type_,
        sort_order=sort_order,
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
        cls.api_association = import_module("open_workshop_manager.association.api_association_control")
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
        app.include_router(cls.api_association.router)
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
        self.assertIn("adult", body["items"][0])
        self.assertFalse(body["items"][0]["adult"])
        self.assertEqual(body["items"][0]["size"], 150)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("mods.public = 0", count_sql)
        self.assertIn("mods.public = 0", list_sql)

    def test_mod_list_filters_by_author_alias(self) -> None:
        session = _RecordingSession(rows=[_mod(mod_id=11)], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"page": 0, "page_size": 20, "sort": "-created_at", "user": 3},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("mods_and_authors", count_sql)
        self.assertIn("user_id = 3", count_sql)
        self.assertIn("mods.public = 0", count_sql)
        self.assertIn("mods_and_authors", list_sql)
        self.assertIn("user_id = 3", list_sql)
        self.assertIn("mods.public = 0", list_sql)

    def test_mod_list_can_include_non_public_author_mods(self) -> None:
        session = _RecordingSession(
            rows=[_mod(mod_id=11, public=1), _mod(mod_id=12, public=0)],
            scalar_values=[2],
        )
        access_mock = AsyncMock(return_value=[11, 12])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mock,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "sort": "-created_at",
                    "user": 3,
                    "show_not_public": "true",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["id"] for item in body["items"]], [11, 12])
        self.assertEqual(body["pagination"]["total"], 2)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 2)
        access_mock.assert_awaited_once()
        access_call = access_mock.await_args.kwargs
        self.assertEqual(access_call["mods_ids"], [11, 12])
        self.assertEqual(access_call["author_id"], 3)
        self.assertTrue(access_call["catalog"])
        self.assertTrue(access_call["check_mode"])

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        candidate_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        list_sql = str(session.execute_statements[1].compile(compile_kwargs={"literal_binds": True}))
        self.assertNotIn("mods.public = 0", count_sql)
        self.assertNotIn("mods.public = 0", candidate_sql)
        self.assertNotIn("mods.public = 0", list_sql)

    def test_mod_list_applies_adult_filters_for_false_and_true(self) -> None:
        for adult_value, expected_sql_value in ((0, "false"), (1, "true")):
            with self.subTest(adult_value=adult_value):
                session = _RecordingSession(rows=[_mod()], scalar_values=[1])

                with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
                    response = self.client.get(
                        f"{self.main_url}/mods",
                        params={"page": 0, "page_size": 20, "sort": "-downloads", "adult": adult_value},
                    )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(session.scalar_statements), 1)
                self.assertEqual(len(session.execute_statements), 1)

                count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
                list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
                self.assertIn(f"mods.adult = {expected_sql_value}", count_sql)
                self.assertIn(f"mods.adult = {expected_sql_value}", list_sql)

    def test_mod_list_treats_bare_dependency_as_any(self) -> None:
        bare_session = _RecordingSession(rows=[_mod()], scalar_values=[1])
        explicit_session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=bare_session):
            bare_response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "dependencies": [14],
                },
            )

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=explicit_session):
            explicit_response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "dependencies": ["14:any"],
                },
            )

        self.assertEqual(bare_response.status_code, 200)
        self.assertEqual(explicit_response.status_code, 200)
        self.assertEqual(len(bare_session.scalar_statements), 1)
        self.assertEqual(len(explicit_session.scalar_statements), 1)
        self.assertEqual(len(bare_session.execute_statements), 1)
        self.assertEqual(len(explicit_session.execute_statements), 1)

        bare_count_sql = str(bare_session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        explicit_count_sql = str(explicit_session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        bare_list_sql = str(bare_session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        explicit_list_sql = str(explicit_session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertEqual(bare_count_sql, explicit_count_sql)
        self.assertEqual(bare_list_sql, explicit_list_sql)
        self.assertIn("mods_dependencies", bare_count_sql)
        self.assertIn("mods_dependencies", bare_list_sql)

    def test_mod_list_filters_dependencies_by_per_item_modes(self) -> None:
        session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "dependencies": ["1:required", "2:optional"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("mods_dependencies", count_sql)
        self.assertIn("mods_dependencies", list_sql)
        self.assertIn("optional", count_sql)
        self.assertIn("optional", list_sql)
        self.assertIn("is false", count_sql)
        self.assertIn("is true", count_sql)
        self.assertIn("is false", list_sql)
        self.assertIn("is true", list_sql)

    def test_mod_list_excludes_conflicting_mods(self) -> None:
        session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "excluded_conflicts": [8, 9],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("mods_conflicts", count_sql)
        self.assertIn("mods_conflicts", list_sql)
        self.assertIn("conflict", count_sql)
        self.assertIn("conflict", list_sql)
        self.assertIn("8", count_sql)
        self.assertIn("9", count_sql)
        self.assertIn("8", list_sql)
        self.assertIn("9", list_sql)

    def test_mod_list_treats_bare_excluded_dependency_as_any(self) -> None:
        bare_session = _RecordingSession(rows=[_mod()], scalar_values=[1])
        explicit_session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=bare_session):
            bare_response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "excluded_dependencies": [14],
                },
            )

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=explicit_session):
            explicit_response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "excluded_dependencies": ["14:any"],
                },
            )

        self.assertEqual(bare_response.status_code, 200)
        self.assertEqual(explicit_response.status_code, 200)
        self.assertEqual(len(bare_session.scalar_statements), 1)
        self.assertEqual(len(explicit_session.scalar_statements), 1)
        self.assertEqual(len(bare_session.execute_statements), 1)
        self.assertEqual(len(explicit_session.execute_statements), 1)

        bare_count_sql = str(bare_session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        explicit_count_sql = str(explicit_session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        bare_list_sql = str(bare_session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        explicit_list_sql = str(explicit_session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertEqual(bare_count_sql, explicit_count_sql)
        self.assertEqual(bare_list_sql, explicit_list_sql)
        self.assertIn("mods_dependencies", bare_count_sql)
        self.assertIn("mods_dependencies", bare_list_sql)

    def test_mod_list_excludes_dependencies_by_per_item_modes(self) -> None:
        session = _RecordingSession(rows=[_mod()], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={
                    "page": 0,
                    "page_size": 20,
                    "excluded_dependencies": ["4:required", "5:optional"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("mods_dependencies", count_sql)
        self.assertIn("mods_dependencies", list_sql)
        self.assertIn("optional", count_sql)
        self.assertIn("optional", list_sql)
        self.assertIn("is false", count_sql)
        self.assertIn("is true", count_sql)
        self.assertIn("is false", list_sql)
        self.assertIn("is true", list_sql)

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

    def test_mod_feed_can_include_non_public_author_mods(self) -> None:
        session = _RecordingSession(
            rows=[_mod(mod_id=11, public=1), _mod(mod_id=12, public=0)],
            scalar_values=[2, 100, 200, 300, 400],
        )
        access_mock = AsyncMock(return_value=[11, 12])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mock,
        ):
            response = self.client.get(
                f"{self.main_url}/mods/feed",
                params={"user": 7, "show_not_public": "true"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["size"], {"min": 100, "max": 200})
        self.assertEqual(body["size_unpacked"], {"min": 300, "max": 400})
        self.assertEqual(len(session.execute_statements), 1)
        self.assertEqual(len(session.scalar_statements), 5)
        access_mock.assert_awaited_once()
        access_call = access_mock.await_args.kwargs
        self.assertEqual(access_call["mods_ids"], [11, 12])
        self.assertEqual(access_call["author_id"], 7)
        self.assertTrue(access_call["catalog"])
        self.assertTrue(access_call["check_mode"])

    def test_mod_info_includes_dependency_collection(self) -> None:
        session = _RecordingSession(rows=[1, 2, 3], get_value=_mod())

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods/7",
                params={"include": ["dependencies"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("adult", body)
        self.assertFalse(body["adult"])
        self.assertEqual(
            body["dependencies"],
            {
                "count": 3,
                "items": [
                    {"mod_id": 1, "optional": False},
                    {"mod_id": 2, "optional": False},
                    {"mod_id": 3, "optional": False},
                ],
            },
        )
        self.assertNotIn("dependencies_count", body)
        self.assertNotIn("conflicts", body)

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
        self.assertEqual(
            body,
            {
                "count": 3,
                "items": [
                    {"mod_id": 1, "optional": False},
                    {"mod_id": 2, "optional": False},
                    {"mod_id": 3, "optional": False},
                ],
            },
        )
        access_mods.assert_awaited_once()

    def test_mod_dependencies_endpoint_serializes_optional_flags(self) -> None:
        session = _RecordingSession(
            rows=[
                types.SimpleNamespace(dependence=1, optional=True),
                types.SimpleNamespace(dependence=2, optional=False),
            ],
            get_value=_mod(),
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.get(f"{self.main_url}/mods/7/dependencies")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body,
            {
                "count": 2,
                "items": [
                    {"mod_id": 1, "optional": True},
                    {"mod_id": 2, "optional": False},
                ],
            },
        )

    def test_mod_conflicts_endpoint_returns_count_and_items(self) -> None:
        session = _RecordingSession(rows=[1, 5], get_value=_mod())
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.get(f"{self.main_url}/mods/7/conflicts")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body, {"count": 2, "items": [1, 5]})
        access_mods.assert_awaited_once()

    def test_mod_dependency_post_creates_optional_false_by_default(self) -> None:
        session = _RecordingSession(get_value=_mod(), allow_writes=True)
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_association.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.post(f"{self.main_url}/mods/7/dependencies/13")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(sum(isinstance(stmt, Insert) for stmt in session.execute_statements), 1)
        insert_stmt = next(stmt for stmt in session.execute_statements if isinstance(stmt, Insert))
        insert_sql = str(insert_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_mods_dependencies", insert_sql)
        self.assertIn("optional", insert_sql)
        self.assertIn("false", insert_sql)

    def test_mod_dependency_put_updates_optional_flag(self) -> None:
        session = _RecordingSession(
            rows=[types.SimpleNamespace(optional=False)],
            get_value=_mod(),
            allow_writes=True,
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_association.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.put(
                f"{self.main_url}/mods/7/dependencies/13",
                json={"optional": True},
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(sum(isinstance(stmt, Update) for stmt in session.execute_statements), 1)
        update_stmt = next(stmt for stmt in session.execute_statements if isinstance(stmt, Update))
        update_sql = str(update_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_mods_dependencies", update_sql)
        self.assertIn("optional", update_sql)
        self.assertIn("true", update_sql)

    def test_mod_conflict_post_creates_relation(self) -> None:
        session = _RecordingSession(get_value=_mod(), allow_writes=True)
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_association.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.post(f"{self.main_url}/mods/7/conflicts/13")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(sum(isinstance(stmt, Insert) for stmt in session.execute_statements), 1)
        insert_stmt = next(stmt for stmt in session.execute_statements if isinstance(stmt, Insert))
        insert_sql = str(insert_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_mods_conflicts", insert_sql)

    def test_mod_authors_put_adds_author(self) -> None:
        catalog_session = _RecordingSession(get_value=_mod())
        account_session = _RecordingSession(
            get_value=_account(),
            scalar_values=[None],
            allow_writes=True,
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=catalog_session), patch.object(
            self.api_association.account,
            "AsyncSessionLocal",
            return_value=account_session,
        ), patch.object(self.api_association.tools, "access_mods", access_mods):
            response = self.client.put(
                f"{self.main_url}/mods/7/authors/123",
                json={"owner": False},
            )

        self.assertEqual(response.status_code, 204)
        access_mods.assert_awaited_once()
        self.assertEqual(catalog_session.commit_count, 0)
        self.assertEqual(account_session.commit_count, 1)
        self.assertEqual(len(account_session.execute_statements), 2)
        self.assertTrue(any(isinstance(stmt, Insert) for stmt in account_session.execute_statements))
        self.assertTrue(any(isinstance(stmt, Update) for stmt in account_session.execute_statements))

    def test_mod_authors_put_sets_owner(self) -> None:
        catalog_session = _RecordingSession(get_value=_mod())
        account_session = _RecordingSession(
            get_value=_account(),
            scalar_values=[None],
            allow_writes=True,
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=catalog_session), patch.object(
            self.api_association.account,
            "AsyncSessionLocal",
            return_value=account_session,
        ), patch.object(self.api_association.tools, "access_mods", access_mods):
            response = self.client.put(
                f"{self.main_url}/mods/7/authors/123",
                json={"owner": True},
            )

        self.assertEqual(response.status_code, 204)
        access_mods.assert_awaited_once()
        self.assertEqual(account_session.commit_count, 1)
        self.assertEqual(len(account_session.execute_statements), 3)
        self.assertEqual(sum(isinstance(stmt, Insert) for stmt in account_session.execute_statements), 1)
        self.assertEqual(sum(isinstance(stmt, Update) for stmt in account_session.execute_statements), 2)

    def test_mod_authors_delete_removes_author(self) -> None:
        catalog_session = _RecordingSession(get_value=_mod())
        account_session = _RecordingSession(
            get_value=_account(),
            scalar_values=[True],
            allow_writes=True,
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=catalog_session), patch.object(
            self.api_association.account,
            "AsyncSessionLocal",
            return_value=account_session,
        ), patch.object(self.api_association.tools, "access_mods", access_mods):
            response = self.client.delete(f"{self.main_url}/mods/7/authors/123")

        self.assertEqual(response.status_code, 204)
        access_mods.assert_awaited_once()
        self.assertEqual(account_session.commit_count, 1)
        self.assertEqual(len(account_session.execute_statements), 2)
        self.assertTrue(any(isinstance(stmt, Delete) for stmt in account_session.execute_statements))
        self.assertTrue(any(isinstance(stmt, Update) for stmt in account_session.execute_statements))

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
        session = _RecordingSession(rows=[_resource(sort_order=5)], scalar_values=[1])

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
        self.assertEqual(body["items"][0]["sort_order"], 5)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("ORDER BY resources.sort_order", list_sql)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_resources_list_supports_descending_sort_order(self) -> None:
        session = _RecordingSession(
            rows=[_resource(sort_order=9), _resource(resource_id=56, sort_order=3)],
            scalar_values=[2],
        )

        with patch.object(self.api_resource.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/resources",
                params={
                    "owner_type": "games",
                    "owner_ids": [1],
                    "page": 0,
                    "page_size": 20,
                    "sort": "-sort_order",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["sort_order"] for item in body["items"]], [9, 3])
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("ORDER BY resources.sort_order DESC", list_sql)

    def test_profile_avatar_get_is_get_safe(self) -> None:
        session = _RecordingSession(scalar_values=["local/avatar.webp"])

        with patch.object(self.api_profile.account, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/profiles/123/avatar", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertIn(f"{self.storage_url}/download/avatar/123.webp", response.headers["location"])
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_profile_list_searches_by_username(self) -> None:
        session = _RecordingSession(rows=[_profile()], scalar_values=[1])

        with patch.object(self.api_profile.account, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/profiles",
                params={"page": 0, "page_size": 10, "username": "Auth"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"], {
            "page": 0,
            "page_size": 10,
            "offset": 0,
            "total": 1,
            "has_next": False,
            "has_previous": False,
        })
        self.assertEqual(body["items"][0]["id"], 123)
        self.assertEqual(body["items"][0]["username"], "Author")
        self.assertEqual(body["items"][0]["grade"], "VIP")
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("accounts", count_sql)
        self.assertIn("accounts.username", count_sql.lower())
        self.assertIn("%auth%", count_sql.lower())
        self.assertIn("accounts", list_sql)
        self.assertIn("accounts.username", list_sql.lower())
        self.assertIn("%auth%", list_sql.lower())
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

        def parameter_names(path: str, method: str) -> set[str]:
            return {parameter["name"] for parameter in schema["paths"][path][method]["parameters"]}

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
            {"short_description", "description", "dates", "game", "tags", "dependencies", "conflicts", "authors", "resources"},
        )
        self.assertEqual(
            include_enum("/mods/{mod_id}", "get"),
            {"short_description", "description", "dates", "game", "tags", "dependencies", "conflicts", "authors", "resources"},
        )
        self.assertIn("adult", parameter_names("/mods", "get"))
        self.assertIn("show_not_public", parameter_names("/mods", "get"))
        self.assertIn("show_not_public", parameter_names("/mods/feed", "get"))
        self.assertIn("author_id", parameter_names("/mods/feed", "get"))
        self.assertIn("user", parameter_names("/mods/feed", "get"))
        self.assertIn("sort", parameter_names("/resources", "get"))
        mod_read = schema["components"]["schemas"]["ModRead"]
        self.assertIn("adult", mod_read["properties"])
        self.assertIn("adult", mod_read["required"])
        self.assertEqual(mod_read["properties"]["adult"]["type"], "boolean")
        resource_read = schema["components"]["schemas"]["ResourceRead"]
        self.assertIn("sort_order", resource_read["properties"])
        self.assertIn("sort_order", resource_read["required"])
        mod_params = parameter_names("/mods", "get")
        self.assertIn("excluded_conflicts", mod_params)
        dependencies_param = next(
            parameter
            for parameter in schema["paths"]["/mods"]["get"]["parameters"]
            if parameter["name"] == "dependencies"
        )
        self.assertEqual(dependencies_param["schema"]["items"]["type"], "string")
        excluded_dependencies_param = next(
            parameter
            for parameter in schema["paths"]["/mods"]["get"]["parameters"]
            if parameter["name"] == "excluded_dependencies"
        )
        self.assertEqual(excluded_dependencies_param["schema"]["items"]["type"], "string")
        self.assertEqual(
            include_enum("/profiles/{user_id}", "get"),
            {"general", "rights", "private"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
