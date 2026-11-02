"""PropStein Observability — structured JSON logging with request IDs.

Foundation-freeze deliverable (master prompt §1: 'structured JSON logging
with request IDs'). Stdlib only — no structlog, no new supply-chain surface
in requirements.txt.

Log line shape (stable — pipelines may key on these fields):
    {"ts": "...", "level": "INFO", "logger": "propstein.api",
     "msg": "...", "request_id": "..." | null, ...extras}

Request completion lines add: method, path, status, duration_ms.
/health and /api/health log at DEBUG so liveness probes do not spam INFO.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Optional

REQUEST_ID_HEADER = "X-Request-ID"

_REQUEST_ID: ContextVar[Optional[str]] = ContextVar("propstein_request_id", default=None)

#: Sanitize inbound request ids: 8-64 chars of [A-Za-z0-9_-] only. Anything
#: else is replaced — never echo attacker-controlled bytes into log headers.
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: LogRecord attributes that are NOT payload; everything else on the record
#: becomes an extra field in the JSON line.
_RESERVED_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "stacklevel", "thread", "threadName",
        "taskName",
    }
)

_HANDLER_MARKER = "propstein_json"  # idempotency marker on handlers we own


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> Optional[str]:
    return _REQUEST_ID.get()


def bind_request_id(request_id: str) -> Token:
    """Bind the request id into the current context. Returns the reset token."""
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token) -> None:
    _REQUEST_ID.reset(token)


def clear_request_id() -> None:
    """Unconditional clear (no token) — for test teardown only."""
    _REQUEST_ID.set(None)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line. request_id is injected from the
    contextvar at format time, so every line inside a request is correlated
    without threading the id through every call site.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_") and key not in payload:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    *,
    level: int = logging.INFO,
    stream: Any = sys.stdout,
    logger_name: str = "",
) -> logging.Logger:
    """Idempotent: replaces any handler we previously installed, never
    duplicates, and leaves foreign handlers (pytest capture, uvicorn's own)
    alone. Returns the logger it configured (root by default)."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    ours = [h for h in logger.handlers if getattr(h, _HANDLER_MARKER, False)]
    for handler in ours:
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARKER, True)
    logger.addHandler(handler)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger under the propstein.* tree."""
    if not name.startswith("propstein"):
        name = f"propstein.{name.lstrip('.')}"
    return logging.getLogger(name)


class RequestContextMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware overhead).

    Per request:
      1. honor an inbound X-Request-ID if it matches the safe pattern,
         otherwise generate one;
      2. bind it into the contextvar so all downstream logs carry it;
      3. echo it on the response;
      4. emit one completion line: method, path, status, duration_ms.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        inbound = headers.get(REQUEST_ID_HEADER.lower(), "")
        request_id = inbound if _SAFE_REQUEST_ID_RE.fullmatch(inbound) else new_request_id()
        token = bind_request_id(request_id)

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        quiet = path.startswith("/health") or path.startswith("/api/health")
        started = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                headers_list = message.setdefault("headers", [])
                headers_list.append((REQUEST_ID_HEADER.encode("latin-1"), request_id.encode("latin-1")))
            await send(message)

        log = get_logger("api.request")
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            log.log(
                logging.DEBUG if quiet else logging.INFO,
                "request complete",
                extra={
                    "method": method,
                    "path": path,
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                },
            )
            reset_request_id(token)
