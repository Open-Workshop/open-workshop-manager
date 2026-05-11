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
        execute_results: list[list[object]] | None = None,
        scalar_values: list[object] | None = None,
        get_value: object | None = None,
        get_map: dict[object, object] | None = None,
        allow_writes: bool = False,
    ) -> None:
        self.rows = rows or []
        self.execute_results = list(execute_results or [])
        self.scalar_values = list(scalar_values or [])
        self.get_value = get_value
        self.get_map = get_map or {}
        self.allow_writes = allow_writes
        self.execute_statements: list[object] = []
        self.scalar_statements: list[object] = []
        self.added: list[object] = []
        self.commit_count = 0
        self.flush_count = 0
        self.next_id = 100

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object:
        self.scalar_statements.append(stmt)
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return 0

    async def execute(self, stmt, *args, **kwargs) -> _DummyResult:
        if isinstance(stmt, (Insert, Update, Delete)) and not self.allow_writes:
            raise AssertionError(f"Unexpected write statement: {stmt!r}")
        self.execute_statements.append(stmt)
        if self.execute_results:
            return _DummyResult(self.execute_results.pop(0))
        selected_columns = list(getattr(stmt, "selected_columns", []))
        if len(selected_columns) == 1 and getattr(selected_columns[0], "name", None) == "id":
            return _DummyResult([int(getattr(row, "id", row)) for row in self.rows])
        return _DummyResult(self.rows)

    async def get(self, *args, **kwargs) -> object | None:
        if self.get_map and args:
            model = args[0]
            ident = args[1] if len(args) > 1 else None
            if (model, ident) in self.get_map:
                return self.get_map[(model, ident)]
            if model in self.get_map:
                return self.get_map[model]
        return self.get_value

    async def commit(self) -> None:
        if not self.allow_writes:
            raise AssertionError("Unexpected commit")
        self.commit_count += 1

    async def flush(self) -> None:
        if not self.allow_writes:
            raise AssertionError("Unexpected flush")
        for item in self.added:
            if getattr(item, "id", None) is None:
                setattr(item, "id", self.next_id)
                self.next_id += 1
        self.flush_count += 1

    def add(self, item: object) -> None:
        if not self.allow_writes:
            raise AssertionError(f"Unexpected add: {item!r}")
        self.added.append(item)


def _mod(
    *,
    mod_id: int = 7,
    name: str = "Sized Mod",
    short_description: str = "Short",
    description: str = "Long",
    source: str = "local",
    source_id: int = 11,
    git_url: str | None = None,
    game: int | None = None,
    public: int = 0,
    adult: bool = False,
    condition: int = 0,
    downloads: int = 42,
    rating: int = 0,
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
        git_url=git_url,
        game=game,
        public=public,
        adult=adult,
        condition=condition,
        downloads=downloads,
        rating=rating,
        size=size,
        size_unpacked=size_unpacked,
        date_creation=datetime.datetime(2026, 4, 27, 12, 0, 0),
        date_update_file=datetime.datetime(2026, 4, 27, 12, 5, 0),
        date_edit=datetime.datetime(2026, 4, 27, 12, 10, 0),
    )


