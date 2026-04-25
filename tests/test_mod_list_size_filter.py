from __future__ import annotations

import pathlib
import sys
import types
import unittest
from importlib import import_module
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import literal_column

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


class _DummySession:
    def __init__(self, rows: list[object], scalar_values: list[object] | None = None) -> None:
        self.rows = rows
        self.executed_sql: list[str] = []
        self.scalar_values = list(scalar_values) if scalar_values is not None else [1]

    async def __aenter__(self) -> "_DummySession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object:  # pragma: no cover - simple stub
        self.executed_sql.append(str(stmt))
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return 0

    async def execute(self, stmt) -> _DummyResult:
        self.executed_sql.append(str(stmt))
        return _DummyResult(self.rows)


class _ModDetailSession(_DummySession):
    def __init__(self, *, public: int, rows: list[object]) -> None:
        super().__init__(rows)
        self.public = public

    async def get(self, *args, **kwargs) -> object:
        return types.SimpleNamespace(public=self.public)


class ModListSizeFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        standarts = import_module("open_workshop_manager.standarts")
        api_mod = import_module("open_workshop_manager.mods.api_mod")
        main_url = import_module("open_workshop_manager.settings").MAIN_URL

        cls.api_mod = api_mod
        cls.main_url = main_url
        cls.standarts = standarts

        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(cls.api_mod.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_mod_list_rejects_reversed_size_range(self) -> None:
        response = self.client.get(
            f"{self.main_url}/mods",
            params={"size_min": 200, "size_max": 100},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Минимальный размер мода не может быть больше максимального!",
        )

    def test_mod_list_applies_size_range_filter(self) -> None:
        mod = types.SimpleNamespace(
            id=7,
            name="Sized Mod",
            description="",
            short_description="",
            date_creation=None,
            date_update_file=None,
            date_edit=None,
            size=150,
            size_unpacked=320,
            source="local",
            source_id=11,
            downloads=42,
        )
        dummy_session = _DummySession([mod])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"size_min": 100, "size_max": 200},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 1)
        self.assertEqual(body["results"][0]["size"], 150)
        self.assertTrue(
            any(
                "mods.size >= " in sql and "mods.size <= " in sql
                for sql in dummy_session.executed_sql
            ),
            msg=f"Captured SQL did not include size bounds: {dummy_session.executed_sql}",
        )

    def test_mod_list_applies_excluded_tags_filter(self) -> None:
        mod = types.SimpleNamespace(
            id=7,
            name="Tagged Mod",
            description="",
            short_description="",
            date_creation=None,
            date_update_file=None,
            date_edit=None,
            size=150,
            size_unpacked=320,
            source="local",
            source_id=11,
            downloads=42,
        )
        dummy_session = _DummySession([mod])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"excluded_tags": "[5, 6]"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 1)
        self.assertTrue(
            any(
                "unity_mods_tags" in sql and "NOT (EXISTS" in sql
                for sql in dummy_session.executed_sql
            ),
            msg=f"Captured SQL did not include excluded tags: {dummy_session.executed_sql}",
        )

    def test_public_mod_dependencies_use_access_service(self) -> None:
        dummy_session = _ModDetailSession(public=0, rows=[3, 5])
        access_mods = AsyncMock(return_value=True)

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ), patch.object(self.api_mod.tools, "access_mods", access_mods):
            response = self.client.get(f"{self.main_url}/mods/7/dependencies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": 2, "results": [3, 5]})
        access_mods.assert_awaited_once()

    def test_private_mod_dependencies_use_access_service(self) -> None:
        dummy_session = _ModDetailSession(public=2, rows=[3])
        access_mods = AsyncMock(return_value=True)

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ), patch.object(self.api_mod.tools, "access_mods", access_mods):
            response = self.client.get(f"{self.main_url}/mods/7/dependencies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": 1, "results": [3]})
        access_mods.assert_awaited_once()

    def test_mod_list_applies_excluded_dependencies_filter(self) -> None:
        mod = types.SimpleNamespace(
            id=7,
            name="Dependent Mod",
            description="",
            short_description="",
            date_creation=None,
            date_update_file=None,
            date_edit=None,
            size=150,
            size_unpacked=320,
            source="local",
            source_id=11,
            downloads=42,
        )
        dummy_session = _DummySession([mod])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"excluded_dependencies": "[7, 8]"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 1)
        self.assertTrue(
            any(
                "unity_mods_dependencies" in sql and "NOT (EXISTS" in sql
                for sql in dummy_session.executed_sql
            ),
            msg=(
                "Captured SQL did not include excluded dependencies: "
                f"{dummy_session.executed_sql}"
            ),
        )

    def test_mod_list_rejects_reversed_dependents_count_range(self) -> None:
        response = self.client.get(
            f"{self.main_url}/mods",
            params={"dependents_count_min": 5, "dependents_count_max": 1},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Минимальное количество зависимых модов не может быть больше максимального!",
        )

    def test_mod_list_applies_dependents_count_range_filter(self) -> None:
        mod = types.SimpleNamespace(
            id=9,
            name="Framework Mod",
            description="",
            short_description="",
            date_creation=None,
            date_update_file=None,
            date_edit=None,
            size=150,
            size_unpacked=320,
            source="local",
            source_id=11,
            downloads=42,
        )
        dummy_session = _DummySession([mod])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"dependents_count_min": 2, "dependents_count_max": 4},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 1)
        self.assertEqual(body["results"][0]["id"], 9)
        self.assertTrue(
            any(
                "unity_mods_dependencies" in sql
                and "dependence" in sql
                and ">=" in sql
                and "<=" in sql
                for sql in dummy_session.executed_sql
            ),
            msg=(
                "Captured SQL did not include dependents count bounds: "
                f"{dummy_session.executed_sql}"
            ),
        )

    def test_sort_helpers_support_download_and_plugins_count_aliases(self) -> None:
        count_expr = literal_column("plugins_count")

        self.assertIs(
            self.api_mod.tools.sort_mods("MOD_DOWNLOADS"),
            self.api_mod.catalog.Mod.downloads,
        )
        self.assertIn(
            "DESC",
            str(self.api_mod.tools.sort_mods("iMOD_DOWNLOADS")).upper(),
        )
        self.assertIn(
            "DESC",
            str(self.api_mod.tools.sort_mods("DOWNLOADS")).upper(),
        )
        self.assertIs(
            self.api_mod.tools.sort_games("MOD_DOWNLOADS"),
            self.api_mod.catalog.Game.mods_downloads,
        )
        self.assertIn(
            "DESC",
            str(self.api_mod.tools.sort_games("MODS_DOWNLOADS")).upper(),
        )
        self.assertIn(
            "DESC",
            str(self.api_mod.tools.sort_games("iMOD_DOWNLOADS")).upper(),
        )

        self.assertIs(self.api_mod.tools.sort_mods("PLUGINS_COUNT", count_expr), count_expr)
        self.assertIn(
            "DESC",
            str(self.api_mod.tools.sort_mods("iPLUGINS_COUNT", count_expr)).upper(),
        )

    def test_mod_list_applies_unpacked_size_range_filter(self) -> None:
        mod = types.SimpleNamespace(
            id=8,
            name="Unpacked Mod",
            description="",
            short_description="",
            date_creation=None,
            date_update_file=None,
            date_edit=None,
            size=150,
            size_unpacked=320,
            source="local",
            source_id=11,
            downloads=42,
        )
        dummy_session = _DummySession([mod])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"size_unpacked_min": 300, "size_unpacked_max": 400},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 1)
        self.assertEqual(body["results"][0]["size_unpacked"], 320)
        self.assertTrue(
            any(
                "mods.size_unpacked >= " in sql and "mods.size_unpacked <= " in sql
                for sql in dummy_session.executed_sql
            ),
            msg=(
                "Captured SQL did not include unpacked size bounds: "
                f"{dummy_session.executed_sql}"
            ),
        )

    def test_mod_feed_returns_size_range(self) -> None:
        dummy_session = _DummySession(
            [],
            scalar_values=[7, 1024, 1048576, 2048, 2097152],
        )

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(f"{self.main_url}/mods/feed")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 7)
        self.assertEqual(body["size_min"], 1024)
        self.assertEqual(body["size_max"], 1048576)
        self.assertEqual(body["size_unpacked_min"], 2048)
        self.assertEqual(body["size_unpacked_max"], 2097152)
        self.assertTrue(
            any(
                "mods.public" in sql and "mods.condition" in sql
                for sql in dummy_session.executed_sql
            ),
            msg=f"Captured SQL did not include visibility filters: {dummy_session.executed_sql}",
        )

    def test_mod_feed_applies_game_filter(self) -> None:
        dummy_session = _DummySession(
            [],
            scalar_values=[4, 128, 256, 512, 1024],
        )

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(
                f"{self.main_url}/mods/feed",
                params={"game": 12},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 4)
        self.assertEqual(body["size_min"], 128)
        self.assertEqual(body["size_max"], 256)
        self.assertEqual(body["size_unpacked_min"], 512)
        self.assertEqual(body["size_unpacked_max"], 1024)
        self.assertTrue(
            any(
                "mods.game =" in sql
                for sql in dummy_session.executed_sql
            ),
            msg=f"Captured SQL did not include game filter: {dummy_session.executed_sql}",
        )

    def test_mod_feed_returns_null_ranges_for_empty_catalog(self) -> None:
        dummy_session = _DummySession([], scalar_values=[0, None, None, None, None])

        with patch.object(
            self.api_mod.catalog,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.get(f"{self.main_url}/mods/feed")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database_size"], 0)
        self.assertIsNone(body["size_min"])
        self.assertIsNone(body["size_max"])
        self.assertIsNone(body["size_unpacked_min"])
        self.assertIsNone(body["size_unpacked_max"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
