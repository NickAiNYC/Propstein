"""PropStein Observability — structured JSON logging with request IDs.

Foundation-freeze deliverable (master prompt §1: 'structured JSON logging
with request IDs'). Stdlib only — no structlog, no new supply-chain surface
in requirements.txt.

Public surface (FROZEN with quant.v1):
    configure_logging()      — idempotent root logging setup (JSON lines)
    get_logger(name)         — namespaced logger
    new_request_id()         — 32-hex request id
    get_request_id()         — current contextvar value or None
    bind_request_id(rid)     — set the contextvar, returns reset token
    reset_request_id(token)  — reset it (tests / middleware teardown)
    RequestContextMiddleware — ASGI middleware: honor-or-generate
                               X-Request-ID, echo it on the response, log
                               method/path/status/duration_ms per request.
"""

from src.observability.logging import (  # noqa: F401
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    bind_request_id,
    clear_request_id,
    configure_logging,
    get_logger,
    get_request_id,
    new_request_id,
    reset_request_id,
)

__all__ = [
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "bind_request_id",
    "clear_request_id",
    "configure_logging",
    "get_logger",
    "get_request_id",
    "new_request_id",
    "reset_request_id",
]
