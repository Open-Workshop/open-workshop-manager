from __future__ import annotations

import pathlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


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

from open_workshop_manager import main


class HealthzTests(unittest.TestCase):
    def test_healthz_returns_ok(self) -> None:
        with (
            patch.object(main.account, "init_models", AsyncMock(return_value=None)),
            patch.object(main.catalog, "init_models", AsyncMock(return_value=None)),
            patch.object(main.statistics, "init_models", AsyncMock(return_value=None)),
            patch.object(main.mod_events, "start", AsyncMock(return_value=None)),
            patch.object(main.mod_events, "stop", AsyncMock(return_value=None)),
            patch.object(main, "_cleanup_stale_mods_loop", AsyncMock(return_value=None)),
        ):
            with TestClient(main.app) as client:
                response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class CleanupTracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_work_shares_the_background_trace(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer(__name__)

        async def query(name: str) -> None:
            with tracer.start_as_current_span(name):
                pass

        async def clean_mods() -> None:
            await query("SELECT mods")

        async def clean_uploads() -> None:
            await query("SELECT upload_jobs")

        with (
            patch.object(main.trace, "get_tracer", return_value=tracer),
            patch.object(main, "_cleanup_stale_mods_once", side_effect=clean_mods),
            patch.object(main, "_cleanup_expired_upload_jobs_once", side_effect=clean_uploads),
        ):
            await main._run_cleanup_cycle()

        spans = {span.name: span for span in exporter.get_finished_spans()}
        root = spans["maintenance.cleanup"]
        for name in ("SELECT mods", "SELECT upload_jobs"):
            self.assertEqual(spans[name].parent.span_id, root.context.span_id)
            self.assertEqual(spans[name].context.trace_id, root.context.trace_id)
        provider.shutdown()

    async def test_failure_is_recorded_and_other_cleanup_still_runs(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer(__name__)
        other_cleanup = AsyncMock()

        with (
            patch.object(main.trace, "get_tracer", return_value=tracer),
            patch.object(main, "_cleanup_stale_mods_once", AsyncMock(side_effect=RuntimeError("test"))),
            patch.object(main, "_cleanup_expired_upload_jobs_once", other_cleanup),
            self.assertLogs(main.logger, level="ERROR"),
        ):
            await main._run_cleanup_cycle()

        other_cleanup.assert_awaited_once()
        root = exporter.get_finished_spans()[0]
        self.assertEqual(root.status.status_code, StatusCode.ERROR)
        self.assertEqual(root.events[0].name, "exception")
        provider.shutdown()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
