"""Observability (D-019): a trace id on every log line, written as one JSON object per line.

A trace is the note_id on the capture path and the event_id on the question path. It starts
as a random id and is rebound once the handler has parsed the real one. Never logs note
text, question text, response_url, tokens or secrets.
"""

import contextlib
import contextvars
import json
import logging
import re
import secrets
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import IO

_TRACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("slackkb_trace", default=None)
_VALID_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_QUIET_LOGGERS = ("botocore", "boto3", "urllib3")


def trace_id() -> str | None:
    """The current trace id, or None outside a trace."""
    return _TRACE.get()


@contextlib.contextmanager
def trace() -> Iterator[None]:
    """Run the body under a fresh random trace id; restore the previous one on exit."""
    token = _TRACE.set("r-" + secrets.token_hex(8))
    try:
        yield
    finally:
        _TRACE.reset(token)


def bind(trace_id: object) -> None:
    """Make trace_id the current id if it is 1-64 of [A-Za-z0-9_-]; otherwise do nothing."""
    if isinstance(trace_id, str) and _VALID_ID.fullmatch(trace_id):
        _TRACE.set(trace_id)


_RECORD_ATTR = "slackkb_trace_id"
_base_factory = logging.getLogRecordFactory()


def _record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    """Stamp each record with the trace id current when it is made, not when it is formatted."""
    record = _base_factory(*args, **kwargs)
    setattr(record, _RECORD_ATTR, _TRACE.get())
    return record


logging.setLogRecordFactory(_record_factory)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        created = datetime.fromtimestamp(record.created, tz=UTC)
        entry = {
            "ts": created.strftime("%Y-%m-%dT%H:%M:%S.") + f"{created.microsecond // 1000:03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, _RECORD_ATTR, None),
        }
        if record.exc_info:
            exc = record.exc_info[0]
            if exc is not None:
                entry["exc"] = exc.__name__
        return json.dumps(entry)


_handler: logging.Handler | None = None


def configure(stream: IO[str] | None = None) -> logging.Handler:
    """Install the one JSON handler on the root logger and quiet the AWS/HTTP loggers."""
    global _handler
    root = logging.getLogger()
    if _handler is not None:
        root.removeHandler(_handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    _handler = handler
    return handler
