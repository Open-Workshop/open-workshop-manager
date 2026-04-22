from __future__ import annotations

import json
import pathlib
import sys
import types
import unittest

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
from open_workshop_manager.standarts.schemas import ProblemDetails


class AccessServicePassThroughTests(unittest.TestCase):
    def test_problem_details_are_parsed_from_access_error_body(self) -> None:
        payload = {
            "type": "about:blank",
            "title": "Доступ запрещен",
            "status": 403,
            "detail": "Нельзя редактировать этот мод.",
            "code": "access_denied",
            "context": {"reason_code": "forbidden"},
        }

        problem = access_client._parse_problem_details(403, json.dumps(payload))

        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertEqual(problem.status, 403)
        self.assertEqual(problem.title, "Доступ запрещен")
        self.assertEqual(problem.detail, "Нельзя редактировать этот мод.")
        self.assertEqual(problem.code, "access_denied")
        self.assertEqual(problem.context, {"reason_code": "forbidden"})

    def test_access_service_errors_are_rethrown_with_problem_details(self) -> None:
        problem = ProblemDetails(
            type="about:blank",
            title="Доступ запрещен",
            status=403,
            detail="Нельзя редактировать этот мод.",
            code="access_denied",
            context={"reason_code": "forbidden"},
        )
        exc = access_client.AccessServiceError.with_problem(
            "Access service rejected request with status 403",
            status_code=403,
            problem=problem,
            response_text=json.dumps(problem.model_dump(mode="json", exclude_none=True)),
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
