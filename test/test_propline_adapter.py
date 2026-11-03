"""
Mission W1 tests — PropLine adapter (`src/odds_adapter.PropLineProvider`) and
the market-feed bridge (`src/services/market_feed`).

All tests are offline: the normalizer is pure, HTTP is monkeypatched, and the
composite fallback is exercised via dependency injection. No test touches the
langgraph agent graph, so this file runs in both CI and the local sandbox.
"""

from __future__ import annotations

import pytest

from src.odds_adapter import (
    BOOK_META,
    CompositeLiveOddsProvider,
    PropLineProvider,
    PropQuote,
)


def _sample_propline_response() -> dict:
    """Mock PropLine /v1/props payload (shape documented on PropLineProvider)."""
    return {
        "props": [
            {
                "event_id": "nba_2026_1029_bos_mil",
                "sport": "nba",
                "player_id": "giannis_antetokounmpo",
                "player_name": "Giannis Antetokounmpo",
                "team": "MIL",
                "opponent": "BOS",
                "market": "points",
                "line": 31.5,
                "books": {
                    "draftkings": {
                        "over_odds": -112,
                        "under_odds": -108,
                        "deeplink": "https://sportsbook.draftkings.com/nba/giannis-pts",
                        "updated_at": "2026-10-29T14:00:00Z",
                    },
                    "fanduel": {"over_odds": -110, "under_odds": -110},
                },
            },
            {
                "event_id": "nfl_2026_w9_lar_sea",
                "sport": "nfl",
                "player_id": "puka_nacua",
                "player_name": "Puka Nacua",
                "team": "LAR",
                "opponent": "SEA",
                "market": "receiving_yards",
                "line": 78.5,
                "books": {
                    "draftkings": {"over_odds": -115, "under_odds": -105},
                },
            },
        ]
    }


def _fd_last_for(quotes: list[PropQuote]) -> PropQuote:
    return [q for q in quotes if q.book_id == "fanduel"][0]


def test_propline_normalizer_parses_dk_fd_primary():
    provider = PropLineProvider(api_key="test_key")
    quotes = provider.normalize_response(_sample_propline_response(), now_ts="2026-10-29T14:00:01+00:00")

    # 2 props x (2 books + 1 book) = 3 quotes
    assert len(quotes) == 3

    giannis = [q for q in quotes if q.market == "points"]
    assert len(giannis) == 2
    # DK is the primary target -> emitted first for the same prop
    assert giannis[0].book_id == "draftkings"
    assert giannis[0].book == "DraftKings"
    assert giannis[0].book_short == "DK"
    assert giannis[0].line == 31.5
    assert giannis[0].over_odds == -112
    assert giannis[0].under_odds == -108
    assert giannis[0].verified is True
    assert giannis[0].observed_at == "2026-10-29T14:00:00Z"
    assert giannis[0].source_url == "https://sportsbook.draftkings.com/nba/giannis-pts"
    assert giannis[0].team == "MIL" and giannis[0].opponent == "BOS"
    assert len(giannis[0].receipt_id) == 16
    assert giannis[0].quote_id.startswith("propline_nba_2026_1029_bos_mil_draftkings_")

    fd = _fd_last_for(giannis)
    assert fd.book == "FanDuel"
    assert fd.over_odds == -110 and fd.under_odds == -110

    puka = [q for q in quotes if q.market == "receiving_yards"][0]
    assert puka.book_id == "draftkings"
    assert puka.line == 78.5 and puka.over_odds == -115 and puka.under_odds == -105


def test_propline_normalizer_rejects_malformed_entries():
    provider = PropLineProvider(api_key="test_key")
    data = {
        "props": [
            {"market": "points", "line": "abc", "books": {}},            # bad line
            {"market": "corners", "line": 2.5, "books": {"draftkings": {"over_odds": -110, "under_odds": -110}}},  # unmapped market
            {"market": "points", "line": 0.0, "books": {"draftkings": {"over_odds": -110, "under_odds": -110}}},   # non-positive line
            {"market": "points", "line": 20.5, "books": {"fanduel": {"available": False, "over_odds": -110, "under_odds": -110}}},  # suspended book
            {"market": "points", "line": 20.5, "books": {"fanduel": {"over_odds": None, "under_odds": -110}}},  # bad odds
            "not-a-dict",                                                # junk entry
        ]
    }
    quotes = provider.normalize_response(data, now_ts="2026-10-29T14:00:01+00:00")
    assert quotes == []

    # Non-dict payload degrades to empty, never raises
    assert provider.normalize_response([1, 2, 3], now_ts="x") == []
    assert provider.normalize_response({}, now_ts="x") == []


