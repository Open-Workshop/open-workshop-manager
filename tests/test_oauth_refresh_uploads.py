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
from open_workshop_manager.api_models import UploadRead
from open_workshop_manager.social import api_session
from open_workshop_manager.sql_logic import sql_account, sql_catalog
from open_workshop_manager.uploads import api_uploads


class _DummyResult:
    def __init__(self, first_value: object | None = None) -> None:
        self._first_value = first_value

    def first(self) -> object | None:
        return self._first_value

    def scalar_one_or_none(self) -> object | None:
        return self._first_value

    def scalars(self) -> "_DummyResult":
        return self

    def all(self) -> list[object]:
        if self._first_value is None:
            return []
        if isinstance(self._first_value, list):
            return self._first_value
        return [self._first_value]


class _MutableSession:
    def __init__(
        self,
        *,
        scalar_values: list[object | None] | None = None,
        execute_first_values: list[object | None] | None = None,
        get_map: dict[type, object] | None = None,
        next_id: int = 1,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.execute_first_values = list(execute_first_values or [])
        self.get_map = dict(get_map or {})
        self.next_id = next_id
        self.added: list[object] = []
        self.execute_statements: list[object] = []
        self.commit_count = 0
        self.flush_count = 0

    async def __aenter__(self) -> "_MutableSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def scalar(self, stmt) -> object | None:
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None

    def _apply_update(self, stmt: Update) -> None:
        table_name = stmt.table.name
        params = stmt.compile().params

        if table_name == sql_catalog.Game.__tablename__:
            game = self.get_map.get(sql_catalog.Game)
            if game is not None:
                game.mods_count = int(getattr(game, "mods_count", 0) or 0) + 1
            return

        if table_name == sql_catalog.Mod.__tablename__:
            target = self.get_map.get(sql_catalog.Mod)
        elif table_name == sql_catalog.Resource.__tablename__:
            target = self.get_map.get(sql_catalog.Resource)
        elif table_name == sql_account.Account.__tablename__:
            target = self.get_map.get(sql_account.Account)
        elif table_name == sql_account.Session.__tablename__:
            target = self.get_map.get(sql_account.Session)
        else:
            target = None

        if target is None:
            return

        for key, value in params.items():
            if key.startswith("id_"):
                continue
            if hasattr(target, key):
                setattr(target, key, value)

    async def execute(self, stmt) -> _DummyResult:
        self.execute_statements.append(stmt)
        if isinstance(stmt, Update):
            self._apply_update(stmt)
        elif isinstance(stmt, Delete):
            pass
        first_value = self.execute_first_values.pop(0) if self.execute_first_values else None
        return _DummyResult(first_value)

    async def get(self, entity, ident) -> object | None:
        target = self.get_map.get(entity)
        if target is None:
            return None
        if ident is None:
            return target
        return target if getattr(target, "id", None) == ident else None

    def add(self, obj) -> None:
        self.added.append(obj)
        self.get_map[type(obj)] = obj

    async def flush(self) -> None:
        self.flush_count += 1
        if not self.added:
            return
        obj = self.added[-1]
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", self.next_id)
            self.next_id += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _DummyAiohttpResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_payload: object | None = None,
        read_payload: bytes = b"",
    ) -> None:
        self.status = status
        self._json_payload = json_payload
        self._read_payload = read_payload

    async def __aenter__(self) -> "_DummyAiohttpResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self) -> object:
        return self._json_payload

    async def read(self) -> bytes:
        return self._read_payload


class _DummyAiohttpSession:
    def __init__(self, token_payload: object, userinfo_payload: object, picture_payload: bytes) -> None:
        self.calls: list[tuple[str, str, object | None]] = []
        self._token_response = _DummyAiohttpResponse(status=200, json_payload=token_payload)
        self._userinfo_response = _DummyAiohttpResponse(status=200, json_payload=userinfo_payload)
        self._picture_response = _DummyAiohttpResponse(status=200, read_payload=picture_payload)

    async def __aenter__(self) -> "_DummyAiohttpSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, data=None) -> _DummyAiohttpResponse:
        self.calls.append(("POST", url, data))
        return self._token_response

    def get(self, url: str, headers=None) -> _DummyAiohttpResponse:
        self.calls.append(("GET", url, headers))
        if "userinfo" in url:
            return self._userinfo_response
        return self._picture_response


class OAuthRefreshUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        standarts.install_exception_handlers(app)
        app.include_router(api_session.router)
        app.include_router(api_uploads.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def setUp(self) -> None:
        self.client.cookies.clear()
        api_uploads.UPLOAD_JOBS.clear()

    def test_refresh_session_rotates_tokens_and_sets_cookies(self) -> None:
        session_row = SimpleNamespace(
            id=1,
            owner_id=42,
            access_token="old-access",
            refresh_token="old-refresh",
            broken=None,
            login_method="password",
            last_request_date=None,
            end_date_access=datetime.datetime(2026, 4, 27, 12, 40, 0),
            end_date_refresh=datetime.datetime(2026, 6, 27, 12, 0, 0),
        )
        account_row = SimpleNamespace(id=42)
        session = _MutableSession(
            execute_first_values=[session_row],
            get_map={sql_account.Account: account_row},
        )

        with patch.object(api_session.account, "AsyncSessionLocal", return_value=session), patch.object(
            api_session.bcrypt,
            "hashpw",
            side_effect=[b"new-access-token", b"new-refresh-token"],
        ):
            response = self.client.post(
                "/sessions/current/refresh",
                cookies={
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access_expires_at", body)
        self.assertIn("refresh_expires_at", body)
        self.assertEqual(session_row.access_token, "new-access-token")
        self.assertEqual(session_row.refresh_token, "new-refresh-token")
        self.assertEqual(session_row.owner_id, 42)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(response.cookies.get("accessToken"), "new-access-token")
        self.assertEqual(response.cookies.get("refreshToken"), "new-refresh-token")

    def test_google_oauth_callback_creates_account_and_uploads_avatar(self) -> None:
        new_account = SimpleNamespace(
            id=None,
            google_id=None,
            username="",
            avatar_url="",
            comments=0,
            author_mods=0,
            registration_date=None,
            reputation=0,
        )
        session = _MutableSession(next_id=123)

        dummy_aiohttp = _DummyAiohttpSession(
            token_payload={"access_token": "google-access"},
            userinfo_payload={
                "id": "google-user-id",
                "picture": "https://example.com/avatar.png",
            },
            picture_payload=b"avatar-bytes",
        )

        with patch.object(
            api_session,
            "_google_token_data",
            return_value={
                "client_id": "client-id",
                "client_secret": "client-secret",
                "redirect_uri": "https://example.com/oauth/google/callback",
                "grant_type": "authorization_code",
            },
        ), patch.object(api_session.account, "check_access", AsyncMock(return_value=False)), patch.object(
            api_session.account,
            "AsyncSessionLocal",
            return_value=session,
        ), patch.object(
            api_session.account.bcrypt,
            "hashpw",
            side_effect=[b"google-access-token", b"google-refresh-token"],
        ), patch.object(
            api_session.aiohttp,
            "ClientSession",
            return_value=dummy_aiohttp,
        ), patch.object(
            api_session.tools,
            "storage_file_upload",
            AsyncMock(return_value=(201, "ok", True)),
        ):
            response = self.client.get(
                "/oauth/google/callback",
                params={"code": "auth-code", "state": "state-123"},
                cookies={
                    api_session.GOOGLE_OAUTH_STATE_COOKIE: "state-123",
                    api_session.GOOGLE_OAUTH_CODE_VERIFIER_COOKIE: "code-verifier-123",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("закрыть его сами", response.text)
        self.assertEqual(session.commit_count, 3)
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].google_id, "google-user-id")
        self.assertEqual(session.added[0].avatar_url, "local.webp")
        self.assertEqual(response.cookies.get("accessToken"), "google-access-token")
        self.assertEqual(response.cookies.get("refreshToken"), "google-refresh-token")
        self.assertEqual(
            [call[0] for call in dummy_aiohttp.calls],
            ["POST", "GET", "GET"],
        )

    def test_yandex_oauth_callback_links_existing_account(self) -> None:
        linked_account = SimpleNamespace(
            id=42,
            yandex_id=None,
            google_id=None,
            username="linked",
            avatar_url="",
            comments=0,
            author_mods=0,
            registration_date=None,
            reputation=0,
        )
        session = _MutableSession(
            scalar_values=[None, linked_account],
            get_map={sql_account.Account: linked_account},
        )

        class _DummyYandexUser:
            id = 777
            login = "yandex-login"
            is_avatar_empty = True
            default_avatar_id = None

        class _DummyYandexID:
            def __init__(self, oauth_token: str) -> None:
                self.oauth_token = oauth_token

            async def get_user_info_json(self, with_openid_identity: bool = False):
                return _DummyYandexUser()

        with patch.object(
            api_session.yandex_oauth,
            "get_token_from_code",
            AsyncMock(return_value=SimpleNamespace(access_token="yandex-access")),
        ), patch.object(api_session, "AsyncYandexID", _DummyYandexID), patch.object(
            api_session.account,
            "check_access",
            AsyncMock(return_value={"owner_id": 42, "authenticated": True}),
        ), patch.object(
            api_session.account,
            "AsyncSessionLocal",
            return_value=session,
        ), patch.object(
            api_session.account.bcrypt,
            "hashpw",
            side_effect=[b"yandex-access-token", b"yandex-refresh-token"],
        ):
            response = self.client.get(
                "/oauth/yandex/callback",
                params={"code": "auth-code", "cid": "device123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("закрыть его сами", response.text)
        self.assertEqual(linked_account.yandex_id, 777)
        self.assertEqual(session.commit_count, 2)
        self.assertEqual(response.cookies.get("accessToken"), "yandex-access-token")
        self.assertEqual(response.cookies.get("refreshToken"), "yandex-refresh-token")

    def test_resource_image_create_uses_admin_access_for_games(self) -> None:
        resource = SimpleNamespace(
            id=None,
            type="screenshot",
            url="",
            size=None,
            date_event=None,
            owner_type="games",
            owner_id=7,
        )
        session = _MutableSession(next_id=555)

        access_admin = AsyncMock(return_value=True)
        access_mods = AsyncMock(side_effect=AssertionError("access_mods must not be called"))

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_admin",
            access_admin,
        ), patch.object(
            api_uploads.tools,
            "access_mods",
            access_mods,
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            return_value="upload-token",
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/uploads",
                json={
                    "kind": "resource_image",
                    "owner_type": "resource",
                    "mode": "create",
                    "resource_owner_type": "games",
                    "resource_owner_id": 7,
                    "resource_type": "screenshot",
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["kind"], "resource_image")
        self.assertEqual(body["owner_id"], 7)
        self.assertEqual(body["resource_id"], 555)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].owner_type, "games")
        self.assertEqual(session.added[0].owner_id, 7)
        self.assertEqual(session.added[0].id, 555)
        access_admin.assert_awaited_once()
        access_mods.assert_not_awaited()

    def test_archive_transfer_completion_updates_mod_and_game(self) -> None:
        mod = SimpleNamespace(
            id=7,
            name="Mod",
            description="Desc",
            public=0,
            condition=1,
            source="steam",
            source_id=99,
            game=1,
            size=0,
            size_unpacked=None,
        )
        game = SimpleNamespace(id=1, mods_count=3)
        session = _MutableSession(
            get_map={
                sql_catalog.Mod: mod,
                sql_catalog.Game: game,
            }
        )
        api_uploads.UPLOAD_JOBS["job-archive"] = UploadRead(
            id="job-archive",
            kind="mod_archive",
            status="created",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-archive",
            owner_type="mod",
            owner_id=7,
            mode="create",
        )

        with patch.object(
            api_uploads.tools,
            "decode_transfer_jwt",
            return_value={
                "job_id": "job-archive",
                "transfer_kind": "archive",
                "status": "success",
                "mod_id": 7,
                "pack_format": "zip",
                "bytes": 123,
                "unpacked_bytes": 456,
            },
        ), patch.object(
            api_uploads.tools,
            "storage_job_move",
            AsyncMock(return_value=(200, {"final_bytes": 321, "unpacked_bytes": 654}, True)),
        ), patch.object(
            api_uploads.mod_events,
            "publish_mod_event",
            AsyncMock(return_value=None),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/internal/storage/transfer-completions",
                headers={"Authorization": "Bearer callback-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mod.condition, 0)
        self.assertEqual(mod.size, 321)
        self.assertEqual(mod.size_unpacked, 654)
        self.assertEqual(game.mods_count, 4)
        self.assertEqual(api_uploads.UPLOAD_JOBS["job-archive"].status, "completed")
        self.assertEqual(session.commit_count, 1)
        self.assertTrue(any(isinstance(stmt, Update) for stmt in session.execute_statements))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