def _modpack(
    *,
    modpack_id: int = 17,
    name: str = "Sized Pack",
    short_description: str = "Pack Short",
    description: str = "Pack Long",
    source: str = "local",
    source_id: str | int | None = "pack-11",
    game: int | None = 1,
    public: int = 0,
    adult: bool = False,
    condition: int = 0,
    downloads: int = 24,
    rating: int = 0,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=modpack_id,
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
        rating=rating,
        date_creation=datetime.datetime(2026, 4, 27, 12, 0, 0),
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


def _tag(
    *,
    tag_id: int = 10,
    name: str = "Gameplay",
    group: types.SimpleNamespace | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=tag_id,
        name=name,
        group=group,
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
        cls.api_mod_build = import_module("open_workshop_manager.mods.api_mod_build")
        cls.api_tag = import_module("open_workshop_manager.mods.api_tag")
        cls.api_tag_group = import_module("open_workshop_manager.mods.api_tag_group")
        cls.api_modpack = import_module("open_workshop_manager.modpacks.api_modpack")
        cls.api_association = import_module("open_workshop_manager.association.api_association_control")
        cls.api_association_getter = import_module("open_workshop_manager.association.api_association_getter")
        cls.api_game = import_module("open_workshop_manager.games.api_game")
        cls.api_resource = import_module("open_workshop_manager.mods.api_resource")
        cls.api_profile = import_module("open_workshop_manager.social.api_profile")
        settings = import_module("open_workshop_manager.settings")
        cls.main_url = ""
        cls.storage_url = settings.STORAGE_URL

        cls.standarts = standarts
        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(cls.api_mod_build.router)
        app.include_router(cls.api_mod.router)
        app.include_router(cls.api_tag.router)
        app.include_router(cls.api_tag_group.router)
        app.include_router(cls.api_modpack.router)
        app.include_router(cls.api_association.router)
        app.include_router(cls.api_association_getter.router)
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
        self.assertEqual(body["items"][0]["source_id"], "11")
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

    def test_mod_list_supports_rating_sort(self) -> None:
        session = _RecordingSession(rows=[_mod(rating=50)], scalar_values=[1])

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods",
                params={"page": 0, "page_size": 20, "sort": "-rating"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"][0]["rating"], 50)
        self.assertEqual(body["items"][0]["votes_count"], 0)
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("ORDER BY mods.rating DESC", list_sql)

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
        session = _RecordingSession(
            execute_results=[[types.SimpleNamespace(id=5, name="Resolution")]],
            scalar_values=[17, 1024, 4096, 2048, 8192],
        )

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/mods/feed", params={"game": 7})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 17)
        self.assertEqual(body["size"], {"min": 1024, "max": 4096})
        self.assertEqual(body["size_unpacked"], {"min": 2048, "max": 8192})
        self.assertEqual(body["tag_groups"], [{"id": 5, "name": "Resolution"}])
        self.assertEqual(len(session.execute_statements), 1)
        self.assertEqual(len(session.scalar_statements), 5)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.flush_count, 0)

    def test_mod_feed_can_include_non_public_author_mods(self) -> None:
        session = _RecordingSession(
            execute_results=[[], [11, 12]],
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
        self.assertEqual(body["tag_groups"], [])
        self.assertEqual(len(session.execute_statements), 2)
        self.assertEqual(len(session.scalar_statements), 5)
        access_mock.assert_awaited_once()
        access_call = access_mock.await_args.kwargs
        self.assertEqual(access_call["mods_ids"], [11, 12])
        self.assertEqual(access_call["author_id"], 7)
        self.assertTrue(access_call["catalog"])
        self.assertTrue(access_call["check_mode"])

    def test_tag_list_excludes_grouped_tags(self) -> None:
        session = _RecordingSession(
            rows=[types.SimpleNamespace(id=10, name="Gameplay")],
            scalar_values=[1],
        )

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/tags", params={"name": "game"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"], [{"id": 10, "name": "Gameplay"}])
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("group_id is null", count_sql)
        self.assertIn("group_id is null", list_sql)

    def test_tag_list_can_include_games_and_orphaned(self) -> None:
        tag = types.SimpleNamespace(id=10, name="Gameplay", group=None)
        session = _RecordingSession(
            execute_results=[
                [tag],
                [(10, 7), (10, 8)],
                [10],
            ],
            scalar_values=[1],
        )

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/tags",
                params={"name": "game", "include": ["games", "orphaned"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["items"],
            [
                {
                    "id": 10,
                    "name": "Gameplay",
                    "orphaned": True,
                    "games": [7, 8],
                }
            ],
        )
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 3)

    def test_orphan_tag_list_requires_admin_and_checks_usage_relations(self) -> None:
        tag = types.SimpleNamespace(id=10, name="Gameplay")
        session = _RecordingSession(rows=[tag], scalar_values=[1])
        access_mock = AsyncMock(return_value=True)

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_tag.tools,
            "access_admin",
            access_mock,
        ):
            response = self.client.get(f"{self.main_url}/tags/orphaned", params={"name": "game"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["items"],
            [{"id": 10, "name": "Gameplay"}],
        )
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        access_mock.assert_awaited_once()
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_mods_tags", count_sql)
        self.assertIn("modpacks_tags", count_sql)
        self.assertIn("unity_allowed_mods_tags", count_sql)
        self.assertTrue("not (exists" in count_sql or "not exists" in count_sql)
        self.assertIn("unity_mods_tags", list_sql)
        self.assertIn("modpacks_tags", list_sql)
        self.assertIn("unity_allowed_mods_tags", list_sql)
        self.assertTrue("not (exists" in list_sql or "not exists" in list_sql)

    def test_tag_detail_includes_requested_fields(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        tag = types.SimpleNamespace(id=123, name="1920x1080", group=group)
        session = _RecordingSession(
            get_map={(self.api_tag.catalog.Tag, 123): tag},
            execute_results=[[7, 8]],
            scalar_values=[False],
        )

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/tags/123",
                params={"include": ["group", "games", "orphaned"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": 123,
                "name": "1920x1080",
                "group": {"id": 5, "name": "Resolution"},
                "orphaned": False,
                "games": [7, 8],
            },
        )

    def test_create_tag_accepts_group_id(self) -> None:
        group = self.api_tag.catalog.TagGroup(id=5, name="Resolution")
        session = _RecordingSession(
            get_map={self.api_tag.catalog.TagGroup: group},
            allow_writes=True,
        )

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_tag.tools,
            "access_admin",
            AsyncMock(return_value=True),
        ):
            response = self.client.post(
                f"{self.main_url}/tags",
                json={"name": "1920x1080", "group_id": 5},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": 100,
                "name": "1920x1080",
                "group": {"id": 5, "name": "Resolution"},
            },
        )
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.commit_count, 1)

    def test_patch_tag_allows_group_id_null(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        tag = types.SimpleNamespace(id=124, name="2560x1440", group_id=5, group=group)
        session = _RecordingSession(
            get_map={(self.api_tag.catalog.Tag, 124): tag},
            allow_writes=True,
        )

        with patch.object(self.api_tag.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_tag.tools,
            "access_admin",
            AsyncMock(return_value=True),
        ):
            response = self.client.patch(
                f"{self.main_url}/tags/124",
                json={"group_id": None},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": 124, "name": "2560x1440"})
        self.assertIsNone(tag.group_id)
        self.assertIsNone(tag.group)
        self.assertEqual(session.commit_count, 1)

    def test_tag_groups_can_filter_by_game(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(execute_results=[[group]], scalar_values=[1])

        with patch.object(self.api_tag_group.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/tag-groups", params={"game_id": 7})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [{"id": 5, "name": "Resolution"}])
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_allowed_mods_tags", count_sql)
        self.assertIn("game_id = 7", count_sql)
        self.assertIn("unity_allowed_mods_tags", list_sql)
        self.assertIn("game_id = 7", list_sql)

    def test_orphan_tag_group_list_requires_admin_and_checks_empty_groups(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(rows=[group], scalar_values=[1])
        access_mock = AsyncMock(return_value=True)

        with patch.object(self.api_tag_group.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_tag_group.tools,
            "access_admin",
            access_mock,
        ):
            response = self.client.get(f"{self.main_url}/tag-groups/orphaned", params={"name": "res"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [{"id": 5, "name": "Resolution"}])
        self.assertEqual(response.json()["pagination"]["total"], 1)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        access_mock.assert_awaited_once()
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("tag_groups", count_sql)
        self.assertIn("tags", count_sql)
        self.assertTrue("not (exists" in count_sql or "not exists" in count_sql)
        self.assertIn("tag_groups", list_sql)
        self.assertIn("tags", list_sql)
        self.assertTrue("not (exists" in list_sql or "not exists" in list_sql)

    def test_tag_group_tags_can_filter_by_game(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        tag = types.SimpleNamespace(id=123, name="1920x1080", group=group)
        session = _RecordingSession(
            get_map={self.api_tag_group.catalog.TagGroup: group},
            execute_results=[[tag]],
            scalar_values=[1],
        )

        with patch.object(self.api_tag_group.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/tag-groups/5/tags",
                params={"game_id": 7},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["items"],
            [
                {
                    "id": 123,
                    "name": "1920x1080",
                    "group": {"id": 5, "name": "Resolution"},
                }
            ],
        )
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_allowed_mods_tags", count_sql)
        self.assertIn("game_id = 7", count_sql)

    def test_delete_tag_group_rejects_non_empty_group(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(
            get_map={self.api_tag_group.catalog.TagGroup: group},
            scalar_values=[123],
        )

        with patch.object(self.api_tag_group.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_tag_group.tools,
            "access_admin",
            AsyncMock(return_value=True),
        ):
            response = self.client.delete(f"{self.main_url}/tag-groups/5")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "TAG_GROUP_NOT_EMPTY")
        self.assertEqual(session.commit_count, 0)

    def test_modpack_list_filters_by_ids_tags_excluded_tags_sources(self) -> None:
        session = _RecordingSession(
            scalar_values=[1],
            execute_results=[
                [_modpack(modpack_id=17, game=2)],
                [(17, 21, True)],
                [(17, 3, "Adventure", None, None), (17, 5, "QoL", None, None)],
                [_resource(owner_type="modpacks", owner_id=17, type_="banner", sort_order=0)],
                [_game(game_id=2)],
            ],
        )

        with patch.object(self.api_modpack.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/modpacks",
                params={
                    "page": 0,
                    "page_size": 20,
                    "ids": [17, 18],
                    "tags": [3, 5],
                    "excluded_tags": [9],
                    "game_id": 2,
                    "sources": ["steam"],
                    "source_ids": ["pack-11"],
                    "include": ["short_description", "description", "dates", "game", "tags", "authors", "resources"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["items"][0]["id"], 17)
        self.assertEqual(body["items"][0]["short_description"], "Pack Short")
        self.assertEqual(body["items"][0]["description"], "Pack Long")
        self.assertIn("created_at", body["items"][0])
        self.assertIn("updated_at", body["items"][0])
        self.assertEqual(body["items"][0]["game"]["id"], 2)
        self.assertEqual(body["items"][0]["tags"], [
            {"id": 3, "name": "Adventure"},
            {"id": 5, "name": "QoL"},
        ])
        self.assertEqual(body["items"][0]["authors"], {"21": {"owner": True}})
        self.assertEqual(body["items"][0]["resources"][0]["owner_type"], "modpacks")
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 5)
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("modpacks", count_sql)
        self.assertIn("modpacks", list_sql)
        self.assertIn("modpacks_tags", count_sql)
        self.assertIn("modpacks_tags", list_sql)
        self.assertIn("tag_id", count_sql)
        self.assertIn("tag_id", list_sql)
        self.assertIn("source_id", count_sql)
        self.assertIn("source_id", list_sql)
        self.assertIn("steam", count_sql)
        self.assertIn("steam", list_sql)

    def test_modpack_list_accepts_legacy_source_alias(self) -> None:
        session = _RecordingSession(
            scalar_values=[1],
            execute_results=[[_modpack(modpack_id=18)]],
        )

        with patch.object(self.api_modpack.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/modpacks",
                params={
                    "page": 0,
                    "page_size": 20,
                    "source": ["steam"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertNotIn("short_description", body["items"][0])
        self.assertNotIn("description", body["items"][0])
        self.assertNotIn("game", body["items"][0])
        self.assertNotIn("tags", body["items"][0])
        self.assertNotIn("authors", body["items"][0])
        self.assertNotIn("resources", body["items"][0])
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("steam", list_sql)

    def test_mod_info_includes_dependency_collection(self) -> None:
        session = _RecordingSession(
            rows=[1, 2, 3],
            get_value=_mod(git_url="https://github.com/Open-Workshop/example-mod"),
        )

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods/7",
                params={"include": ["dependencies"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("adult", body)
        self.assertFalse(body["adult"])
        self.assertEqual(body["git_url"], "https://github.com/Open-Workshop/example-mod")
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

    def test_mod_info_includes_conflicts_scope(self) -> None:
        session = _RecordingSession(rows=[1, 5], get_value=_mod())

        with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/mods/7",
                params={"include": ["conflicts"], "scope": "incoming"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["conflicts"], {"count": 2, "items": [1, 5]})
        sql = " ".join(str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower().split())
        self.assertIn("unity_mods_conflicts.mod_id as mod_id", sql)
        self.assertIn("unity_mods_conflicts.conflict = 7", sql)

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

    def test_mod_dependency_delete_removes_relation(self) -> None:
        session = _RecordingSession(get_value=_mod(), allow_writes=True)
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_association.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_association.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.delete(f"{self.main_url}/mods/7/dependencies/13")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(sum(isinstance(stmt, Delete) for stmt in session.execute_statements), 1)
        delete_stmt = next(stmt for stmt in session.execute_statements if isinstance(stmt, Delete))
        delete_sql = str(delete_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("unity_mods_dependencies", delete_sql)
        self.assertIn("mod_id", delete_sql)
        self.assertIn("dependence", delete_sql)
        access_mods.assert_awaited_once()

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

    def test_mod_conflicts_endpoint_scope_controls_direction(self) -> None:
        cases = {
            "outgoing": ("unity_mods_conflicts.conflict as mod_id", "unity_mods_conflicts.mod_id = 7"),
            "incoming": ("unity_mods_conflicts.mod_id as mod_id", "unity_mods_conflicts.conflict = 7"),
            "all": ("select distinct case when", "unity_mods_conflicts.mod_id = 7 or unity_mods_conflicts.conflict = 7"),
        }

        for scope, expected_snippets in cases.items():
            with self.subTest(scope=scope):
                session = _RecordingSession(rows=[1, 5], get_value=_mod())
                access_mods = AsyncMock(return_value=True)

                with patch.object(self.api_mod.catalog, "AsyncSessionLocal", return_value=session), patch.object(
                    self.api_mod.tools,
                    "access_mods",
                    access_mods,
                ):
                    response = self.client.get(
                        f"{self.main_url}/mods/7/conflicts",
                        params={"scope": scope},
                    )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"count": 2, "items": [1, 5]})
                access_mods.assert_awaited_once()
                sql = " ".join(
                    str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower().split()
                )
                for expected_snippet in expected_snippets:
                    self.assertIn(expected_snippet, sql)

    def test_mod_build_conflicts_endpoint_returns_conflicting_mod_ids(self) -> None:
        session = _RecordingSession(
            execute_results=[
                [1, 2, 3],
                [
                    (1, 2),
                    (3, 2),
                ],
                [
                    (1, "One"),
                    (2, "Two"),
                    (3, "Three"),
                ],
            ],
            get_value=_mod(),
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_mod_build.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod_build.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.get(
                "/mods/build/conflicts",
                params=[("mods_ids", 1), ("mods_ids", 2), ("mods_ids", 3)],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "nodes": [
                    {
                        "mod_id": 1,
                        "mod_name": "One",
                        "selected": True,
                    },
                    {
                        "mod_id": 2,
                        "mod_name": "Two",
                        "selected": True,
                    },
                    {
                        "mod_id": 3,
                        "mod_name": "Three",
                        "selected": True,
                    },
                ],
                "edges": [
                    {
                        "source_mod_id": 1,
                        "target_mod_id": 2,
                    },
                    {
                        "source_mod_id": 2,
                        "target_mod_id": 3,
                    },
                ],
            },
        )
        access_mods.assert_awaited_once()
        self.assertEqual(len(session.execute_statements), 3)

    def test_mod_build_missing_dependencies_endpoint_traverses_required_chain(self) -> None:
        session = _RecordingSession(
            execute_results=[
                [1],
                [(1, 2)],
                [(2, 3)],
                [],
                [
                    (1, "D"),
                    (2, "B"),
                    (3, "A"),
                ],
            ],
            get_value=_mod(),
        )
        access_mods = AsyncMock(return_value=True)

        with patch.object(self.api_mod_build.catalog, "AsyncSessionLocal", return_value=session), patch.object(
            self.api_mod_build.tools,
            "access_mods",
            access_mods,
        ):
            response = self.client.get(
                "/mods/build/dependencies/missing",
                params=[("mods_ids", 1)],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "nodes": [
                    {
                        "mod_id": 1,
                        "mod_name": "D",
                        "selected": True,
                    },
                    {
                        "mod_id": 2,
                        "mod_name": "B",
                        "selected": False,
                    },
                    {
                        "mod_id": 3,
                        "mod_name": "A",
                        "selected": False,
                    },
                ],
                "edges": [
                    {
                        "source_mod_id": 1,
                        "target_mod_id": 2,
                    },
                    {
                        "source_mod_id": 2,
                        "target_mod_id": 3,
                    },
                ],
            },
        )
        access_mods.assert_awaited_once()
        self.assertEqual(len(session.execute_statements), 5)

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
        self.assertEqual(body["items"][0]["source_id"], "108600")
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

    def test_game_info_includes_grouped_tags(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(get_value=_game(), execute_results=[[_tag(), _tag(tag_id=11, name="1920x1080", group=group)]])

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/games/1", params={"include": ["tags"]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["tags"],
            [
                {"id": 10, "name": "Gameplay"},
                {"id": 11, "name": "1920x1080", "group": {"id": 5, "name": "Resolution"}},
            ],
        )
        self.assertEqual(len(session.scalar_statements), 0)
        self.assertEqual(len(session.execute_statements), 1)

    def test_games_list_includes_grouped_tags(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        game = _game()
        session = _RecordingSession(
            execute_results=[
                [game],
                [_tag(), _tag(tag_id=11, name="1920x1080", group=group)],
            ],
            scalar_values=[1],
        )

        with patch.object(self.api_game.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(f"{self.main_url}/games", params={"include": ["tags"]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["items"][0]["tags"],
            [
                {"id": 10, "name": "Gameplay"},
                {"id": 11, "name": "1920x1080", "group": {"id": 5, "name": "Resolution"}},
            ],
        )
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 2)

    def test_game_tags_endpoint_includes_grouped_tags(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(
            get_value=_game(),
            execute_results=[[_tag(), _tag(tag_id=11, name="1920x1080", group=group)]],
            scalar_values=[2],
        )

        with patch.object(self.api_association_getter.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/games/1/tags",
                params={"page": 0, "page_size": 20},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["items"],
            [
                {"id": 10, "name": "Gameplay"},
                {"id": 11, "name": "1920x1080", "group": {"id": 5, "name": "Resolution"}},
            ],
        )
        self.assertEqual(
            body["pagination"],
            {
                "page": 0,
                "page_size": 20,
                "offset": 0,
                "total": 2,
                "has_next": False,
                "has_previous": False,
            },
        )
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)

    def test_game_tags_endpoint_filters_by_name_and_ids(self) -> None:
        group = types.SimpleNamespace(id=5, name="Resolution")
        session = _RecordingSession(
            get_value=_game(),
            execute_results=[[_tag(tag_id=11, name="1920x1080", group=group)]],
            scalar_values=[1],
        )

        with patch.object(self.api_association_getter.catalog, "AsyncSessionLocal", return_value=session):
            response = self.client.get(
                f"{self.main_url}/games/1/tags",
                params={"page": 0, "page_size": 20, "name": "1920", "ids": [11, 12]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["items"],
            [
                {"id": 11, "name": "1920x1080", "group": {"id": 5, "name": "Resolution"}},
            ],
        )
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        count_sql = str(session.scalar_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        list_sql = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("lower(tags.name) like lower('%1920%')", count_sql)
        self.assertIn("1920", count_sql)
        self.assertIn("in (11, 12)", count_sql)
        self.assertIn("lower(tags.name) like lower('%1920%')", list_sql)
        self.assertIn("1920", list_sql)
        self.assertIn("in (11, 12)", list_sql)

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

    def test_resources_list_supports_modpack_owner_type(self) -> None:
        session = _RecordingSession(
            rows=[_resource(owner_type="modpacks", owner_id=17, sort_order=5)],
            scalar_values=[1],
        )
        access_modpacks = AsyncMock(return_value=[17])

        with (
            patch.object(self.api_resource.catalog, "AsyncSessionLocal", return_value=session),
            patch.object(self.api_resource.tools, "access_modpacks", access_modpacks),
        ):
            response = self.client.get(
                f"{self.main_url}/resources",
                params={
                    "owner_type": "modpacks",
                    "owner_ids": [17],
                    "page": 0,
                    "page_size": 20,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"][0]["owner_type"], "modpacks")
        self.assertEqual(body["items"][0]["sort_order"], 5)
        self.assertEqual(len(session.scalar_statements), 1)
        self.assertEqual(len(session.execute_statements), 1)
        self.assertTrue(access_modpacks.await_args.kwargs["check_mode"])

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
        self.assertEqual(
            include_enum("/modpacks", "get"),
            {"short_description", "description", "dates", "game", "tags", "authors", "resources"},
        )
        self.assertEqual(include_enum("/tags", "get"), {"orphaned", "group", "games"})
        self.assertEqual(include_enum("/tags/orphaned", "get"), {"orphaned", "group", "games"})
        self.assertEqual(include_enum("/tags/{tag_id}", "get"), {"orphaned", "group", "games"})
        scope_enum = lambda path, method: next(
            parameter
            for parameter in schema["paths"][path][method]["parameters"]
            if parameter["name"] == "scope"
        )["schema"]["enum"]
        self.assertEqual(scope_enum("/mods", "get"), ["outgoing", "incoming", "all"])
        self.assertEqual(scope_enum("/mods/{mod_id}", "get"), ["outgoing", "incoming", "all"])
        self.assertEqual(scope_enum("/mods/{mod_id}/conflicts", "get"), ["outgoing", "incoming", "all"])
        self.assertIn("adult", parameter_names("/mods", "get"))
        self.assertIn("show_not_public", parameter_names("/mods", "get"))
        self.assertIn("scope", parameter_names("/mods", "get"))
        self.assertIn("scope", parameter_names("/mods/{mod_id}", "get"))
        self.assertIn("scope", parameter_names("/mods/{mod_id}/conflicts", "get"))
        self.assertIn("show_not_public", parameter_names("/mods/feed", "get"))
        self.assertIn("author_id", parameter_names("/mods/feed", "get"))
        self.assertIn("user", parameter_names("/mods/feed", "get"))
        self.assertIn("include", parameter_names("/tags", "get"))
        self.assertIn("page", parameter_names("/games/{game_id}/tags", "get"))
        self.assertIn("page_size", parameter_names("/games/{game_id}/tags", "get"))
        self.assertIn("name", parameter_names("/games/{game_id}/tags", "get"))
        self.assertIn("ids", parameter_names("/games/{game_id}/tags", "get"))
        self.assertEqual(
            parameter_names("/tags/orphaned", "get"),
            {"page", "page_size", "name", "ids", "include"},
        )
        self.assertIn("include", parameter_names("/tags/{tag_id}", "get"))
        self.assertEqual(
            parameter_names("/tag-groups/orphaned", "get"),
            {"page", "page_size", "name", "ids"},
        )
        self.assertIn("game_id", parameter_names("/tag-groups", "get"))
        self.assertIn("game_id", parameter_names("/tag-groups/{group_id}/tags", "get"))
        self.assertIn("ids", parameter_names("/tag-groups/{group_id}/tags", "get"))
        self.assertIn("sort", parameter_names("/resources", "get"))
        modpack_params = parameter_names("/modpacks", "get")
        self.assertIn("ids", modpack_params)
        self.assertIn("tags", modpack_params)
        self.assertIn("excluded_tags", modpack_params)
        self.assertIn("sources", modpack_params)
        self.assertIn("source_ids", modpack_params)
        self.assertIn("game_id", modpack_params)
        self.assertIn("include", modpack_params)
        self.assertNotIn("source", modpack_params)
        modpack_adult = next(
            parameter
            for parameter in schema["paths"]["/modpacks"]["get"]["parameters"]
            if parameter["name"] == "adult"
        )
        self.assertEqual(modpack_adult["schema"]["type"], "integer")
        self.assertEqual(modpack_adult["schema"]["minimum"], -1)
        self.assertEqual(modpack_adult["schema"]["maximum"], 1)
        self.assertEqual(modpack_adult["schema"]["default"], -1)
        self.assertEqual(modpack_adult["description"], "Adult content filter: -1 any, 0 false, 1 true.")
        mod_read = schema["components"]["schemas"]["ModRead"]
        self.assertIn("adult", mod_read["properties"])
        self.assertIn("adult", mod_read["required"])
        self.assertEqual(mod_read["properties"]["adult"]["type"], "boolean")
        self.assertIn("rating", mod_read["properties"])
        self.assertIn("votes_count", mod_read["properties"])
        self.assertIn("current_vote", mod_read["properties"])
        self.assertIn("git_url", mod_read["properties"])
        self.assertIn("/modpacks/{modpack_id}/mods", schema["paths"])
        self.assertIn("get", schema["paths"]["/modpacks/{modpack_id}/mods"])
        self.assertIn("put", schema["paths"]["/modpacks/{modpack_id}/mods"])
        self.assertIn("ModpackModRead", schema["components"]["schemas"])
        self.assertIn("ModpackModsRead", schema["components"]["schemas"])
        self.assertIn("ModpackModUpsert", schema["components"]["schemas"])
        self.assertIn("ModpackModsUpsert", schema["components"]["schemas"])
        self.assertEqual(
            set(schema["components"]["schemas"]["ModpackModRead"]["properties"]),
            {"mod_id", "sort_order", "auto_added"},
        )
        self.assertEqual(
            set(schema["components"]["schemas"]["ModpackModsRead"]["properties"]),
            {"modpack_id", "items"},
        )
        self.assertEqual(
            set(schema["components"]["schemas"]["ModpackModUpsert"]["properties"]),
            {"mod_id", "auto_added"},
        )
        self.assertEqual(
            set(schema["components"]["schemas"]["ModpackModsUpsert"]["properties"]),
            {"items"},
        )
        build_node_read = schema["components"]["schemas"]["ModBuildNodeRead"]
        self.assertEqual(
            set(build_node_read["properties"]),
            {"mod_id", "mod_name", "selected"},
        )
        build_edge_read = schema["components"]["schemas"]["ModBuildEdgeRead"]
        self.assertEqual(
            set(build_edge_read["properties"]),
            {"source_mod_id", "target_mod_id"},
        )
        self.assertIn("/mods/{mod_id}/rating", schema["paths"])
        self.assertIn("/mods/build/conflicts", schema["paths"])
        self.assertIn("/mods/build/dependencies/missing", schema["paths"])
        self.assertIn("/tags", schema["paths"])
        self.assertIn("/tags/orphaned", schema["paths"])
        self.assertIn("/tags/{tag_id}", schema["paths"])
        self.assertIn("/tag-groups", schema["paths"])
        self.assertIn("/tag-groups/orphaned", schema["paths"])
        self.assertIn("/tag-groups/{group_id}", schema["paths"])
        self.assertIn("/tag-groups/{group_id}/tags", schema["paths"])
        self.assertIn("/modpacks", schema["paths"])
        self.assertIn("/modpacks/{modpack_id}", schema["paths"])
        self.assertIn("/modpacks/{modpack_id}/rating", schema["paths"])
        self.assertIn("/modpacks/{modpack_id}/authors/{author_id}", schema["paths"])
        self.assertIn("/modpacks/{modpack_id}/tags", schema["paths"])
        self.assertIn("/modpacks/{modpack_id}/tags/{tag_id}", schema["paths"])
        self.assertIn("/profiles/{user_id}/rating", schema["paths"])
        self.assertIn("/profiles/{user_id}/rating/history", schema["paths"])
        modpack_read = schema["components"]["schemas"]["ModpackRead"]
        self.assertIn("adult", modpack_read["properties"])
        self.assertIn("rating", modpack_read["properties"])
        self.assertIn("votes_count", modpack_read["properties"])
        self.assertIn("current_vote", modpack_read["properties"])
        self.assertIn("game", modpack_read["properties"])
        self.assertIn("authors", modpack_read["properties"])
        self.assertIn("tags", modpack_read["properties"])
        self.assertIn("resources", modpack_read["properties"])
        self.assertNotIn("condition", modpack_read["properties"])
        self.assertNotIn("git_url", modpack_read["properties"])
        tag_read = schema["components"]["schemas"]["TagRead"]
        self.assertIn("group", tag_read["properties"])
        self.assertIn("orphaned", tag_read["properties"])
        self.assertIn("games", tag_read["properties"])
        games_schema = tag_read["properties"]["games"]
        if "items" in games_schema:
            self.assertEqual(games_schema["items"]["type"], "integer")
        else:
            array_schema = next(item for item in games_schema["anyOf"] if item.get("type") == "array")
            self.assertEqual(array_schema["items"]["type"], "integer")
        mod_rating_read = schema["components"]["schemas"]["ModRatingRead"]
        self.assertIn("rating", mod_rating_read["properties"])
        self.assertIn("votes_count", mod_rating_read["properties"])
        self.assertIn("mod_id", mod_rating_read["properties"])
        modpack_rating_read = schema["components"]["schemas"]["ModpackRatingRead"]
        self.assertIn("rating", modpack_rating_read["properties"])
        self.assertIn("votes_count", modpack_rating_read["properties"])
        self.assertIn("modpack_id", modpack_rating_read["properties"])
        profile_rating_read = schema["components"]["schemas"]["ProfileRatingRead"]
        self.assertIn("rating", profile_rating_read["properties"])
        self.assertIn("votes_count", profile_rating_read["properties"])
        self.assertIn("profile_id", profile_rating_read["properties"])
        profile_general_read = schema["components"]["schemas"]["ProfileGeneralRead"]
        self.assertIn("rating", profile_general_read["properties"])
        self.assertIn("votes_count", profile_general_read["properties"])
        self.assertIn("rating", profile_general_read["required"])
        self.assertIn("votes_count", profile_general_read["required"])
        self.assertEqual(profile_general_read["properties"]["rating"]["type"], "integer")
        self.assertEqual(profile_general_read["properties"]["votes_count"]["type"], "integer")
        self.assertNotIn("reputation", profile_general_read["properties"])
        resource_read = schema["components"]["schemas"]["ResourceRead"]
        self.assertIn("sort_order", resource_read["properties"])
        self.assertIn("sort_order", resource_read["required"])
        resource_create = schema["components"]["schemas"]["ResourceCreate"]
        self.assertIn("modpacks", resource_create["properties"]["owner_type"]["enum"])
        tag_read = schema["components"]["schemas"]["TagRead"]
        self.assertIn("group", tag_read["properties"])
        tag_create = schema["components"]["schemas"]["TagCreate"]
        self.assertIn("group_id", tag_create["properties"])
        tag_patch = schema["components"]["schemas"]["TagPatch"]
        self.assertIn("group_id", tag_patch["properties"])
        self.assertIn("TagGroupRead", schema["components"]["schemas"])
        self.assertIn("TagGroupListResponse", schema["components"]["schemas"])
        mod_feed_read = schema["components"]["schemas"]["ModFeedRead"]
        self.assertIn("tag_groups", mod_feed_read["properties"])
        mod_params = parameter_names("/mods", "get")
        self.assertIn("excluded_conflicts", mod_params)
        dependencies_param = next(
            parameter
            for parameter in schema["paths"]["/mods"]["get"]["parameters"]
            if parameter["name"] == "dependencies"
        )
        self.assertEqual(dependencies_param["schema"]["items"]["type"], "string")
        build_conflicts_param = next(
            parameter
            for parameter in schema["paths"]["/mods/build/conflicts"]["get"]["parameters"]
            if parameter["name"] == "mods_ids"
        )
        self.assertEqual(build_conflicts_param["schema"]["items"]["type"], "integer")
        build_missing_param = next(
            parameter
            for parameter in schema["paths"]["/mods/build/dependencies/missing"]["get"]["parameters"]
            if parameter["name"] == "mods_ids"
        )
        self.assertEqual(build_missing_param["schema"]["items"]["type"], "integer")
        excluded_dependencies_param = next(
            parameter
            for parameter in schema["paths"]["/mods"]["get"]["parameters"]
            if parameter["name"] == "excluded_dependencies"
        )
        self.assertEqual(excluded_dependencies_param["schema"]["items"]["type"], "string")
        build_conflict_graph_read = schema["components"]["schemas"]["ModBuildConflictGraphRead"]
        self.assertEqual(
            build_conflict_graph_read["properties"]["nodes"]["items"]["$ref"],
            "#/components/schemas/ModBuildNodeRead",
        )
        self.assertEqual(
            build_conflict_graph_read["properties"]["edges"]["items"]["$ref"],
            "#/components/schemas/ModBuildEdgeRead",
        )
        build_dependency_graph_read = schema["components"]["schemas"]["ModBuildDependencyGraphRead"]
        self.assertEqual(
            build_dependency_graph_read["properties"]["nodes"]["items"]["$ref"],
            "#/components/schemas/ModBuildNodeRead",
        )
        self.assertEqual(
            build_dependency_graph_read["properties"]["edges"]["items"]["$ref"],
            "#/components/schemas/ModBuildEdgeRead",
        )
        self.assertEqual(
            include_enum("/profiles/{user_id}", "get"),
            {"general", "rights", "private"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
