from __future__ import annotations

import datetime
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
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


from open_workshop_manager import standarts
from open_workshop_manager.mods import api_mod
from open_workshop_manager.modpacks import api_modpack
from open_workshop_manager.social import api_profile
from open_workshop_manager.sql_logic import sql_account, sql_catalog


class _DummyResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_DummyResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self.first()


class _RatingSession:
    def __init__(
        self,
        *,
        get_map: dict[type, object] | None = None,
        scalar_results: list[object | None] | None = None,
        execute_results: list[list[object]] | None = None,
    ) -> None:
        self.get_map = dict(get_map or {})
        self.scalar_results = list(scalar_results or [])
        self.execute_results = list(execute_results or [])
        self.execute_statements: list[object] = []
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commit_count = 0

    async def __aenter__(self) -> "_RatingSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object | None:
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def execute(self, stmt, *args, **kwargs) -> _DummyResult:
        self.execute_statements.append(stmt)
        if isinstance(stmt, (Insert, Update, Delete)):
            return _DummyResult([])
        if self.execute_results:
            return _DummyResult(self.execute_results.pop(0))
        return _DummyResult([])

    async def get(self, entity, ident) -> object | None:
        target = self.get_map.get(entity)
        if isinstance(target, dict):
            return target.get(int(ident))
        return target if target is not None and getattr(target, "id", None) == ident else None

    def add(self, obj) -> None:
        self.added.append(obj)
        self.get_map[type(obj)] = obj

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commit_count += 1


class ReputationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(api_mod.router)
        app.include_router(api_modpack.router)
        app.include_router(api_profile.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_mod_rating_updates_mod_and_author_reputation_by_tenth_point(self) -> None:
        mod = SimpleNamespace(id=7, name="Cool Mod", rating=0)
        author = SimpleNamespace(id=11, username="Author", reputation=4.0)
        session = _RatingSession(
            get_map={sql_catalog.Mod: mod},
            scalar_results=[None],
            execute_results=[[author]],
        )
        vote_access = SimpleNamespace(
            authenticated=True,
            owner_id=99,
            vote_for_reputation=SimpleNamespace(value=True, reason="ok", reason_code="allowed"),
        )
        publish_event = AsyncMock(return_value=None)

        with (
            patch.object(api_mod.tools, "access_vote_for_reputation", AsyncMock(return_value=vote_access)),
            patch.object(api_mod.tools, "access_mods", AsyncMock(return_value=True)),
            patch.object(api_mod.account, "AsyncSessionLocal", return_value=session),
            patch.object(api_mod.mod_events, "publish_mod_event", publish_event),
        ):
            response = self.client.put("/mods/7/rating", json={"value": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mod_id": 7, "rating": 1})
        self.assertEqual(mod.rating, 1)
        self.assertEqual(author.reputation, 4.1)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(len(session.added), 2)
        self.assertEqual(getattr(session.added[-1], "target_type", None), "mod")
        self.assertEqual(getattr(session.added[-1], "mod_delta", None), 1)
        self.assertEqual(getattr(session.added[-1], "reputation_delta", None), 0.1)
        publish_event.assert_awaited_once()
        self.assertEqual(publish_event.await_args.args[0], api_mod.mod_events.MOD_EVENT_RATED)
        self.assertEqual(publish_event.await_args.args[1], 7)
        self.assertEqual(publish_event.await_args.kwargs["extra"]["vote_value"], 1)
        self.assertEqual(publish_event.await_args.kwargs["extra"]["rating"], 1)

    def test_mod_rating_updates_author_reputation_on_second_vote(self) -> None:
        mod = SimpleNamespace(id=7, name="Cool Mod", rating=9)
        author = SimpleNamespace(id=11, username="Author", reputation=4.9)
        session = _RatingSession(
            get_map={sql_catalog.Mod: mod},
            scalar_results=[None],
            execute_results=[[author]],
        )
        vote_access = SimpleNamespace(
            authenticated=True,
            owner_id=99,
            vote_for_reputation=SimpleNamespace(value=True, reason="ok", reason_code="allowed"),
        )
        publish_event = AsyncMock(return_value=None)

        with (
            patch.object(api_mod.tools, "access_vote_for_reputation", AsyncMock(return_value=vote_access)),
            patch.object(api_mod.tools, "access_mods", AsyncMock(return_value=True)),
            patch.object(api_mod.account, "AsyncSessionLocal", return_value=session),
            patch.object(api_mod.mod_events, "publish_mod_event", publish_event),
        ):
            response = self.client.put("/mods/7/rating", json={"value": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mod_id": 7, "rating": 10})
        self.assertEqual(mod.rating, 10)
        self.assertEqual(author.reputation, 5.0)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(len(session.added), 2)
        self.assertEqual(getattr(session.added[-1], "target_type", None), "mod")
        self.assertEqual(getattr(session.added[-1], "mod_delta", None), 1)
        self.assertEqual(getattr(session.added[-1], "reputation_delta", None), 0.1)
        publish_event.assert_awaited_once()
        self.assertEqual(publish_event.await_args.kwargs["extra"]["rating"], 10)

    def test_modpack_rating_updates_modpack_and_author_reputation_by_tenth_point(self) -> None:
        modpack = SimpleNamespace(id=17, name="Cool Pack", rating=0)
        author = SimpleNamespace(id=21, username="Pack Author", reputation=1.5)
        session = _RatingSession(
            get_map={sql_catalog.Modpack: modpack},
            scalar_results=[None],
            execute_results=[[author]],
        )
        vote_access = SimpleNamespace(
            authenticated=True,
            owner_id=77,
            vote_for_reputation=SimpleNamespace(value=True, reason="ok", reason_code="allowed"),
        )

        with (
            patch.object(api_modpack.tools, "access_vote_for_reputation", AsyncMock(return_value=vote_access)),
            patch.object(api_modpack.tools, "access_modpacks", AsyncMock(return_value=True)),
            patch.object(api_modpack.account, "AsyncSessionLocal", return_value=session),
        ):
            response = self.client.put("/modpacks/17/rating", json={"value": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"modpack_id": 17, "rating": 1})
        self.assertEqual(modpack.rating, 1)
        self.assertEqual(author.reputation, 1.6)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(len(session.added), 2)
        self.assertEqual(getattr(session.added[-1], "target_type", None), "modpack")
        self.assertEqual(getattr(session.added[-1], "mod_delta", None), 1)
        self.assertEqual(getattr(session.added[-1], "reputation_delta", None), 0.1)

    def test_get_modpack_includes_current_vote_state_for_authenticated_user(self) -> None:
        modpack = SimpleNamespace(
            id=17,
            name="Cool Pack",
            short_description="Short",
            description="Long",
            source="local",
            source_id=None,
            git_url=None,
            game=None,
            public=0,
            adult=False,
            condition=0,
            downloads=0,
            rating=13,
            date_creation=None,
            date_edit=None,
        )
        vote_history_row = SimpleNamespace(
            id=1,
            voter_id=42,
            target_type="modpack",
            target_id=17,
            target_name="Cool Pack",
            previous_value=0,
            value=-1,
            reputation_delta=-0.1,
            mod_delta=-1,
            created_at=datetime.datetime(2026, 5, 3, 12, 0, 0),
        )
        catalog_session = _RatingSession(
            get_map={sql_catalog.Modpack: modpack},
            execute_results=[[(17, 21, True)]],
        )
        vote_session = _RatingSession(scalar_results=[vote_history_row])
        access_state = SimpleNamespace(authenticated=True, owner_id=42)

        with (
            patch.object(api_modpack.account, "check_access", AsyncMock(return_value=access_state)),
            patch.object(api_modpack.catalog, "AsyncSessionLocal", return_value=catalog_session),
            patch.object(api_modpack.account, "AsyncSessionLocal", return_value=vote_session),
        ):
            response = self.client.get("/modpacks/17")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], 17)
        self.assertEqual(body["current_vote"], -1)
        self.assertEqual(body["authors"], {"21": {"owner": True}})

    def test_get_modpack_mods_returns_stored_mod_list(self) -> None:
        modpack = SimpleNamespace(
            id=17,
            name="Cool Pack",
            short_description="Short",
            description="Long",
            source="local",
            source_id=None,
            game=None,
            public=0,
            adult=False,
            rating=13,
            downloads=0,
            date_creation=None,
            date_edit=None,
        )
        catalog_session = _RatingSession(
            get_map={sql_catalog.Modpack: modpack},
            execute_results=[[(17, 11, 0, False), (17, 7, 1, True)]],
        )

        with patch.object(api_modpack.catalog, "AsyncSessionLocal", return_value=catalog_session):
            response = self.client.get("/modpacks/17/mods")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["modpack_id"], 17)
        self.assertEqual(body["items"], [
            {"mod_id": 11, "sort_order": 0, "auto_added": False},
            {"mod_id": 7, "sort_order": 1, "auto_added": True},
        ])

    def test_put_modpack_mods_persists_mod_list_and_auto_added_flags(self) -> None:
        modpack = SimpleNamespace(
            id=17,
            name="Cool Pack",
            short_description="Short",
            description="Long",
            source="local",
            source_id=None,
            game=None,
            public=0,
            adult=False,
            rating=13,
            downloads=0,
            date_creation=None,
            date_edit=None,
        )
        catalog_session = _RatingSession(
            get_map={sql_catalog.Modpack: modpack},
            execute_results=[
                [11, 7],
                [(17, 7, 0, False), (17, 11, 1, True)],
            ],
        )
        access_result = SimpleNamespace(
            authenticated=True,
            edit=SimpleNamespace(value=True, reason="ok", reason_code="allowed"),
        )

        with (
            patch.object(api_modpack.tools, "access_modpacks", AsyncMock(return_value=access_result)),
            patch.object(api_modpack.tools, "access_mods", AsyncMock(return_value=True)),
            patch.object(api_modpack.catalog, "AsyncSessionLocal", return_value=catalog_session),
        ):
            response = self.client.put(
                "/modpacks/17/mods",
                json={
                    "items": [
                        {"mod_id": 7, "auto_added": False},
                        {"mod_id": 11, "auto_added": True},
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["modpack_id"], 17)
        self.assertEqual(body["items"], [
            {"mod_id": 7, "sort_order": 0, "auto_added": False},
            {"mod_id": 11, "sort_order": 1, "auto_added": True},
        ])
        self.assertEqual(catalog_session.commit_count, 1)
        self.assertEqual(access_result.authenticated, True)

    def test_put_modpack_author_requires_author_management_right(self) -> None:
        access_result = SimpleNamespace(
            authenticated=True,
            edit=SimpleNamespace(
                authors=SimpleNamespace(
                    value=False,
                    reason="no author access",
                    reason_code="forbidden",
                )
            ),
        )
        access_mock = AsyncMock(return_value=access_result)

        with patch.object(api_modpack.tools, "access_modpack_action", access_mock):
            response = self.client.put("/modpacks/17/authors/21", json={"owner": True})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(access_mock.await_args.kwargs["author_id"], 21)
        self.assertTrue(access_mock.await_args.kwargs["mode"])

    def test_delete_modpack_author_requires_author_management_right(self) -> None:
        access_result = SimpleNamespace(
            authenticated=True,
            edit=SimpleNamespace(
                authors=SimpleNamespace(
                    value=False,
                    reason="no author access",
                    reason_code="forbidden",
                )
            ),
        )
        access_mock = AsyncMock(return_value=access_result)

        with patch.object(api_modpack.tools, "access_modpack_action", access_mock):
            response = self.client.delete("/modpacks/17/authors/21")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(access_mock.await_args.kwargs["author_id"], 21)
        self.assertFalse(access_mock.await_args.kwargs["mode"])

    def test_delete_modpack_requires_delete_right(self) -> None:
        access_result = SimpleNamespace(
            authenticated=True,
            delete=SimpleNamespace(
                value=False,
                reason="no delete access",
                reason_code="forbidden",
            ),
        )
        access_mock = AsyncMock(return_value=access_result)

        with patch.object(api_modpack.tools, "access_modpack_action", access_mock):
            response = self.client.delete("/modpacks/17")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(access_mock.await_args.kwargs["modpack_id"], 17)
        self.assertNotIn("author_id", access_mock.await_args.kwargs)

    def test_get_mod_includes_current_vote_state_for_authenticated_user(self) -> None:
        mod = SimpleNamespace(
            id=7,
            name="Cool Mod",
            short_description="Short",
            description="Long",
            source="local",
            source_id=None,
            git_url=None,
            game=None,
            public=0,
            adult=False,
            condition=0,
            downloads=0,
            rating=13,
            size=0,
            size_unpacked=None,
            date_creation=None,
            date_update_file=None,
            date_edit=None,
        )
        vote_history_row = SimpleNamespace(
            id=1,
            voter_id=42,
            target_type="mod",
            target_id=7,
            target_name="Cool Mod",
            previous_value=0,
            value=-1,
            reputation_delta=-0.1,
            mod_delta=-1,
            created_at=datetime.datetime(2026, 5, 3, 12, 0, 0),
        )
        catalog_session = _RatingSession(get_map={sql_catalog.Mod: mod})
        vote_session = _RatingSession(scalar_results=[vote_history_row])
        access_state = SimpleNamespace(authenticated=True, owner_id=42)

        with (
            patch.object(api_mod.account, "check_access", AsyncMock(return_value=access_state)),
            patch.object(api_mod.catalog, "AsyncSessionLocal", return_value=catalog_session),
            patch.object(api_mod.account, "AsyncSessionLocal", return_value=vote_session),
        ):
            response = self.client.get("/mods/7")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], 7)
        self.assertEqual(body["rating"], 13)
        self.assertEqual(body["current_vote"], -1)

    def test_profile_rating_updates_reputation(self) -> None:
        profile = SimpleNamespace(id=7, username="User", reputation=12.0)
        session = _RatingSession(
            get_map={sql_account.Account: profile},
            scalar_results=[None],
        )
        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=42,
            vote_for_reputation=SimpleNamespace(value=True, reason="ok", reason_code="allowed"),
            info=SimpleNamespace(meta=SimpleNamespace(value=True, reason="ok", reason_code="self")),
        )

        with (
            patch.object(api_profile.tools, "access_profile", AsyncMock(return_value=access_result)),
            patch.object(api_profile.account, "AsyncSessionLocal", return_value=session),
        ):
            response = self.client.put("/profiles/7/rating", json={"value": -1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"profile_id": 7, "reputation": 11.0})
        self.assertEqual(profile.reputation, 11.0)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(len(session.added), 2)
        self.assertEqual(getattr(session.added[-1], "target_type", None), "profile")
        self.assertEqual(getattr(session.added[-1], "reputation_delta", None), -1.0)

    def test_profile_rating_history_returns_items(self) -> None:
        profile = SimpleNamespace(id=7, username="User", reputation=11.0)
        history_row = SimpleNamespace(
            id=1,
            voter_id=7,
            target_type="mod",
            target_id=77,
            target_name="Cool Mod",
            previous_value=0,
            value=1,
            reputation_delta=0.1,
            mod_delta=1,
            created_at=datetime.datetime(2026, 5, 3, 12, 0, 0),
        )
        session = _RatingSession(
            get_map={sql_account.Account: profile},
            execute_results=[[history_row]],
        )
        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=7,
            info=SimpleNamespace(meta=SimpleNamespace(value=True, reason="ok", reason_code="self")),
        )

        with (
            patch.object(api_profile.tools, "access_profile", AsyncMock(return_value=access_result)),
            patch.object(api_profile.account, "AsyncSessionLocal", return_value=session),
        ):
            response = self.client.get("/profiles/7/rating/history")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["items"][0]["target_name"], "Cool Mod")
        self.assertEqual(body["items"][0]["mod_delta"], 1)
        self.assertEqual(body["items"][0]["reputation_delta"], 0.1)
        self.assertEqual(session.commit_count, 0)

    def test_profile_rating_history_returns_latest_state_per_target(self) -> None:
        profile = SimpleNamespace(id=7, username="User", reputation=11.0)
        latest_mod_row = SimpleNamespace(
            id=4,
            voter_id=7,
            target_type="mod",
            target_id=3,
            target_name="Harmony",
            previous_value=1,
            value=0,
            reputation_delta=-1.0,
            mod_delta=-10,
            created_at=datetime.datetime(2026, 5, 3, 16, 15, 41),
        )
        older_mod_row = SimpleNamespace(
            id=2,
            voter_id=7,
            target_type="mod",
            target_id=3,
            target_name="Harmony",
            previous_value=-1,
            value=1,
            reputation_delta=2.0,
            mod_delta=20,
            created_at=datetime.datetime(2026, 5, 3, 16, 12, 16),
        )
        profile_row = SimpleNamespace(
            id=5,
            voter_id=7,
            target_type="profile",
            target_id=8,
            target_name="User",
            previous_value=0,
            value=1,
            reputation_delta=1.0,
            mod_delta=0,
            created_at=datetime.datetime(2026, 5, 3, 16, 10, 0),
        )
        session = _RatingSession(
            get_map={sql_account.Account: profile},
            execute_results=[[latest_mod_row, older_mod_row, profile_row]],
        )
        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=7,
            info=SimpleNamespace(meta=SimpleNamespace(value=True, reason="ok", reason_code="self")),
        )

        with (
            patch.object(api_profile.tools, "access_profile", AsyncMock(return_value=access_result)),
            patch.object(api_profile.account, "AsyncSessionLocal", return_value=session),
        ):
            response = self.client.get("/profiles/7/rating/history")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["id"], 4)
        self.assertEqual(body["items"][0]["value"], 0)
        self.assertEqual(body["items"][1]["target_type"], "profile")
        self.assertEqual(body["items"][1]["id"], 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
