from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

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

from open_workshop_manager import access_client, standarts, tools
from open_workshop_manager.sql_logic import sql_account
from open_workshop_manager.standarts.schemas import ProblemDetails


class _TimeoutRequest:
    async def __aenter__(self):
        raise asyncio.TimeoutError

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _TimeoutSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_TimeoutSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def request(self, *args, **kwargs) -> _TimeoutRequest:
        return _TimeoutRequest()


class _DeleteTimeoutResponse:
    async def __aenter__(self):
        raise asyncio.TimeoutError

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DeleteTimeoutSession:
    last_kwargs: dict[str, object] | None = None

    def __init__(self, *args, **kwargs) -> None:
        _DeleteTimeoutSession.last_kwargs = dict(kwargs)

    async def __aenter__(self) -> "_DeleteTimeoutSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def delete(self, *args, **kwargs) -> _DeleteTimeoutResponse:
        return _DeleteTimeoutResponse()


class _DeleteResourcesResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_DeleteResourcesResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _DeleteResourcesSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.execute_statements: list[object] = []
        self.commit_count = 0

    async def __aenter__(self) -> "_DeleteResourcesSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def execute(self, stmt) -> _DeleteResourcesResult:
        self.execute_statements.append(stmt)
        return _DeleteResourcesResult(self.rows)

    async def commit(self) -> None:
        self.commit_count += 1


def _mod_response(catalog: bool, download: bool) -> access_client.ModResponse:
    return access_client.ModResponse.model_validate(
        {
            "authenticated": True,
            "owner_id": 42,
            "login_method": "password",
            "info": {
                "value": True,
                "reason": "ok",
                "reason_code": "public",
            },
            "catalog": {
                "value": catalog,
                "reason": "catalog" if catalog else "hidden",
                "reason_code": "catalog" if catalog else "hidden",
            },
            "edit": {
                "title": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "description": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "short_description": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "screenshots": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "new_version": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "authors": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "tags": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
                "dependencies": {
                    "value": False,
                    "reason": "edit",
                    "reason_code": "forbidden",
                },
            },
            "delete": {
                "value": False,
                "reason": "delete",
                "reason_code": "forbidden",
            },
            "download": {
                "value": download,
                "reason": "download" if download else "hidden",
                "reason_code": "public" if download else "hidden",
            },
        }
    )


