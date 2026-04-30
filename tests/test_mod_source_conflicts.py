from __future__ import annotations

import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


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


from open_workshop_manager import standarts
from open_workshop_manager.mods import api_mod


class _SourceConflictSession:
    def __init__(self, existing_mod: object | None = None) -> None:
        self.existing_mod = existing_mod
        self.scalar_statements: list[object] = []
        self.commit_count = 0
        self.flush_count = 0
        self.added: list[object] = []

    async def __aenter__(self) -> "_SourceConflictSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object | None:
        self.scalar_statements.append(stmt)
        if self.existing_mod is None:
            return None

        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "mods.condition = 0" in sql and int(getattr(self.existing_mod, "condition", 0) or 0) != 0:
            return None
        return getattr(self.existing_mod, "id", 1)

    async def get(self, *args, **kwargs) -> object | None:
        return self.existing_mod

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.added and getattr(self.added[-1], "id", None) is None:
            setattr(self.added[-1], "id", 1)

    async def commit(self) -> None:
        self.commit_count += 1


def _mod(
    *,
    mod_id: int = 1,
    source: str = "steam",
    source_id: int = 2284478696,
    git_url: str | None = None,
    condition: int = 1,
    game: int = 7,
    public: int = 0,
) -> types.SimpleNamespace:
    return SimpleNamespace(
        id=mod_id,
        name="Draft Mod",
        short_description="Short",
        description="Long",
        source=source,
        source_id=source_id,
        git_url=git_url,
        game=game,
        public=public,
        adult=False,
        condition=condition,
        downloads=0,
        size=0,
        size_unpacked=None,
        date_creation=None,
        date_update_file=None,
        date_edit=None,
    )


class ModSourceConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(api_mod.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_create_mod_allows_duplicate_uploading_source(self) -> None:
        session = _SourceConflictSession(existing_mod=_mod(condition=1))
        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=-1,
            add=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
            anonymous_add=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
        )

        with (
            patch.object(api_mod.catalog, "AsyncSessionLocal", return_value=session),
            patch.object(api_mod.tools, "access_mod_add", AsyncMock(return_value=access_result)),
            patch.object(api_mod.tools, "check_game_exists", AsyncMock(return_value=True)),
        ):
            response = self.client.post(
                "/mods",
                json={
                    "name": "Draft Mod",
                    "source": "steam",
                    "source_id": 2284478696,
                    "game_id": 7,
                    "public": 0,
                    "adult": False,
                    "without_author": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(session.scalar_statements), 1)
        sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("mods.condition = 0", sql)

    def test_patch_mod_allows_duplicate_uploading_source(self) -> None:
        session = _SourceConflictSession(existing_mod=_mod(condition=1))
        access_result = SimpleNamespace(
            authenticated=True,
            edit=SimpleNamespace(
                title=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                description=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                short_description=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                screenshots=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                new_version=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                authors=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                tags=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                dependencies=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
            ),
        )

        with (
            patch.object(api_mod.catalog, "AsyncSessionLocal", return_value=session),
            patch.object(api_mod.tools, "access_mods", AsyncMock(return_value=access_result)),
            patch.object(api_mod.tools, "check_game_exists", AsyncMock(return_value=True)),
        ):
            response = self.client.patch(
                "/mods/1",
                json={
                    "source": "steam",
                    "source_id": 2284478696,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.scalar_statements), 1)
        sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("mods.condition = 0", sql)

    def test_patch_mod_saves_git_url(self) -> None:
        session = _SourceConflictSession(existing_mod=_mod(condition=1))
        access_result = SimpleNamespace(
            authenticated=True,
            edit=SimpleNamespace(
                title=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                description=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                short_description=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                screenshots=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                new_version=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                authors=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                tags=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
                dependencies=SimpleNamespace(value=True, reason="ok", reason_code="ok"),
            ),
        )
        git_url = "https://github.com/Open-Workshop/example-mod"

        with (
            patch.object(api_mod.catalog, "AsyncSessionLocal", return_value=session),
            patch.object(api_mod.tools, "access_mods", AsyncMock(return_value=access_result)),
        ):
            response = self.client.patch(
                "/mods/1",
                json={"git_url": git_url},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["git_url"], git_url)
        self.assertEqual(getattr(session.existing_mod, "git_url", None), git_url)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
