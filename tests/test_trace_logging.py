from __future__ import annotations

import asyncio
import io
import logging
import pathlib
import sys
import unittest

from opentelemetry.sdk.trace import TracerProvider
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from open_workshop_manager import trace_logging


class TraceLoggingTests(unittest.TestCase):
    def test_trace_ids_follow_async_context_without_labelling_background_logs(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        old_factory = logging.getLogRecordFactory()
        old_installed = trace_logging._installed
        trace_logging._installed = False
        try:
            trace_logging.install_trace_log_context()
            logger = logging.getLogger("ow-trace-log-test")
            logger.setLevel(logging.INFO)
            provider = TracerProvider()
            tracer = provider.get_tracer("test")
            async def task(label):
                with tracer.start_as_current_span(label) as span:
                    await asyncio.sleep(0)
                    logger.info(label)
                    return f"{span.get_span_context().trace_id:032x}", f"{span.get_span_context().span_id:016x}"
            async def run():
                return await asyncio.gather(task("first"), task("second"))
            ids = asyncio.run(run())
            logger.info("background")
            lines = output.getvalue().splitlines()
            self.assertIn(f"trace_id={ids[0][0]} span_id={ids[0][1]} first", lines)
            self.assertIn(f"trace_id={ids[1][0]} span_id={ids[1][1]} second", lines)
            self.assertIn("background", lines)
        finally:
            root.removeHandler(handler)
            logging.setLogRecordFactory(old_factory)
            trace_logging._installed = old_installed


if __name__ == "__main__":
    unittest.main()