def test_propline_fetch_handles_missing_key_and_http_failures(monkeypatch):
    # 1. Missing key -> no fetch, empty list
    provider = PropLineProvider(api_key=None)
    monkeypatch.delenv("PROPLINE_API_KEY", raising=False)
    assert provider.fetch_quotes(season=2026, week=9) == []

    # 2. 401 / 429 -> graceful empty (composite falls through to The Odds API)
    class _Resp:
        def __init__(self, status: int):
            self.status_code = status

        def raise_for_status(self):
            raise AssertionError("raise_for_status must not be reached for 401/429")

    provider = PropLineProvider(api_key="bad_key")
    for status in (401, 429):
        monkeypatch.setattr(
            "requests.get", lambda *a, _s=status, **k: _Resp(_s)
        )
        assert provider.fetch_quotes(season=2026, week=9) == []

    # 3. Network exception -> graceful empty
    def _boom(*a, **k):
        raise ConnectionError("propline down")

    monkeypatch.setattr("requests.get", _boom)
    assert provider.fetch_quotes(season=2026, week=9) == []

    # 4. Happy path: real response parsed through the pure normalizer
    class _OkResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _sample_propline_response()

    captured: dict = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _OkResp()

    monkeypatch.setattr("requests.get", _fake_get)
    quotes = provider.fetch_quotes(season=2026, week=9, game_id="nba_2026_1029_bos_mil")
    assert len(quotes) == 3
    assert captured["url"] == "https://api.propline.com/v1/props"
    assert captured["params"]["season"] == 2026
    assert captured["headers"]["Authorization"] == "Bearer bad_key"


def test_quote_to_raw_ingest_mapping_and_sport_inference():
    from src.services.market_feed import quote_prop_id, quote_sport, quote_to_raw_ingest

    provider = PropLineProvider(api_key="k")
    quotes = provider.normalize_response(_sample_propline_response(), now_ts="2026-10-29T14:00:01+00:00")
    giannis = [q for q in quotes if q.market == "points"][0]
    puka = [q for q in quotes if q.market == "receiving_yards"][0]

    assert quote_sport(giannis) == "nba"
    assert quote_sport(puka) == "nfl"
    assert quote_prop_id(giannis) == "giannis_antetokounmpo:points"

    raw = quote_to_raw_ingest(giannis)
    assert raw["venue_type"] == "sportsbook"
    assert raw["book"] == "DraftKings"
    assert raw["line"] == 31.5
    assert raw["is_live"] is True
    assert len(raw["source_hash"]) == 64
    assert raw["player_id"] == "giannis_antetokounmpo"


def test_push_quotes_dual_writes_and_isolates_per_quote_failures():
    from src.services.market_feed import push_quotes_to_truth

    provider = PropLineProvider(api_key="k")
    quotes = provider.normalize_response(_sample_propline_response(), now_ts="2026-10-29T14:00:01+00:00")
    assert len(quotes) == 3

    pushed_odds: list[dict] = []
    ingested: list[dict] = []

    class _FlakyTruth:
        def upsert_last_known_odds(self, row: dict):
            if row.get("book") == "DraftKings" and row.get("market") == "points":
                # First quote (DK primary) fails -> must not block the rest of the batch
                raise RuntimeError("transient truth store hiccup")
            pushed_odds.append(row)

    class _StubIngest:
        def ingest_quote(self, raw, now=None):
            ingested.append(raw)

    summary = push_quotes_to_truth(quotes, truth=_FlakyTruth(), market_agent=_StubIngest())
    assert summary["ingested"] == 2
    assert summary["failed"] == 1
    assert len(ingested) == 2
    assert all(row["venue_type"] == "sportsbook" for row in pushed_odds)


class _FailingProvider:
    """Provider stub that always raises — simulates a dead PropLine API."""

    api_key = "configured"

    def fetch_quotes(self, season, week, game_id=None):
        raise ConnectionError("propline exploded")


class _StubProvider:
    api_key = "configured"

    def __init__(self, quotes):
        self._quotes = quotes

    def fetch_quotes(self, season, week, game_id=None):
        return list(self._quotes)


def _stub_quote(book: str) -> PropQuote:
    return PropQuote(
        quote_id=f"stub_{book}",
        book=book,
        market="points",
        player_raw_name="Test Player",
        team="MIL",
        opponent="BOS",
        line=25.5,
        over_odds=-110,
        under_odds=-110,
        observed_at="2026-10-29T14:00:00+00:00",
        source=f"stub ({book})",
        verified=True,
        receipt_id="0123456789abcdef",
        book_id=book.lower(),
    )


def test_composite_falls_back_when_propline_fails(monkeypatch):
    comp = CompositeLiveOddsProvider(api_key="unused")
    # Dependency-inject failure + fallback providers; no network involved.
    comp.propline = _FailingProvider()
    comp.selected = None
    comp.the_odds_api = _StubProvider([_stub_quote("Pinnacle")])
    comp.bovada = _StubProvider([])

    quotes = comp.fetch_quotes(season=2026, week=9)
    assert [q.book for q in quotes] == ["Pinnacle"]


def test_composite_prefers_propline_when_healthy(monkeypatch):
    comp = CompositeLiveOddsProvider(api_key="unused")
    comp.propline = _StubProvider([_stub_quote("DraftKings"), _stub_quote("FanDuel")])
    comp.selected = None
    comp.the_odds_api = _StubProvider([_stub_quote("Pinnacle")])
    comp.bovada = _StubProvider([])

    quotes = comp.fetch_quotes(season=2026, week=9)
    assert [q.book for q in quotes] == ["DraftKings", "FanDuel", "Pinnacle"]


def test_propline_registered_in_provider_registry():
    from src.odds_adapter import PROVIDER_REGISTRY

    assert PROVIDER_REGISTRY.get("propline") is PropLineProvider
    assert BOOK_META["draftkings"]["short"] == "DK"
    assert BOOK_META["fanduel"]["short"] == "FD"
