"""PropStein pipeline — rate-limited HTTP fetcher.

Production semantics:
  - token-bucket rate limiting (default 2 req/s)
  - retries with exponential backoff + full jitter (injectable for tests)
  - honors Retry-After on HTTP 429
  - hard timeout per request
  - permanent 4xx fails fast (no retry storm)

Everything raises FeedUnavailableError on final failure — the pipeline then
fails closed; it never fabricates data to fill a gap (charter rule 10).
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx


class FeedUnavailableError(RuntimeError):
    """The feed could not be fetched after all retries."""


class TokenBucket:
    """Minimal token-bucket rate limiter (1 token = 1 request)."""

    def __init__(self, rate_per_second: float, clock: Callable[[], float] = time.monotonic) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate must be positive")
        self._rate = rate_per_second
        self._tokens = 1.0
        self._last = clock()
        self._clock = clock

    def acquire(self) -> None:
        while True:
            now = self._clock()
            self._tokens = min(1.0, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate
            time.sleep(max(0.0, wait))


class Fetcher:
    """GET JSON with retries, backoff, and rate limiting."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        timeout: float = 10.0,
        max_retries: int = 5,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        rate_per_second: float = 2.0,
        client: Any = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[float], float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.bucket = TokenBucket(rate_per_second, clock=clock)
        self.client = client or httpx.Client(timeout=timeout)
        self.sleep = sleep_fn
        self.jitter = jitter_fn or (lambda backoff: random.uniform(0.0, backoff))
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Fetch and parse one JSON document. Raises FeedUnavailableError on failure."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        last_status: int | None = None

        for attempt in range(self.max_retries + 1):
            self.bucket.acquire()
            try:
                response = self.client.get(url, params=params, headers=self._headers(), timeout=self.timeout)
            except Exception as exc:  # transport-level failure (timeout, DNS, reset)
                last_error = exc
                last_status = None
            else:
                status = response.status_code
                if 200 <= status < 300:
                    try:
                        return response.json()
                    except Exception as exc:
                        raise FeedUnavailableError(f"non-JSON body from {url}: {exc}") from exc
                last_status = status
                if status == 429:
                    retry_after = _parse_retry_after(response.headers.get("retry-after"))
                    if retry_after is not None:
                        self.sleep(retry_after)
                        continue
                if 400 <= status < 500 and status != 429:
                    # Permanent client error — retrying will not help.
                    raise FeedUnavailableError(f"HTTP {status} from {url}: {getattr(response, 'text', '')[:200]}")
                last_error = RuntimeError(f"HTTP {status} from {url}")

            if attempt >= self.max_retries:
                break
            backoff = min(self.base_delay * (2**attempt), self.max_delay)
            self.sleep(self.jitter(backoff))

        detail = f"status={last_status}" if last_status is not None else "transport error"
        raise FeedUnavailableError(f"feed unavailable after {self.max_retries + 1} attempts ({detail}): {last_error}")


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
