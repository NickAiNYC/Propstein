"""NbaComProvider contracts — free/keyless stats.nba.com path (D7).

The stats.nba.com transport is stubbed; nothing here touches the network.
Mirror of the balldontlie provider test matrix: fail-closed errors,
politeness spacing, normalization fidelity, dataset compatibility.
"""

import gzip
import json

import pytest

from nba_model.data.dataset import build_dataset
from nba_model.data.nbacom import NbaComProvider, _decode_body
from nba_model.data.providers import ProviderNetworkError, RateLimitError

LGF_HEADERS = [
    "SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME",
    "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS",
]
BOX_HEADERS = [
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "START_POSITION",
    "MIN", "PTS", "REB", "AST", "FG3M", "FGM", "FGA", "FTM", "FTA",
    "OREB", "TOV", "COMMENT",
]


def _rs(name, headers, rows):
    return {"name": name, "headers": headers,
            "rowSet": [[r[h] for h in headers] for r in rows]}


def _lgf_payload(rows):
    return {"resource": "leaguegamefinder",
            "resultSets": [_rs("LeagueGameFinderResults", LGF_HEADERS, rows)]}


def _box_payload(rows):
    return {"resource": "boxscoretraditionalv2",
            "resultSets": [_rs("PlayerStats", BOX_HEADERS, rows)]}


def _team_row(abbr, gid, matchup, pts, game_date="2026-11-02"):
    return {"SEASON_ID": "22026", "TEAM_ID": 1, "TEAM_ABBREVIATION": abbr,
            "TEAM_NAME": abbr, "GAME_ID": gid, "GAME_DATE": game_date,
            "MATCHUP": matchup, "WL": "W" if pts else None, "PTS": pts}


def _box_row(pid, name, abbr, min_, pts, pos="F"):
    return {"PLAYER_ID": pid, "PLAYER_NAME": name, "TEAM_ABBREVIATION": abbr,
            "START_POSITION": pos, "MIN": min_, "PTS": pts, "REB": 5, "AST": 3,
            "FG3M": 1, "FGM": 4, "FGA": 10, "FTM": 2, "FTA": 3, "OREB": 1,
            "TOV": 2, "COMMENT": "" if min_ else "DNP - Coach's Decision"}


def _transport_map(routes, calls=None):
    """routes: list of (url_substring, status, payload) matched in order."""
    log = calls if calls is not None else []

    def transport(url):
        log.append(url)
        for substring, status, payload in routes:
            if substring in url:
                return status, payload
        raise AssertionError(f"unexpected url {url}")
    return transport, log


def _provider(routes, sleeps, spacing=0.0):
    transport, log = _transport_map(routes)
    return NbaComProvider(transport=transport, sleep_fn=sleeps.append,
                          spacing_seconds=spacing), log


# ── happy path ──────────────────────────────────────────────────────────────
def test_keyless_happy_path_normalization():
    sleeps = []
    lgf = _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", 110),
        _team_row("LAL", "0022500001", "LAL vs. BOS", 118),
    ])
    box = _box_payload([
        _box_row("203999", "Jaylen Brown", "BOS", "34:30", 28),
        _box_row("201567", "Klay Thompson", "BOS", None, None, pos=""),
    ])
    provider, log = _provider(
        [("leaguegamefinder", 200, lgf), ("boxscoretraditionalv2", 200, box)],
        sleeps)
    world = provider.fetch_range(["2026-11-02"])

    # games
    assert len(world["games"]) == 1
    game = world["games"][0]
    assert game["game_id"] == "nba-0022500001"
    assert game["bdl_game_id"] == "0022500001"
    assert game["home_team"] == "LAL" and game["away_team"] == "BOS"
    assert game["home_team_score"] == 118 and game["away_team_score"] == 110
    assert game["status"] == "Final"
    assert game["game_date"] == "2026-11-02"   # ET slate key, used as-is
    assert game["_fixture"] is False and game["source"] == "stats_nba_com"

    # rows
    assert len(world["rows"]) == 2
    starter, dnp = world["rows"]
    assert starter["player_id"] == "nba-203999"
    assert starter["player_display_name"] == "Jaylen Brown"
    assert starter["minutes"] == 34.5          # '34:30' -> 34.5
    assert starter["minutes_raw"] == "34:30"
    assert starter["team"] == "BOS" and starter["opponent"] == "LAL"
    assert starter["is_home"] is False
    assert starter["position"] == "F"
    assert starter["pts"] == 28 and starter["rebounds"] == 5 and starter["tov"] == 2
    assert dnp["minutes"] == 0.0 and dnp["position"] is None
    assert dnp["pts"] is None                  # DNP row keeps null stats

    # politeness + keyless-by-design meta
    assert len(sleeps) == 2                    # one spacing sleep per successful call
    assert world["meta"]["source"] == "stats_nba_com"
    assert world["meta"]["_fixture"] is False
    assert world["meta"]["dates"] == ["2026-11-02"]
    assert "leaguegamefinder" in log[0] and "boxscoretraditionalv2" in log[1]


def test_scheduled_game_skips_boxscore_call():
    sleeps = []
    lgf = _lgf_payload([
        _team_row("BOS", "0022500002", "BOS @ LAL", None),
        _team_row("LAL", "0022500002", "LAL vs. BOS", None),
    ])
    provider, log = _provider(
        [("leaguegamefinder", 200, lgf), ("boxscoretraditionalv2", 200, _box_payload([]))],
        sleeps)
    world = provider.fetch_range(["2026-11-03"])
    assert world["games"][0]["status"] == "Scheduled"
    assert world["rows"] == []
    assert len(log) == 1                       # boxscore never called for unplayed games


