from __future__ import annotations

import asyncio
import datetime
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

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
from open_workshop_manager import main as app_main
from open_workshop_manager.mods import api_mod
from open_workshop_manager.social import api_profile
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

    def _resolve_target(self, entity: type, ident: object | None) -> object | None:
        target = self.get_map.get(entity)
        if isinstance(target, dict):
            if ident is None:
                return None
            try:
                ident_value = int(ident)
            except (TypeError, ValueError):
                return None
            return target.get(ident_value)
        if target is None:
            return None
        if ident is None:
            return target
        return target if getattr(target, "id", None) == ident else None

    def _apply_update(self, stmt: Update) -> None:
        table_name = stmt.table.name
        params = stmt.compile().params

        if table_name == sql_catalog.Game.__tablename__:
            game_targets = self.get_map.get(sql_catalog.Game)
            target_id = None
            for key, value in params.items():
                if key.startswith("id_"):
                    try:
                        target_id = int(value)
                    except (TypeError, ValueError):
                        target_id = None
                    break
            if isinstance(game_targets, dict):
                game = self._resolve_target(sql_catalog.Game, target_id)
                if game is None and len(game_targets) == 1:
                    game = next(iter(game_targets.values()))
            else:
                game = game_targets

            if game is None:
                return

            try:
                sql_text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            except Exception:  # pragma: no cover - fallback for unusual SQLAlchemy paths
                sql_text = str(stmt)

            if "mods_count" in sql_text:
                current = int(getattr(game, "mods_count", 0) or 0)
                if "+ 1" in sql_text or "+1" in sql_text:
                    game.mods_count = current + 1
                elif "- 1" in sql_text or "-1" in sql_text:
                    game.mods_count = current - 1
                else:
                    new_value = params.get("mods_count")
                    if new_value is not None:
                        game.mods_count = int(new_value)
            return

        if table_name == sql_catalog.Mod.__tablename__:
            target = self._resolve_target(sql_catalog.Mod, None)
        elif table_name == sql_catalog.Resource.__tablename__:
            target = self._resolve_target(sql_catalog.Resource, None)
        elif table_name == sql_account.Account.__tablename__:
            target = self._resolve_target(sql_account.Account, None)
        elif table_name == sql_account.Session.__tablename__:
            target = self._resolve_target(sql_account.Session, None)
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
        return self._resolve_target(entity, ident)

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
        app.include_router(api_profile.router)
        app.include_router(api_mod.router)
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

    def test_yandex_oauth_authorize_sets_state_cookie(self) -> None:
        with patch.object(
            api_session.secrets,
            "token_urlsafe",
            return_value="state-123",
        ), patch.object(
            api_session.yandex_oauth,
            "jget_authorization_url",
            return_value="https://oauth.yandex.test/authorize?state=state-123",
        ) as auth_url_mock:
            response = self.client.get("/oauth/yandex/authorize", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(
            response.headers["location"],
            "https://oauth.yandex.test/authorize?state=state-123",
        )
        self.assertEqual(
            response.cookies.get(api_session.YANDEX_OAUTH_STATE_COOKIE),
            "state-123",
        )
        auth_url_mock.assert_called_once_with(state="state-123")

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
                params={"code": "auth-code", "cid": "device123", "state": "state-123"},
                cookies={api_session.YANDEX_OAUTH_STATE_COOKIE: "state-123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("закрыть его сами", response.text)
        self.assertEqual(linked_account.yandex_id, 777)
        self.assertEqual(session.commit_count, 2)
        self.assertEqual(response.cookies.get("accessToken"), "yandex-access-token")
        self.assertEqual(response.cookies.get("refreshToken"), "yandex-refresh-token")

    def test_yandex_oauth_callback_rejects_state_mismatch(self) -> None:
        token_mock = AsyncMock(side_effect=AssertionError("token exchange must not happen"))
        with patch.object(
            api_session.yandex_oauth,
            "get_token_from_code",
            token_mock,
        ):
            response = self.client.get(
                "/oauth/yandex/callback",
                params={"code": "auth-code", "state": "callback-state"},
                cookies={api_session.YANDEX_OAUTH_STATE_COOKIE: "cookie-state"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Yandex OAuth state mismatch", response.text)
        token_mock.assert_not_awaited()

    def test_resource_image_create_uses_game_screenshot_access_for_games(self) -> None:
        resource = SimpleNamespace(
            id=None,
            type="screenshot",
            url="",
            size=None,
            date_event=None,
            sort_order=0,
            owner_type="games",
            owner_id=7,
        )
        session = _MutableSession(next_id=555)

        access_game_action = AsyncMock(
            return_value=SimpleNamespace(
                authenticated=True,
                owner_id=42,
                edit=SimpleNamespace(
                    screenshots=SimpleNamespace(value=True, reason="", reason_code="")
                ),
            )
        )
        access_mods = AsyncMock(side_effect=AssertionError("access_mods must not be called"))
        captured_payload: dict[str, object] = {}

        def fake_create_transfer_jwt(payload, audience, ttl_seconds, issuer="manager"):
            captured_payload.update(payload)
            captured_payload["audience"] = audience
            captured_payload["ttl_seconds"] = ttl_seconds
            captured_payload["issuer"] = issuer
            return "upload-token"

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_game_action",
            access_game_action,
        ), patch.object(
            api_uploads.tools,
            "access_mods",
            access_mods,
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            side_effect=fake_create_transfer_jwt,
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
                    "resource_sort_order": 17,
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["kind"], "resource_image")
        self.assertEqual(body["owner_id"], 7)
        self.assertEqual(body["resource_id"], 555)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(len(session.added), 2)
        resource_row = next(obj for obj in session.added if isinstance(obj, sql_catalog.Resource))
        self.assertEqual(resource_row.sort_order, 17)
        self.assertTrue(any(isinstance(obj, sql_catalog.Resource) for obj in session.added))
        self.assertTrue(any(isinstance(obj, sql_catalog.UploadJob) for obj in session.added))
        self.assertEqual(captured_payload["transfer_kind"], "img")
        self.assertEqual(captured_payload["storage_type"], "resource")
        self.assertEqual(captured_payload["file_kind"], "img")
        self.assertEqual(captured_payload["callback_action"], "resource_add")
        self.assertEqual(captured_payload["resource_sort_order"], 17)
        self.assertEqual(captured_payload["target_path"], "games/7/555.webp")
        access_game_action.assert_awaited_once_with(request=ANY, game_id=7)
        access_mods.assert_not_awaited()

    def test_resource_image_create_uses_modpack_access_for_modpacks(self) -> None:
        resource = SimpleNamespace(
            id=None,
            type="screenshot",
            url="",
            size=None,
            date_event=None,
            sort_order=0,
            owner_type="modpacks",
            owner_id=7,
        )
        session = _MutableSession(next_id=555)

        access_modpacks = AsyncMock(return_value=True)
        access_game_action = AsyncMock(side_effect=AssertionError("access_game_action must not be called"))
        access_mods = AsyncMock(side_effect=AssertionError("access_mods must not be called"))
        captured_payload: dict[str, object] = {}

        def fake_create_transfer_jwt(payload, audience, ttl_seconds, issuer="manager"):
            captured_payload.update(payload)
            captured_payload["audience"] = audience
            captured_payload["ttl_seconds"] = ttl_seconds
            captured_payload["issuer"] = issuer
            return "upload-token"

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_game_action",
            access_game_action,
        ), patch.object(
            api_uploads.tools,
            "access_mods",
            access_mods,
        ), patch.object(
            api_uploads.tools,
            "access_modpacks",
            access_modpacks,
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            side_effect=fake_create_transfer_jwt,
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
                    "resource_owner_type": "modpacks",
                    "resource_owner_id": 7,
                    "resource_type": "screenshot",
                    "resource_sort_order": 17,
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["kind"], "resource_image")
        self.assertEqual(body["owner_id"], 7)
        self.assertEqual(body["resource_id"], 555)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(len(session.added), 2)
        resource_row = next(obj for obj in session.added if isinstance(obj, sql_catalog.Resource))
        self.assertEqual(resource_row.sort_order, 17)
        self.assertTrue(any(isinstance(obj, sql_catalog.Resource) for obj in session.added))
        self.assertTrue(any(isinstance(obj, sql_catalog.UploadJob) for obj in session.added))
        self.assertEqual(captured_payload["transfer_kind"], "img")
        self.assertEqual(captured_payload["storage_type"], "resource")
        self.assertEqual(captured_payload["file_kind"], "img")
        self.assertEqual(captured_payload["callback_action"], "resource_add")
        self.assertEqual(captured_payload["resource_sort_order"], 17)
        self.assertEqual(captured_payload["target_path"], "modpacks/7/555.webp")
        access_modpacks.assert_awaited_once()
        access_game_action.assert_not_awaited()
        access_mods.assert_not_awaited()

    def test_profile_avatar_create_uses_avatar_file_kind(self) -> None:
        session = _MutableSession(next_id=777)
        access_profile = AsyncMock(
            return_value=SimpleNamespace(
                authenticated=True,
                edit=SimpleNamespace(
                    avatar=SimpleNamespace(value=True, reason="", reason_code=""),
                ),
            )
        )
        captured_payload: dict[str, object] = {}

        def fake_create_transfer_jwt(payload, audience, ttl_seconds, issuer="manager"):
            captured_payload.update(payload)
            captured_payload["audience"] = audience
            captured_payload["ttl_seconds"] = ttl_seconds
            captured_payload["issuer"] = issuer
            return "upload-token"

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_profile",
            access_profile,
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            side_effect=fake_create_transfer_jwt,
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/uploads",
                json={
                    "kind": "profile_avatar",
                    "owner_type": "profile",
                    "owner_id": 7,
                    "mode": "create",
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["kind"], "profile_avatar")
        self.assertEqual(body["owner_id"], 7)
        self.assertEqual(body["mode"], "create")
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(len(session.added), 1)
        self.assertTrue(any(isinstance(obj, sql_catalog.UploadJob) for obj in session.added))
        self.assertEqual(captured_payload["transfer_kind"], "img")
        self.assertEqual(captured_payload["storage_type"], "avatar")
        self.assertEqual(captured_payload["file_kind"], "img")
        self.assertEqual(captured_payload["callback_action"], "avatar_set")
        self.assertEqual(captured_payload["target_path"], "7.webp")
        access_profile.assert_awaited_once()

    def test_mod_archive_create_rejects_published_mod(self) -> None:
        mod = SimpleNamespace(
            id=7,
            condition=0,
            source="local",
            source_id=None,
            game=None,
            name="Published mod",
            description="Desc",
            public=0,
        )
        session = _MutableSession(get_map={sql_catalog.Mod: mod})

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_mods",
            AsyncMock(return_value=True),
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            side_effect=AssertionError("token should not be created"),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/uploads",
                json={
                    "kind": "mod_archive",
                    "owner_type": "mod",
                    "owner_id": 7,
                    "mode": "create",
                },
            )

        self.assertEqual(response.status_code, 412)
        body = response.json()
        self.assertEqual(body["code"], "MOD_UPLOAD_MODE_MISMATCH")
        self.assertEqual(session.commit_count, 0)

    def test_mod_archive_replace_rejects_draft_mod(self) -> None:
        mod = SimpleNamespace(
            id=7,
            condition=1,
            source="local",
            source_id=None,
            game=None,
            name="Draft mod",
            description="Desc",
            public=0,
        )
        session = _MutableSession(get_map={sql_catalog.Mod: mod})

        with patch.object(api_uploads.config, "TRANSFER_JWT_SECRET", "secret", create=True), patch.object(
            api_uploads.tools,
            "access_mods",
            AsyncMock(return_value=True),
        ), patch.object(
            api_uploads.tools,
            "create_transfer_jwt",
            side_effect=AssertionError("token should not be created"),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/uploads",
                json={
                    "kind": "mod_archive",
                    "owner_type": "mod",
                    "owner_id": 7,
                    "mode": "replace",
                },
            )

        self.assertEqual(response.status_code, 412)
        body = response.json()
        self.assertEqual(body["code"], "MOD_UPLOAD_MODE_MISMATCH")
        self.assertEqual(session.commit_count, 0)

    def test_get_upload_reads_persisted_row_when_cache_is_empty(self) -> None:
        upload_row = SimpleNamespace(
            id="job-db",
            kind="mod_archive",
            status="created",
            transfer_url="https://storage.example/transfer/upload?token=abc",
            ws_url="wss://storage.example/transfer/ws/job-db?token=abc",
            expires_at=datetime.datetime(2026, 4, 27, 12, 15, 0, tzinfo=datetime.timezone.utc),
            owner_type="mod",
            owner_id=7,
            mode="create",
            resource_id=None,
        )
        session = _MutableSession(get_map={sql_catalog.UploadJob: upload_row})
        access_mods = AsyncMock(return_value=True)

        with patch.object(
            api_uploads.tools,
            "access_mods",
            access_mods,
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.get("/uploads/job-db")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "created")
        self.assertEqual(set(body.keys()), {"status", "expires_at"})
        self.assertEqual(api_uploads.UPLOAD_JOBS["job-db"].status, "created")
        access_mods.assert_awaited_once()
        self.assertEqual(access_mods.await_args.kwargs["mods_ids"], [7])
        self.assertTrue(access_mods.await_args.kwargs["edit"])

    def test_profile_patch_allows_clearing_mute_until(self) -> None:
        profile_row = SimpleNamespace(
            id=7,
            username="User",
            about="About",
            avatar_url="",
            grade="Member",
            comments=0,
            author_mods=0,
            registration_date=datetime.datetime(2026, 4, 1, 0, 0, 0),
            reputation=0,
            mute_until=datetime.datetime(2026, 5, 1, 0, 0, 0),
        )
        session = _MutableSession(get_map={sql_account.Account: profile_row})

        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=1,
            edit=SimpleNamespace(
                rights=SimpleNamespace(value=False),
                nickname=SimpleNamespace(value=True, reason="", reason_code=""),
                description=SimpleNamespace(value=True, reason="", reason_code=""),
                grade=SimpleNamespace(value=True, reason="", reason_code=""),
                mute=SimpleNamespace(value=True, reason="", reason_code=""),
            ),
        )

        with patch.object(
            api_profile.tools,
            "access_profile",
            AsyncMock(return_value=access_result),
        ), patch.object(
            api_profile.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/profiles/7",
                json={"mute_until": None},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(profile_row.mute_until)
        body = response.json()
        self.assertEqual(body["id"], 7)
        self.assertFalse(body["mute"])

    def test_profile_patch_rejects_self_mute_via_access(self) -> None:
        profile_row = SimpleNamespace(
            id=7,
            username="User",
            about="About",
            avatar_url="",
            grade="Member",
            comments=0,
            author_mods=0,
            registration_date=datetime.datetime(2026, 4, 1, 0, 0, 0),
            reputation=0,
            mute_until=None,
        )
        session = _MutableSession(get_map={sql_account.Account: profile_row})

        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=7,
            admin=False,
            edit=SimpleNamespace(
                rights=SimpleNamespace(value=False),
                nickname=SimpleNamespace(value=True, reason="", reason_code=""),
                description=SimpleNamespace(value=True, reason="", reason_code=""),
                grade=SimpleNamespace(value=True, reason="", reason_code=""),
                mute=SimpleNamespace(
                    value=False,
                    reason="Нельзя назначить мут своему профилю.",
                    reason_code="forbidden",
                ),
                password=SimpleNamespace(value=True, reason="", reason_code=""),
            ),
        )

        with patch.object(
            api_profile.tools,
            "access_profile",
            AsyncMock(return_value=access_result),
        ), patch.object(
            api_profile.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/profiles/7",
                json={"mute_until": datetime.datetime(2026, 5, 1, 0, 0, 0).isoformat()},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")

    def test_profile_patch_username_cooldown_for_self(self) -> None:
        profile_row = SimpleNamespace(
            id=7,
            username="User",
            about="About",
            avatar_url="",
            grade="Member",
            comments=0,
            author_mods=0,
            registration_date=datetime.datetime(2026, 4, 1, 0, 0, 0),
            reputation=0,
            mute_until=None,
            last_username_reset=datetime.datetime(2026, 4, 27, 0, 0, 0),
        )
        session = _MutableSession(get_map={sql_account.Account: profile_row})

        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=7,
            admin=False,
            edit=SimpleNamespace(
                rights=SimpleNamespace(value=False),
                nickname=SimpleNamespace(
                    value=False,
                    reason="Смена никнейма пока недоступна: после последнего изменения действует задержка.",
                    reason_code="cooldown",
                ),
                description=SimpleNamespace(value=True, reason="", reason_code=""),
                grade=SimpleNamespace(value=True, reason="", reason_code=""),
                mute=SimpleNamespace(value=True, reason="", reason_code=""),
                password=SimpleNamespace(value=True, reason="", reason_code=""),
            ),
        )

        with patch.object(
            api_profile.tools,
            "access_profile",
            AsyncMock(return_value=access_result),
        ), patch.object(
            api_profile.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/profiles/7",
                json={"username": "NewName"},
            )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()["code"], "PRECONDITION_FAILED")

    def test_profile_password_patch_enforces_cooldown(self) -> None:
        profile_row = SimpleNamespace(
            id=7,
            username="User",
            about="About",
            avatar_url="",
            grade="Member",
            comments=0,
            author_mods=0,
            registration_date=datetime.datetime(2026, 4, 1, 0, 0, 0),
            reputation=0,
            mute_until=None,
            last_password_reset=datetime.datetime.now() - datetime.timedelta(minutes=1),
            password_hash="old-hash",
        )
        session = _MutableSession(get_map={sql_account.Account: profile_row})

        access_result = SimpleNamespace(
            authenticated=True,
            owner_id=7,
            admin=False,
            edit=SimpleNamespace(
                rights=SimpleNamespace(value=False),
                nickname=SimpleNamespace(value=True, reason="", reason_code=""),
                description=SimpleNamespace(value=True, reason="", reason_code=""),
                grade=SimpleNamespace(value=True, reason="", reason_code=""),
                mute=SimpleNamespace(value=True, reason="", reason_code=""),
                password=SimpleNamespace(
                    value=False,
                    reason="Смена пароля пока недоступна: после последнего изменения действует задержка.",
                    reason_code="cooldown",
                ),
            ),
        )

        with patch.object(
            api_profile.tools,
            "access_profile",
            AsyncMock(return_value=access_result),
        ), patch.object(
            api_profile.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/profiles/7/password",
                json={"new_password": "new-password"},
            )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()["code"], "PRECONDITION_FAILED")

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
        ), patch.object(
            api_uploads.account,
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

    def test_archive_transfer_completion_deletes_conflicting_archive(self) -> None:
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
        conflict_mod = SimpleNamespace(id=8)
        session = _MutableSession(
            scalar_values=[conflict_mod.id],
            get_map={
                sql_catalog.Mod: mod,
            },
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

        storage_delete = AsyncMock(return_value=True)

        with patch.object(
            api_uploads.tools,
            "decode_transfer_jwt",
            return_value={
                "job_id": "job-archive",
                "transfer_kind": "archive",
                "status": "success",
                "mod_id": 7,
                "pack_format": "zip",
                "mode": "create",
                "bytes": 123,
                "unpacked_bytes": 456,
            },
        ), patch.object(
            api_uploads.tools,
            "storage_job_move",
            AsyncMock(return_value=(200, {"final_bytes": 321, "unpacked_bytes": 654}, True)),
        ), patch.object(
            api_uploads.tools,
            "storage_file_delete",
            storage_delete,
        ), patch.object(
            api_uploads.mod_events,
            "publish_mod_event",
            AsyncMock(return_value=None),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ), patch.object(
            api_uploads.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/internal/storage/transfer-completions",
                headers={"Authorization": "Bearer callback-token"},
            )

        self.assertEqual(response.status_code, 412)
        storage_delete.assert_awaited_once_with(type="archive", path="mods/7/main.zip")
        self.assertEqual(api_uploads.UPLOAD_JOBS["job-archive"].status, "failed")

    def test_archive_transfer_completion_is_idempotent_when_job_completed(self) -> None:
        upload_row = SimpleNamespace(
            id="job-archive",
            kind="mod_archive",
            status="completed",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-archive",
            expires_at=datetime.datetime(2026, 4, 27, 12, 15, 0, tzinfo=datetime.timezone.utc),
            owner_type="mod",
            owner_id=7,
            mode="create",
            resource_id=None,
        )
        session = _MutableSession(get_map={sql_catalog.UploadJob: upload_row})

        with patch.object(
            api_uploads.tools,
            "decode_transfer_jwt",
            return_value={
                "job_id": "job-archive",
                "transfer_kind": "archive",
                "status": "success",
                "mod_id": 7,
            },
        ), patch.object(
            api_uploads.tools,
            "storage_job_move",
            AsyncMock(side_effect=AssertionError("move should not be called")),
        ), patch.object(
            api_uploads.mod_events,
            "publish_mod_event",
            AsyncMock(return_value=None),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ), patch.object(
            api_uploads.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/internal/storage/transfer-completions",
                headers={"Authorization": "Bearer callback-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(upload_row.status, "completed")
        self.assertEqual(session.commit_count, 0)

    def test_archive_transfer_completion_returns_conflict_when_job_failed(self) -> None:
        upload_row = SimpleNamespace(
            id="job-archive",
            kind="mod_archive",
            status="failed",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-archive",
            expires_at=datetime.datetime(2026, 4, 27, 12, 15, 0, tzinfo=datetime.timezone.utc),
            owner_type="mod",
            owner_id=7,
            mode="create",
            resource_id=None,
        )
        session = _MutableSession(get_map={sql_catalog.UploadJob: upload_row})

        with patch.object(
            api_uploads.tools,
            "decode_transfer_jwt",
            return_value={
                "job_id": "job-archive",
                "transfer_kind": "archive",
                "status": "success",
                "mod_id": 7,
            },
        ), patch.object(
            api_uploads.tools,
            "storage_job_move",
            AsyncMock(side_effect=AssertionError("move should not be called")),
        ), patch.object(
            api_uploads.mod_events,
            "publish_mod_event",
            AsyncMock(return_value=None),
        ), patch.object(
            api_uploads.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ), patch.object(
            api_uploads.account,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.post(
                "/internal/storage/transfer-completions",
                headers={"Authorization": "Bearer callback-token"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(upload_row.status, "failed")
        self.assertEqual(session.commit_count, 0)

    def test_patch_mod_clears_nullable_descriptions_without_stringifying_none(self) -> None:
        mod = SimpleNamespace(
            id=7,
            name="Mod",
            short_description="Old short",
            description="Old description",
            source="local",
            source_id=None,
            size=0,
            size_unpacked=None,
            condition=1,
            public=0,
            adult=False,
            date_creation=datetime.datetime(2026, 4, 1, 0, 0, 0),
            date_update_file=datetime.datetime(2026, 4, 27, 0, 0, 0),
            date_edit=datetime.datetime(2026, 4, 27, 0, 0, 0),
            game=None,
            downloads=0,
        )
        session = _MutableSession(get_map={sql_catalog.Mod: mod})

        with patch.object(
            api_mod.tools,
            "access_mods",
            AsyncMock(return_value=True),
        ), patch.object(
            api_mod.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/mods/7",
                json={
                    "short_description": None,
                    "description": None,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(mod.short_description)
        self.assertIsNone(mod.description)
        body = response.json()
        self.assertNotIn("short_description", body)
        self.assertNotIn("description", body)

    def test_patch_mod_updates_game_counts_when_moving_published_mod(self) -> None:
        mod = SimpleNamespace(
            id=7,
            name="Mod",
            short_description="Short",
            description="Description",
            source="local",
            source_id=None,
            size=0,
            size_unpacked=None,
            condition=0,
            public=0,
            adult=False,
            date_creation=datetime.datetime(2026, 4, 1, 0, 0, 0),
            date_update_file=datetime.datetime(2026, 4, 27, 0, 0, 0),
            date_edit=datetime.datetime(2026, 4, 27, 0, 0, 0),
            game=1,
            downloads=0,
        )
        old_game = SimpleNamespace(id=1, mods_count=3)
        new_game = SimpleNamespace(id=2, mods_count=4)
        session = _MutableSession(
            get_map={
                sql_catalog.Mod: mod,
                sql_catalog.Game: {
                    1: old_game,
                    2: new_game,
                },
            }
        )

        with patch.object(
            api_mod.tools,
            "access_mods",
            AsyncMock(return_value=True),
        ), patch.object(
            api_mod.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            response = self.client.patch(
                "/mods/7",
                json={
                    "game_id": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mod.game, 2)
        self.assertEqual(old_game.mods_count, 2)
        self.assertEqual(new_game.mods_count, 5)
        self.assertEqual(session.commit_count, 1)

    def test_cleanup_expired_upload_jobs_removes_empty_resource_image_resources(self) -> None:
        upload_row = SimpleNamespace(
            id="job-resource",
            kind="resource_image",
            status="created",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-resource",
            expires_at=datetime.datetime(2026, 4, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
            owner_type="resource",
            owner_id=7,
            mode="create",
            resource_id=10,
        )
        resource = SimpleNamespace(
            id=10,
            type="screenshot",
            url="",
            size=None,
            sort_order=0,
            date_event=None,
            owner_type="games",
            owner_id=7,
        )
        session = _MutableSession(
            execute_first_values=[[upload_row]],
            get_map={sql_catalog.Resource: resource},
        )
        app_main.upload_api.UPLOAD_JOBS["job-resource"] = UploadRead(
            id="job-resource",
            kind="resource_image",
            status="created",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-resource",
            expires_at=upload_row.expires_at,
            owner_type="resource",
            owner_id=7,
            mode="create",
            resource_id=10,
        )

        with patch.object(
            app_main.catalog,
            "AsyncSessionLocal",
            return_value=session,
        ):
            asyncio.run(app_main._cleanup_expired_upload_jobs_once())

        self.assertNotIn("job-resource", app_main.upload_api.UPLOAD_JOBS)
        self.assertTrue(
            any(
                isinstance(stmt, Delete)
                and stmt.table.name == sql_catalog.Resource.__tablename__
                for stmt in session.execute_statements
            )
        )
        self.assertTrue(
            any(
                isinstance(stmt, Delete)
                and stmt.table.name == sql_catalog.UploadJob.__tablename__
                for stmt in session.execute_statements
            )
        )
        self.assertEqual(session.commit_count, 1)

    def test_resource_image_completion_updates_sort_order_on_success(self) -> None:
        upload_row = SimpleNamespace(
            id="job-resource",
            kind="resource_image",
            status="created",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-resource",
            expires_at=datetime.datetime(2026, 4, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
            owner_type="resource",
            owner_id=7,
            mode="replace",
            resource_id=10,
        )
        resource = SimpleNamespace(
            id=10,
            type="screenshot",
            url="",
            size=None,
            sort_order=1,
            date_event=None,
            owner_type="games",
            owner_id=7,
        )
        session = _MutableSession(get_map={sql_catalog.Resource: resource})
        app_main.upload_api.UPLOAD_JOBS["job-resource"] = UploadRead(
            id="job-resource",
            kind="resource_image",
            status="created",
            transfer_url="https://storage.example/transfer/upload",
            ws_url="wss://storage.example/transfer/ws/job-resource",
            expires_at=upload_row.expires_at,
            owner_type="resource",
            owner_id=7,
            mode="replace",
            resource_id=10,
        )

        with patch.object(
            api_uploads.tools,
            "decode_transfer_jwt",
            return_value={
                "job_id": "job-resource",
                "transfer_kind": "img",
                "status": "success",
                "storage_type": "resource",
                "callback_action": "resource_edit",
                "callback_context": {"resource_id": 10},
                "resource_sort_order": 33,
                "target_path": "games/7/10.webp",
            },
        ), patch.object(
            api_uploads.tools,
            "storage_job_move",
            AsyncMock(return_value=(200, {"final_bytes": 123}, True)),
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
        self.assertEqual(resource.sort_order, 33)
        self.assertEqual(resource.url, "local/games/7/10.webp")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