class AccessServicePassThroughTests(unittest.TestCase):
    def test_resolve_mod_add_uses_access_put_endpoint(self) -> None:
        access_payload = {
            "authenticated": True,
            "owner_id": 42,
            "add": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
            "anonymous_add": {
                "value": False,
                "reason": "admin only",
                "reason_code": "admin_required",
            },
        }

        request_json = AsyncMock(return_value=access_payload)
        with patch.object(access_client, "_request_json", request_json):
            result = asyncio.run(access_client.resolve_mod_add())

        request_json.assert_awaited_once_with(
            "PUT",
            "/mod",
            None,
            cookies={},
        )
        self.assertTrue(result.add.value)
        self.assertFalse(result.anonymous_add.value)

    def test_resolve_tags_uses_access_patch_endpoint(self) -> None:
        access_payload = {
            "authenticated": True,
            "owner_id": 42,
            "add": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
            "edit": {
                "value": False,
                "reason": "no edit",
                "reason_code": "forbidden",
            },
            "delete": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
        }

        request_json = AsyncMock(return_value=access_payload)
        with patch.object(access_client, "_request_json", request_json):
            result = asyncio.run(access_client.resolve_tags())

        request_json.assert_awaited_once_with(
            "PATCH",
            "/tags",
            None,
            cookies={},
        )
        self.assertTrue(result.add.value)
        self.assertFalse(result.edit.value)
        self.assertTrue(result.delete.value)

    def test_resolve_genres_uses_access_patch_endpoint(self) -> None:
        access_payload = {
            "authenticated": True,
            "owner_id": 42,
            "add": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
            "edit": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
            "delete": {
                "value": False,
                "reason": "no delete",
                "reason_code": "forbidden",
            },
        }

        request_json = AsyncMock(return_value=access_payload)
        with patch.object(access_client, "_request_json", request_json):
            result = asyncio.run(access_client.resolve_genres())

        request_json.assert_awaited_once_with(
            "PATCH",
            "/genres",
            None,
            cookies={},
        )
        self.assertTrue(result.add.value)
        self.assertTrue(result.edit.value)
        self.assertFalse(result.delete.value)

    def test_resolve_game_add_uses_access_put_endpoint(self) -> None:
        access_payload = {
            "authenticated": True,
            "owner_id": 42,
            "add": {
                "value": True,
                "reason": "ok",
                "reason_code": "allowed",
            },
        }

        request_json = AsyncMock(return_value=access_payload)
        with patch.object(access_client, "_request_json", request_json):
            result = asyncio.run(access_client.resolve_game_add())

        request_json.assert_awaited_once_with(
            "PUT",
            "/game",
            None,
            cookies={},
        )
        self.assertTrue(result.add.value)

    def test_resolve_game_uses_access_post_endpoint(self) -> None:
        access_payload = {
            "authenticated": True,
            "owner_id": 42,
            "edit": {
                "title": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
                "description": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
                "short_description": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
                "screenshots": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
                "tags": {
                    "value": False,
                    "reason": "no tags",
                    "reason_code": "forbidden",
                },
                "genres": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
            },
            "delete": {
                "value": False,
                "reason": "no delete",
                "reason_code": "forbidden",
            },
        }

        request_json = AsyncMock(return_value=access_payload)
        with patch.object(access_client, "_request_json", request_json):
            result = asyncio.run(access_client.resolve_game(game_id=7))

        request_json.assert_awaited_once_with(
            "POST",
            "/game/7",
            {},
            cookies={},
        )
        self.assertTrue(result.edit.title.value)
        self.assertFalse(result.edit.tags.value)
        self.assertFalse(result.delete.value)

    def test_legacy_access_admin_uses_access_service_not_local_session(self) -> None:
        request = types.SimpleNamespace(cookies={}, url="http://manager.test/admin")
        access_payload = access_client.GameAddResponse.model_validate(
            {
                "authenticated": True,
                "owner_id": 42,
                "add": {
                    "value": True,
                    "reason": "ok",
                    "reason_code": "allowed",
                },
            }
        )

        with (
            patch.object(
                access_client,
                "resolve_game_add",
                AsyncMock(return_value=access_payload),
            ) as resolve_game_add,
            patch.object(
                tools.account,
                "check_access",
                AsyncMock(side_effect=AssertionError("local admin check must not be used")),
            ),
        ):
            self.assertTrue(asyncio.run(tools.access_admin(request)))

        resolve_game_add.assert_awaited_once_with(request=request)

    def test_access_mods_uses_catalog_right_for_catalog_mode(self) -> None:
        request = types.SimpleNamespace(cookies={})
        access_result = {
            11: _mod_response(catalog=False, download=True),
            12: _mod_response(catalog=True, download=False),
        }

        with patch.object(
            access_client, "resolve_mods", AsyncMock(return_value=access_result)
        ):
            public_ids = asyncio.run(
                tools.access_mods(request, mods_ids=[11, 12], check_mode=True)
            )
            catalog_ids = asyncio.run(
                tools.access_mods(
                    request, mods_ids=[11, 12], check_mode=True, catalog=True
                )
            )

        self.assertEqual(public_ids, [11])
        self.assertEqual(catalog_ids, [12])

    def test_access_service_timeout_becomes_gateway_timeout_error(self) -> None:
        with patch.object(access_client.aiohttp, "ClientSession", _TimeoutSession):
            with self.assertRaises(access_client.AccessServiceError) as raised:
                asyncio.run(access_client._request_json("POST", "/mods", {}))

        self.assertEqual(raised.exception.status_code, 504)

    def test_session_touch_is_throttled(self) -> None:
        now = datetime.datetime(2026, 4, 25, 12, 21, 24)

        with patch.object(
            sql_account.config,
            "SESSION_TOUCH_INTERVAL_SECONDS",
            60,
            create=True,
        ):
            self.assertFalse(
                sql_account.should_touch_session(
                    now - datetime.timedelta(seconds=30),
                    now,
                )
            )
            self.assertTrue(
                sql_account.should_touch_session(
                    now - datetime.timedelta(seconds=61),
                    now,
                )
            )

    def test_successful_bcrypt_token_check_is_cached(self) -> None:
        tools._TOKEN_CHECK_CACHE.clear()

        with (
            patch.object(
                tools.config,
                "ACCESS_CALLBACK_TOKEN",
                "$2b$cached-token-hash",
                create=True,
            ),
            patch.object(tools.bcrypt, "checkpw", return_value=True) as checkpw,
        ):
            self.assertTrue(
                asyncio.run(tools.check_token("ACCESS_CALLBACK_TOKEN", "secret"))
            )
            self.assertTrue(
                asyncio.run(tools.check_token("ACCESS_CALLBACK_TOKEN", "secret"))
            )

        self.assertEqual(checkpw.call_count, 1)
        tools._TOKEN_CHECK_CACHE.clear()

    def test_problem_details_are_parsed_from_access_error_body(self) -> None:
        payload = {
            "type": "about:blank",
            "title": "Доступ запрещен",
            "status": 403,
            "detail": "Нельзя редактировать этот мод.",
            "code": "FORBIDDEN",
            "context": {"reason_code": "forbidden"},
        }

        problem = access_client._parse_problem_details(403, json.dumps(payload))

        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertEqual(problem.status, 403)
        self.assertEqual(problem.title, "Доступ запрещен")
        self.assertEqual(problem.detail, "Нельзя редактировать этот мод.")
        self.assertEqual(problem.code, "FORBIDDEN")
        self.assertEqual(problem.context, {"reason_code": "forbidden"})

    def test_access_service_errors_are_rethrown_with_problem_details(self) -> None:
        problem = ProblemDetails(
            type="about:blank",
            title="Доступ запрещен",
            status=403,
            detail="Нельзя редактировать этот мод.",
            instance="http://manager.test/mod/1",
            code="FORBIDDEN",
            context={"reason_code": "forbidden"},
        )
        exc = access_client.AccessServiceError.with_problem(
            "Access service rejected request with status 403",
            status_code=403,
            problem=problem,
            response_text=json.dumps(
                problem.model_dump(mode="json", exclude_none=True)
            ),
        )

        with self.assertRaises(HTTPException) as raised:
            tools._raise_access_service_error("http://manager.test/mod/1", exc)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            raised.exception.detail,
            problem.model_dump(mode="json", exclude_none=True),
        )

    def test_plain_access_service_status_is_preserved(self) -> None:
        exc = access_client.AccessServiceError(
            "Access service rejected request with status 403: forbidden",
            status_code=403,
        )
        exc.response_text = "forbidden"

        with self.assertRaises(HTTPException) as raised:
            tools._raise_access_service_error("http://manager.test/mod/1", exc)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "forbidden")

    def test_access_service_timeout_fallback_remains_intact(self) -> None:
        exc = access_client.AccessServiceError(
            "Access service rejected request with status 504",
            status_code=504,
        )

        with self.assertRaises(standarts.GatewayTimeoutError) as raised:
            tools._raise_access_service_error("http://manager.test/mod/1", exc)

        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(raised.exception.problem.detail, "Access service timeout")

    def test_storage_file_delete_timeout_returns_false(self) -> None:
        _DeleteTimeoutSession.last_kwargs = None
        with (
            patch.object(
                tools.config,
                "STORAGE_DELETE_TIMEOUT_SECONDS",
                1,
                create=True,
            ),
            patch.object(
                tools.aiohttp,
                "ClientSession",
                _DeleteTimeoutSession,
            ),
        ):
            self.assertFalse(
                asyncio.run(tools.storage_file_delete("resource", "mods/1/file.webp"))
            )

        self.assertIsNotNone(_DeleteTimeoutSession.last_kwargs)
        assert _DeleteTimeoutSession.last_kwargs is not None
        timeout = _DeleteTimeoutSession.last_kwargs.get("timeout")
        self.assertIsNotNone(timeout)
        self.assertEqual(getattr(timeout, "total", None), 1)

    def test_delete_resources_returns_false_when_any_storage_delete_fails(self) -> None:
        rows = [
            types.SimpleNamespace(id=1, url="local/mods/1/one.webp"),
            types.SimpleNamespace(id=2, url="local/mods/1/two.webp"),
        ]
        session = _DeleteResourcesSession(rows)
        storage_delete = AsyncMock(side_effect=[True, False])

        with (
            patch.object(
                tools.catalog,
                "AsyncSessionLocal",
                return_value=session,
            ),
            patch.object(
                tools,
                "storage_file_delete",
                storage_delete,
            ),
        ):
            result = asyncio.run(tools.delete_resources(owner_type="mods", owner_id=1))

        self.assertFalse(result)
        self.assertEqual(storage_delete.await_count, 2)
        self.assertEqual(session.commit_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