def test_rows_feed_build_dataset_unchanged():
    """The whole point of the swap: dataset never learns which provider ran."""
    lgf = _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", 110),
        _team_row("LAL", "0022500001", "LAL vs. BOS", 118),
    ])
    box = _box_payload([
        _box_row("203999", "Jaylen Brown", "BOS", "34:30", 28),
        _box_row("201567", "Klay Thompson", "LAL", "28:15", 21, pos="G"),
    ])
    provider, _ = _provider(
        [("leaguegamefinder", 200, lgf), ("boxscoretraditionalv2", 200, box)],
        [])
    world = provider.fetch_range(["2026-11-02"])
    world.setdefault("odds", [])
    world.setdefault("injuries", [])
    df, meta = build_dataset(world["rows"], world["games"])
    assert meta["n_rows"] == 2 and meta["n_games"] == 1
    assert meta["source"] == "stats_nba_com"


# ── fail-closed matrix ──────────────────────────────────────────────────────
def test_429_backs_off_once_then_succeeds():
    sleeps = []
    lgf = _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", 110),
        _team_row("LAL", "0022500001", "LAL vs. BOS", 118),
    ])
    attempts = {"lgf": 0, "box": 0}
    log = []

    def transport(url):
        log.append(url)
        if "leaguegamefinder" in url:
            attempts["lgf"] += 1
            return (429, {}) if attempts["lgf"] == 1 else (200, lgf)
        attempts["box"] += 1
        return (429, {}) if attempts["box"] == 1 else (200, _box_payload([]))

    provider = NbaComProvider(transport=transport, sleep_fn=sleeps.append,
                              spacing_seconds=0.0)
    world = provider.fetch_range(["2026-11-02"])
    assert 60.0 in sleeps                       # the documented 60 s backoff
    assert len(log) == 4                        # 2 attempts per endpoint
    assert world["meta"]["source"] == "stats_nba_com"


def test_429_twice_raises_rate_limit_error():
    provider, _ = _provider([("leaguegamefinder", 429, {})], [])
    with pytest.raises(RateLimitError):
        provider.fetch_range(["2026-11-02"])


def test_403_blocked_ip_raises_network_error():
    provider, _ = _provider([("leaguegamefinder", 403, {})], [])
    with pytest.raises(ProviderNetworkError):
        provider.fetch_range(["2026-11-02"])


def test_missing_result_set_fails_closed():
    provider, _ = _provider([("leaguegamefinder", 200, {"resource": "leaguegamefinder"})], [])
    with pytest.raises(ProviderNetworkError):
        provider.fetch_range(["2026-11-02"])


def test_lone_team_row_fails_closed():
    provider, _ = _provider([("leaguegamefinder", 200, _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", 110),
    ]))], [])
    with pytest.raises(ProviderNetworkError):
        provider.fetch_range(["2026-11-02"])


def test_no_home_row_fails_closed():
    provider, _ = _provider([("leaguegamefinder", 200, _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", 110),
        _team_row("LAL", "0022500001", "LAL @ BOS", 118),
    ]))], [])
    with pytest.raises(ProviderNetworkError):
        provider.fetch_range(["2026-11-02"])


# ── robustness ──────────────────────────────────────────────────────────────
def test_column_order_independence():
    shuffled = ["PTS", "MATCHUP", "GAME_ID", "TEAM_ABBREVIATION", "GAME_DATE", "WL", "TEAM_NAME", "TEAM_ID", "SEASON_ID"]
    payload = {"resource": "leaguegamefinder",
               "resultSets": [_rs("LeagueGameFinderResults", shuffled, [
                   {"PTS": 110, "MATCHUP": "BOS @ LAL", "GAME_ID": "0022500001",
                    "TEAM_ABBREVIATION": "BOS", "GAME_DATE": "2026-11-02",
                    "WL": "L", "TEAM_NAME": "BOS", "TEAM_ID": 1, "SEASON_ID": "22026"},
                   {"PTS": 118, "MATCHUP": "LAL vs. BOS", "GAME_ID": "0022500001",
                    "TEAM_ABBREVIATION": "LAL", "GAME_DATE": "2026-11-02",
                    "WL": "W", "TEAM_NAME": "LAL", "TEAM_ID": 2, "SEASON_ID": "22026"},
               ])]}
    provider, _ = _provider([
        ("leaguegamefinder", 200, payload),
        ("boxscoretraditionalv2", 200, _box_payload([])),
    ], [])
    world = provider.fetch_range(["2026-11-02"])
    game = world["games"][0]
    assert game["home_team"] == "LAL" and game["away_team"] == "BOS"


def test_one_sided_score_marks_in_progress():
    lgf = _lgf_payload([
        _team_row("BOS", "0022500001", "BOS @ LAL", None),
        _team_row("LAL", "0022500001", "LAL vs. BOS", 61),
    ])
    provider, log = _provider([
        ("leaguegamefinder", 200, lgf),
        ("boxscoretraditionalv2", 200, _box_payload([])),
    ], [])
    world = provider.fetch_range(["2026-11-02"])
    assert world["games"][0]["status"] == "InProgress"
    assert len(log) == 1                        # live game: no boxscore fetch yet


# ── helpers ─────────────────────────────────────────────────────────────────
def test_season_key_boundaries():
    f = NbaComProvider._season_key
    assert f("2026-10-22") == "2026-27"   # season start
    assert f("2026-06-05") == "2025-26"   # finals
    assert f("2026-08-15") == "2026-27"   # offseason -> upcoming season
    assert f("2027-01-03") == "2026-27"   # calendar year rolls, season doesn't


def test_decode_body_gzip_and_plain():
    raw = json.dumps({"ok": True}).encode()
    assert _decode_body(raw) == {"ok": True}
    assert _decode_body(gzip.compress(raw)) == {"ok": True}
