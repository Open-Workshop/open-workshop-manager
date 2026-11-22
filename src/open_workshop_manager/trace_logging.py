"""Keep application log records correlated with the current OpenTelemetry span."""
from __future__ import annotations

import logging

_installed = False


class _TraceFormatter(logging.Formatter):
    def __init__(self, original: logging.Formatter | None):
        super().__init__()
        self.original = original or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        message = self.original.format(record)
        trace_id = getattr(record, "ow_trace_id", "")
        span_id = getattr(record, "ow_span_id", "")
        if trace_id and span_id:
            return f"trace_id={trace_id} span_id={span_id} {message}"
        return message


def install_trace_log_context() -> None:
    global _installed
    if _installed:
        return
    from opentelemetry import trace

    previous_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous_factory(*args, **kwargs)
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            record.ow_trace_id = f"{context.trace_id:032x}"
            record.ow_span_id = f"{context.span_id:016x}"
        else:
            record.ow_trace_id = ""
            record.ow_span_id = ""
        return record

    logging.setLogRecordFactory(factory)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    # Some frameworks use their own handlers instead of propagating to root.
    handlers = list(root.handlers)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            handlers.extend(logger.handlers)
    for handler in set(handlers):
        if not isinstance(handler.formatter, _TraceFormatter):
            handler.setFormatter(_TraceFormatter(handler.formatter))
    _installed = True
