"""Foundation Freeze — tests for src/observability (structured JSON logging).

Covers: JSON line shape, request-id contextvar propagation, idempotent
configure_logging, and the ASGI RequestContextMiddleware (honor-or-generate
X-Request-ID, echo on response, completion log with method/path/status/
duration_ms). Uses a minimal FastAPI app so the middleware is tested in
isolation from the production app's routes.
"""

from __future__ import annotations

import json
import logging

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.observability.logging import (  # noqa: E402
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    bind_request_id,
    clear_request_id,
    configure_logging,
    get_logger,
    get_request_id,
    new_request_id,
)


@pytest.fixture()
def capture():
    """Install a JSON handler on a scratch logger and capture its lines."""
    class _Sink:
        def __init__(self):
            self.lines: list[str] = []

        def write(self, s: str) -> int:
            if s.strip():
                self.lines.append(s.strip())
            return len(s)

        def flush(self) -> None:
            pass

    sink = _Sink()
    logger = configure_logging(logger_name="propstein.test", stream=sink, level=logging.DEBUG)
    return logger, sink


class TestJsonLines:
    def test_line_is_valid_json_with_required_keys(self, capture):
        logger, sink = capture
        logger.info("hello %s", "world")
        assert len(sink.lines) == 1
        payload = json.loads(sink.lines[0])
        assert payload["msg"] == "hello world"
        for key in ("ts", "level", "logger", "msg", "request_id"):
            assert key in payload
        assert payload["level"] == "INFO"
        assert payload["logger"] == "propstein.test"

    def test_extras_become_fields(self, capture):
        logger, sink = capture
        logger.warning("odd feed", extra={"book": "draftkings", "staleness_min": 91.5})
        payload = json.loads(sink.lines[-1])
        assert payload["book"] == "draftkings"
        assert payload["staleness_min"] == 91.5

    def test_request_id_is_injected_from_context(self, capture):
        logger, sink = capture
        token = bind_request_id("req" + "a" * 28)
        try:
            logger.info("inside request")
        finally:
            clear_request_id()
        payload = json.loads(sink.lines[-1])
        assert payload["request_id"] == "req" + "a" * 28
        # and absent once the context is cleared
        logger.info("outside request")
        payload = json.loads(sink.lines[-1])
        assert payload["request_id"] is None

    def test_configure_logging_is_idempotent(self):
        a = configure_logging(logger_name="propstein.idem")
        before = len(a.handlers)
        b = configure_logging(logger_name="propstein.idem")
        assert b is a
        assert len(b.handlers) == before  # no duplicate handler added

    def test_get_logger_namespaces(self):
        assert get_logger("api.request").name == "propstein.api.request"
        assert get_logger("propstein.api").name == "propstein.api"


class TestRequestContextMiddleware:
    @pytest.fixture()
    def app(self):
        app = FastAPI()

        @app.get("/echo")
        def echo():
            return {"request_id": get_request_id()}

        @app.get("/health/live")
        def health():
            return {"ok": True}

        app.add_middleware(RequestContextMiddleware)
        return app

    def test_generates_and_echoes_request_id(self, app):
        with TestClient(app) as client:
            r = client.get("/echo")
        assert r.status_code == 200
        rid = r.headers[REQUEST_ID_HEADER]
        assert len(rid) >= 8
        assert r.json()["request_id"] == rid  # downstream saw the same id

    def test_two_requests_get_distinct_ids(self, app):
        with TestClient(app) as client:
            r1 = client.get("/echo")
            r2 = client.get("/echo")
        assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]

    def test_honors_safe_inbound_request_id(self, app):
        with TestClient(app) as client:
            r = client.get("/echo", headers={REQUEST_ID_HEADER: "trace-12345678"})
        assert r.headers[REQUEST_ID_HEADER] == "trace-12345678"
        assert r.json()["request_id"] == "trace-12345678"

    def test_replaces_unsafe_inbound_request_id(self, app):
        # Attack bytes in the header must never reach logs or the response.
        evil = "../../../etc/passwd<script>"
        with TestClient(app) as client:
            r = client.get("/echo", headers={REQUEST_ID_HEADER: evil})
        rid = r.headers[REQUEST_ID_HEADER]
        assert rid != evil
        assert rid.isalnum()

    def test_completion_log_carries_request_fields(self, app, capture):
        logger, sink = capture
        # Route the request logger into our capture sink
        from src.observability.logging import JsonFormatter

        handler = logging.StreamHandler(sink)
        handler.setFormatter(JsonFormatter())
        setattr(handler, "propstein_json", True)
        rl = logging.getLogger("propstein.api.request")
        rl.handlers = [handler]
        rl.setLevel(logging.INFO)
        rl.propagate = False
        try:
            with TestClient(app) as client:
                client.get("/echo")
            line = sink.lines[-1]
            payload = json.loads(line)
            assert payload["msg"] == "request complete"
            assert payload["method"] == "GET"
            assert payload["path"] == "/echo"
            assert payload["status"] == 200
            assert "duration_ms" in payload
            assert payload["request_id"]
        finally:
            rl.handlers = []
            rl.propagate = True

    def test_new_request_id_is_unique_and_hex(self):
        a, b = new_request_id(), new_request_id()
        assert a != b and len(a) == 32
        int(a, 16)
