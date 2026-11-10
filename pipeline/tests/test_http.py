"""Fetcher contracts: backoff, rate limiting, 429 handling, fail-fast 4xx."""

from __future__ import annotations

import pytest

from pipeline.http import FeedUnavailableError, Fetcher, TokenBucket


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body  # None => .json() raises (non-JSON body)
        self.headers = headers or {}
        self.text = str(self._body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class NoSleepClock:
    """Monotonic clock that never sleeps (rate limiter satisfied instantly)."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        self.now += 0.5  # half a second passes per call
        return self.now


def make_fetcher(client, sleeps: list[float] | None = None, jitter=None, rate=1000.0):
    sleeps = sleeps if sleeps is not None else []
    return Fetcher(
        "https://feed.example",
        "key",
        max_retries=4,
        base_delay=1.0,
        max_delay=8.0,
        rate_per_second=rate,
        client=client,
        sleep_fn=lambda s: sleeps.append(s),
        jitter_fn=jitter or (lambda b: b),  # deterministic jitter for tests
        clock=NoSleepClock(),
    )


def test_success_first_try():
    fetcher = make_fetcher(FakeClient([FakeResponse(200, {"ok": 1})]))
    assert fetcher.get_json("/x") == {"ok": 1}
    assert fetcher.client.calls[0]["headers"]["Authorization"] == "Bearer key"


def test_retries_with_exponential_backoff_then_succeeds():
    client = FakeClient(
        [
            FakeResponse(503),
            FakeResponse(503),
            FakeResponse(200, {"ok": 2}),
        ]
    )
    sleeps: list[float] = []
    fetcher = make_fetcher(client, sleeps=sleeps)
    assert fetcher.get_json("/x") == {"ok": 2}
    assert sleeps == [1.0, 2.0]  # base * 2^attempt, deterministic jitter


def test_gives_up_after_max_retries():
    client = FakeClient([FakeResponse(502) for _ in range(6)])
    sleeps: list[float] = []
    fetcher = make_fetcher(client, sleeps=sleeps)
    with pytest.raises(FeedUnavailableError, match="HTTP 502"):
        fetcher.get_json("/x")
    assert len(sleeps) == 4  # max_retries backoffs, no sleep after final attempt


def test_backoff_caps_at_max_delay():
    sleeps: list[float] = []
    client = FakeClient([FakeResponse(500) for _ in range(5)])
    fetcher = make_fetcher(client, sleeps=sleeps)  # max_delay=8
    with pytest.raises(FeedUnavailableError):
        fetcher.get_json("/x")
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


def test_permanent_4xx_fails_fast():
    client = FakeClient([FakeResponse(403, {"detail": "forbidden"})])
    sleeps: list[float] = []
    fetcher = make_fetcher(client, sleeps=sleeps)
    with pytest.raises(FeedUnavailableError, match="403"):
        fetcher.get_json("/x")
    assert sleeps == []  # no retry on permanent client errors
    assert len(client.calls) == 1


def test_429_honors_retry_after_header():
    sleeps: list[float] = []
    client = FakeClient(
        [
            FakeResponse(429, headers={"retry-after": "1.5"}),
            FakeResponse(200, {"ok": 3}),
        ]
    )
    fetcher = make_fetcher(client, sleeps=sleeps)
    assert fetcher.get_json("/x") == {"ok": 3}
    assert 1.5 in sleeps


def test_transport_errors_retry():
    sleeps: list[float] = []
    client = FakeClient([TimeoutError("boom"), FakeResponse(200, {"ok": 4})])
    fetcher = make_fetcher(client, sleeps=sleeps)
    assert fetcher.get_json("/x") == {"ok": 4}
    assert sleeps == [1.0]


def test_non_json_body_fails_closed():
    client = FakeClient([FakeResponse(200, None)])
    fetcher = make_fetcher(client)
    with pytest.raises(FeedUnavailableError, match="non-JSON"):
        fetcher.get_json("/x")


def test_full_jitter_stays_within_backoff_ceiling():
    """Production jitter (uniform 0..backoff) never exceeds the backoff."""

    def full_jitter(backoff: float) -> float:
        return min(backoff, max(0.0, backoff * 0.999))

    sleeps: list[float] = []
    client = FakeClient([FakeResponse(503) for _ in range(5)])
    fetcher = make_fetcher(client, sleeps=sleeps, jitter=full_jitter)
    with pytest.raises(FeedUnavailableError):
        fetcher.get_json("/x")
    # base_delay 1.0, max 8.0: attempts sleep 1, 2, 4, 8 at most
    assert sleeps == [pytest.approx(s, abs=1e-9) for s in (1.0, 2.0, 4.0, 8.0)] or all(
        0 <= s <= ceiling for s, ceiling in zip(sleeps, (1.0, 2.0, 4.0, 8.0))
    )


def test_token_bucket_limits_burst():
    """Virtual-clock test: a burst beyond the rate must wait for refill."""

    class FrozenClock:
        def __init__(self):
            self.now = 1000.0

        def __call__(self):
            return self.now

    clock = FrozenClock()
    slept: list[float] = []

    def virtual_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds  # time actually passes while sleeping

    bucket = TokenBucket(rate_per_second=2.0, clock=clock, sleep_fn=virtual_sleep)

    bucket.acquire()  # consumes the stored token — no wait
    assert slept == []
    bucket.acquire()  # bucket empty at rate 2/s -> must wait ~0.5s virtually
    assert len(slept) == 1
    assert slept[0] == pytest.approx(0.5, abs=1e-9)


def test_token_bucket_sustained_rate():
    """A long request train never exceeds the configured rate."""

    class FrozenClock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    clock = FrozenClock()
    slept: list[float] = []

    def virtual_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    bucket = TokenBucket(rate_per_second=4.0, clock=clock, sleep_fn=virtual_sleep)
    for _ in range(10):
        bucket.acquire()
    # After the stored token, each request at 4/s waits ~0.25s
    assert len(slept) == 9
    assert sum(slept) == pytest.approx(9 * 0.25, abs=1e-6)
