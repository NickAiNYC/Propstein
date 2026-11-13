"""Kalshi NBA fallback: parsing, main-line choice, fail-closed writes, publishing."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import fetch_kalshi_nba as k  # noqa: E402

DAY = "2026-11-13"
ESPN = {"events": [
    {"id": "1", "date": "2026-11-14T01:00Z", "competitions": [{"competitors": [
        {"homeAway": "away", "team": {"abbreviation": "ATL"}}, {"homeAway": "home", "team": {"abbreviation": "CHI"}}]}]},
    {"id": "2", "date": "2026-11-14T03:00Z", "competitions": [{"competitors": [
        {"homeAway": "away", "team": {"abbreviation": "POR"}}, {"homeAway": "home", "team": {"abbreviation": "SAC"}}]}]},
]}
EVENTS = [{"event_ticker": "KXNBAPTS-26NOV13ATLCHI", "sub_title": "ATL vs CHI (Nov 13)"},
          {"event_ticker": "KXNBAPTS-26NOV14BOSNYK", "sub_title": "BOS vs NYK (Nov 14)"}]


def market(player_seg, name, k_, bid, ask, no_ask, event="KXNBAPTS-26NOV13ATLCHI"):
    return {"ticker": f"{event}-{player_seg}-{k_}", "event_ticker": event, "title": f"{name}: {k_}+ points",
            "strike_type": "greater", "floor_strike": k_ - 0.5,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "no_ask_dollars": no_ask}


MARKETS = [
    market("CHIJSMITH25", "Jalen Smith", 10, "0.80", "0.84", "0.20"),
    market("CHIJSMITH25", "Jalen Smith", 15, "0.48", "0.52", "0.52"),
    market("CHIJSMITH25", "Jalen Smith", 20, "0.15", "0.19", "0.85"),
    market("ATLTYOUNG11", "Trae Young", 25, "0.0000", "0.95", "1.00"),   # placeholder
    market("ATLDMURRAY5", "Dejounte Murray", 20, "0.30", "0.55", "0.70"),  # spread too wide
    market("BOSJTATUM0", "Jayson Tatum", 25, "0.50", "0.52", "0.50", event="KXNBAPTS-26NOV14BOSNYK"),  # other day
]


def test_schedule_maps_espn_codes_and_keeps_only_the_slate_day():
    games = k.normalize_espn_games(ESPN, DAY)
    assert [g["game_id"] for g in games] == ["nba-20261113-ATL-CHI", "nba-20261113-POR-SAC"]
    assert games[0]["gametime_et"] == "20:00" and games[0]["_fixture"] is False
    assert k.normalize_espn_games(ESPN, "2026-11-14") == []
    with pytest.raises(ValueError, match="unmapped team"):
        k.normalize_espn_games({"events": [{**ESPN["events"][0], "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "XXX"}},
            {"homeAway": "home", "team": {"abbreviation": "CHI"}}]}]}]}, DAY)


def test_one_two_sided_main_line_per_player_and_nothing_invented():
    games = k.normalize_espn_games(ESPN, DAY)
    quotes = k.build_quotes(DAY, games, EVENTS, MARKETS, "2026-11-13T16:00:00Z")
    assert [(q["player_name"], q["line"]) for q in quotes] == [("Jalen Smith", 14.5)]
    q = quotes[0]
    assert (q["team"], q["opponent"], q["game_id"]) == ("CHI", "ATL", "nba-20261113-ATL-CHI")
    assert (q["over_odds"], q["under_odds"]) == (-108, -108)
    assert q["book"] == "Kalshi" and q["verified"] is False and q["_fixture"] is False
    assert q["provider_quote_id"] == "KXNBAPTS-26NOV13ATLCHI-CHIJSMITH25-15"


def test_run_writes_nothing_without_quotes_and_publishes_through_the_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(k, "VIEWER", tmp_path)
    responses = {k.ESPN: ESPN}

    def fake_get(url, params=None):
        if url in responses:
            return responses[url]
        kind = url.rsplit("/", 1)[1]
        return {kind: EVENTS if kind == "events" else markets[0]}

    markets = [[MARKETS[3]]]  # placeholder only
    monkeypatch.setattr(k, "get_json", fake_get)
    assert k.run(DAY, 0.10) == 3
    assert list(tmp_path.iterdir()) == []

    markets[0] = MARKETS
    assert k.run(DAY, 0.10) == 0
    odds = json.loads((tmp_path / f"nba_odds_{DAY}.json").read_text())
    games = json.loads((tmp_path / f"nba_games_{DAY}.json").read_text())
    assert odds["source"] == "kalshi" and odds["total_quotes"] == 1 and odds["slate"] == DAY
    assert len(games) == 2 and (tmp_path / f"nba_odds_{DAY}.manifest.json").exists()

    monkeypatch.setattr(k, "get_json", lambda url, params=None: (_ for _ in ()).throw(OSError("down")))
    assert k.run(DAY, 0.10) == 5


def test_publisher_accepts_one_reference_book_and_refuses_mixed_or_unknown(tmp_path, monkeypatch):
    import publish_nba_market_slate as pub
    monkeypatch.setattr(pub, "VIEWER", tmp_path)
    monkeypatch.setattr(pub, "write_manifest", lambda now: None)
    games = k.normalize_espn_games(ESPN, DAY)
    (tmp_path / f"nba_games_{DAY}.json").write_text(json.dumps(games))
    quote = k.build_quotes(DAY, games, EVENTS, MARKETS, "2026-11-13T16:00:00Z")[0]

    def write(quotes):
        (tmp_path / f"nba_odds_{DAY}.json").write_text(json.dumps({
            "slate": DAY, "_fixture": False, "feed_status": "live-unverified",
            "updated_at": "2026-11-13T16:00:00Z", "total_quotes": len(quotes), "quotes": quotes}))

    write([quote])
    pub.publish(DAY)
    assert json.loads((tmp_path / f"nba_slate_{DAY}.json").read_text()) == []
    write([quote, {**quote, "quote_id": "x", "book": "FanDuel"}])
    with pytest.raises(ValueError, match="one reference book"):
        pub.publish(DAY)
    write([{**quote, "book": "Bovada"}])
    with pytest.raises(ValueError, match="unsupported book"):
        pub.publish(DAY)
