"""Pluggable extension session state (revocation, rate limits, token version).

Redis is the shared store: the project already depends on ``redis`` and uses
``REDIS_URL`` for streams. The in-memory store is the default for tests and
single-process development. Production startup refuses a multi-worker process
that is still on the in-memory store — revocation would otherwise be local to
whichever worker issued the token.
"""

from __future__ import annotations

import logging
import os
import secrets
import time

_REVOKED_JTI: dict[str, float] = {}  # jti -> expiration epoch
_RATE_BUCKETS: dict[str, list[float]] = {}  # principal -> issuance timestamps
_SESSION_VERSIONS: dict[str, int] = {}  # principal -> stored session version

_WORKER_ENV_VARS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS")

# Atomic check-and-record. Returns {1, new_count} when the hit is stored and
# {0, current_count} when the principal is already at the limit. Rejected
# hits are not stored, matching the in-memory window.
RATE_LIMIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return {0, count}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
return {1, count + 1}
"""


class SessionStoreUnavailable(RuntimeError):
    """The shared store could not be read or written. Callers fail closed."""


class MemorySessionStore:
    """Process-local store. Tests clear the module dicts this object uses."""

    def __init__(
        self,
        revoked: dict[str, float] | None = None,
        buckets: dict[str, list[float]] | None = None,
        versions: dict[str, int] | None = None,
    ) -> None:
        self.revoked = _REVOKED_JTI if revoked is None else revoked
        self.buckets = _RATE_BUCKETS if buckets is None else buckets
        self.versions = _SESSION_VERSIONS if versions is None else versions

    def is_revoked(self, jti: str, now: float) -> bool:
        until = self.revoked.get(jti)
        return until is not None and until > now

    def revoke(self, jti: str, exp_epoch: float) -> None:
        self.revoked[jti] = float(exp_epoch)
        now = time.time()
        for key, until in list(self.revoked.items()):
            if until <= now:
                self.revoked.pop(key, None)

    def check_and_record(self, principal: str, now: float, window_seconds: float, limit: int) -> bool:
        window = [t for t in self.buckets.get(principal, []) if now - t < window_seconds]
        if len(window) >= limit:
            self.buckets[principal] = window
            return False
        window.append(now)
        self.buckets[principal] = window
        return True

    def session_version(self, principal: str) -> int:
        return max(env_session_version(), int(self.versions.get(principal, 1)))

    def set_session_version(self, principal: str, version: int) -> None:
        if int(version) < 1:
            raise ValueError("session version must be positive")
        self.versions[principal] = int(version)


class RedisSessionStore:
    """Redis-backed store. Keys expire with the token or the rate window."""

    def __init__(self, client) -> None:
        self._client = client

    def _call(self, fn):
        try:
            return fn()
        except SessionStoreUnavailable:
            raise
        except Exception:
            # Do not chain the driver error: connection failures can echo the URL.
            raise SessionStoreUnavailable("session store is unavailable")

    @staticmethod
    def _revoked_key(jti: str) -> str:
        return f"pste:ext:revoked:{jti}"

    @staticmethod
    def _rate_key(principal: str) -> str:
        return f"pste:ext:rate:{principal}"

    @staticmethod
    def _version_key(principal: str) -> str:
        return f"pste:ext:sv:{principal}"

    def is_revoked(self, jti: str, now: float) -> bool:
        def _read() -> bool:
            raw = self._client.get(self._revoked_key(jti))
            if raw is None:
                return False
            return float(raw) > now

        return self._call(_read)

    def revoke(self, jti: str, exp_epoch: float) -> None:
        ttl = max(1, int(float(exp_epoch) - time.time()))

        def _write() -> None:
            self._client.set(self._revoked_key(jti), str(float(exp_epoch)), ex=ttl)

        self._call(_write)

    def check_and_record(self, principal: str, now: float, window_seconds: float, limit: int) -> bool:
        member = f"{now:.6f}:{secrets.token_hex(4)}"

        def _write() -> bool:
            result = self._client.eval(
                RATE_LIMIT_LUA,
                1,
                self._rate_key(principal),
                str(now),
                str(window_seconds),
                str(limit),
                member,
            )
            allowed = int(result[0])
            return allowed == 1

        return self._call(_write)

    def session_version(self, principal: str) -> int:
        floor = env_session_version()

        def _read() -> int:
            raw = self._client.get(self._version_key(principal))
            stored = int(raw) if raw is not None else 1
            return max(floor, stored)

        return self._call(_read)

    def set_session_version(self, principal: str, version: int) -> None:
        if int(version) < 1:
            raise ValueError("session version must be positive")

        def _write() -> None:
            self._client.set(self._version_key(principal), str(int(version)))

        self._call(_write)


_active: MemorySessionStore | RedisSessionStore | None = None


def get_store() -> MemorySessionStore | RedisSessionStore:
    global _active
    if _active is None:
        _active = MemorySessionStore()
    return _active


def use_memory_store() -> MemorySessionStore:
    global _active
    _active = MemorySessionStore()
    return _active


def store_is_memory() -> bool:
    return isinstance(get_store(), MemorySessionStore)


def worker_count() -> int:
    """Highest configured web worker count. Unset means one worker."""
    count = 1
    for key in _WORKER_ENV_VARS:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"Refusing to start: {key} must be an integer") from exc
        if parsed < 1:
            raise RuntimeError(f"Refusing to start: {key} must be >= 1")
        count = max(count, parsed)
    return count


def env_session_version() -> int:
    raw = os.environ.get("EXTENSION_SESSION_VERSION")
    if raw is None or raw.strip() == "":
        return 1
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError("EXTENSION_SESSION_VERSION must be a positive integer") from exc
    if value < 1:
        raise RuntimeError("EXTENSION_SESSION_VERSION must be a positive integer")
    return value


def connect_redis(url: str):
    """Return a live Redis client, or None when dev may fall back to memory.

    Production never falls back: an unreachable Redis would silently split
    revocation across workers.
    """
    import redis

    from api.extension_router import _is_production

    client = redis.from_url(url, decode_responses=True, socket_connect_timeout=1.5)
    try:
        client.ping()
    except Exception as exc:
        if _is_production():
            raise RuntimeError(
                "Refusing to start: REDIS_URL is set but Redis is unreachable"
            ) from None
        logging.getLogger("propstein.security").warning(
            "REDIS_URL is set but Redis is unreachable (%s); using the in-memory session store",
            type(exc).__name__,
        )
        return None
    return client


def configure_from_env():
    """Select the store from EXTENSION_SESSION_STORE and REDIS_URL.

    ``auto`` (the default) uses Redis when REDIS_URL is set and memory otherwise.
    """
    choice = (os.environ.get("EXTENSION_SESSION_STORE") or "auto").strip().lower() or "auto"
    if choice not in {"auto", "memory", "redis"}:
        raise RuntimeError("EXTENSION_SESSION_STORE must be auto, memory, or redis")
    redis_url = (os.environ.get("REDIS_URL") or "").strip()
    if choice == "memory" or (choice == "auto" and not redis_url):
        return use_memory_store()
    if not redis_url:
        raise RuntimeError("EXTENSION_SESSION_STORE=redis requires REDIS_URL")
    client = connect_redis(redis_url)
    if client is None:
        return use_memory_store()
    global _active
    _active = RedisSessionStore(client)
    return _active
