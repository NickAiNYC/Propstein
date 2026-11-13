import json
from datetime import datetime, timezone

from scripts.check_data_health import (SWEEP_SOURCE, check_nba_lines, check_nfl,
                                       check_odds_api_credits, main, render, run_checks)

NOW = datetime(2026, 11, 13, 18, 30, tzinfo=timezone.utc)
KEY = "secret-key-123"


def fake_fetch(status, headers=None, body=""):
    return lambda key: (status, headers or {}, body)


# ---- Odds API credits ---------------------------------------------------------

def test_credits_ok_and_warn_thresholds():
    ok = check_odds_api_credits(KEY, fake_fetch(200, {"X-Requests-Remaining": "420", "x-requests-used": "80"}))
    assert ok.status == "OK" and "420 credits remaining" in ok.detail
    low = check_odds_api_credits(KEY, fake_fetch(200, {"x-requests-remaining": "12"}))
    assert low.status == "WARN"
    zero = check_odds_api_credits(KEY, fake_fetch(200, {"x-requests-remaining": "0"}))
    assert zero.status == "FAIL"


def test_exhausted_key_fails_with_reason():
    body = '{"message":"Usage quota has been reached","error_code":"OUT_OF_USAGE_CREDITS"}'
    r = check_odds_api_credits(KEY, fake_fetch(401, {}, body))
    assert r.status == "FAIL" and "out of credits" in r.detail


def test_missing_key_skips_and_network_error_never_leaks_key():
    assert check_odds_api_credits(None).status == "SKIP"

    def boom(key):
        raise OSError(f"connection reset for https://x/?apiKey={key}")
    r = check_odds_api_credits(KEY, boom)
    assert r.status == "WARN" and KEY not in r.detail


# ---- NBA ------------------------------------------------------------------------

def write_nba(viewer, day, updated_at, fixture=False, quotes=80):
    (viewer / f"nba_odds_{day}.json").write_text(json.dumps(
        {"updated_at": updated_at, "_fixture": fixture, "total_quotes": quotes}))


def test_nba_stale_fails_fresh_passes_and_fixtures_ignored(tmp_path):
    write_nba(tmp_path, "2026-11-07", "2026-11-07T19:52:16Z")
    write_nba(tmp_path, "2026-11-12", "2026-11-12T16:00:00Z", fixture=True)
    (tmp_path / "nba_odds_2026-11-07.manifest.json").write_text("{}")
    stale = check_nba_lines(tmp_path, NOW)
    assert stale.status == "FAIL" and "2026-11-07" in stale.detail

    write_nba(tmp_path, "2026-11-13", "2026-11-13T16:05:00Z")
    fresh = check_nba_lines(tmp_path, NOW)
    assert fresh.status == "OK" and "2026-11-13" in fresh.detail


def test_nba_offseason_skips_and_no_real_files_fails(tmp_path):
    assert check_nba_lines(tmp_path, datetime(2026, 8, 1, tzinfo=timezone.utc)).status == "SKIP"
    assert check_nba_lines(tmp_path, NOW).status == "FAIL"


# ---- NFL ------------------------------------------------------------------------

def nfl_viewer(tmp_path, gameday="2026-11-16", feed_at="2026-11-13T17:00:00Z",
               injuries_at="2026-11-13T10:00:00Z", sportsbook=0):
    (tmp_path / "feeds").mkdir(exist_ok=True)
    (tmp_path / "feeds/slate-index.json").write_text(json.dumps({"sports": {"nfl": {
        "default_slate": "2026_w10", "slates": {"2026_w10": {
            "games": "games.json", "injuries": "injuries.json"}}}}}))
    (tmp_path / "games.json").write_text(json.dumps([{"gameday": gameday}]))
    quotes = [{"source": "Polymarket CLOB"}] + [{"source": SWEEP_SOURCE}] * sportsbook
    (tmp_path / "live_odds_feed.json").write_text(json.dumps(
        {"updated_at": feed_at, "polymarket_quotes_count": 1, "quotes": quotes}))
    (tmp_path / "injuries.json").write_text(json.dumps({"as_of": injuries_at}))
    return tmp_path


def by_name(results):
    return {r.name: r for r in results}


def test_nfl_active_window_all_fresh(tmp_path):
    r = by_name(check_nfl(nfl_viewer(tmp_path, sportsbook=3), NOW))
    assert r["nfl_odds_feed"].status == "OK"
    assert r["nfl_sportsbook"].status == "OK"
    assert r["nfl_injuries"].status == "OK"


def test_nfl_stale_feed_and_injuries_fail_and_polymarket_only_warns(tmp_path):
    r = by_name(check_nfl(nfl_viewer(tmp_path, feed_at="2026-11-13T08:00:00Z",
                                     injuries_at="2026-11-11T00:00:00Z"), NOW))
    assert r["nfl_odds_feed"].status == "FAIL"
    assert r["nfl_injuries"].status == "FAIL"
    assert r["nfl_sportsbook"].status == "WARN"


def test_nfl_outside_window_skips(tmp_path):
    r = check_nfl(nfl_viewer(tmp_path, gameday="2026-12-31", feed_at="2026-10-01T00:00:00Z"), NOW)
    assert [x.status for x in r] == ["SKIP"]


# ---- report ---------------------------------------------------------------------

def test_report_and_exit_code(tmp_path, monkeypatch, capsys):
    viewer = nfl_viewer(tmp_path, sportsbook=1)
    write_nba(viewer, "2026-11-13", "2026-11-13T16:05:00Z")
    results = run_checks(viewer, NOW, KEY, fake_fetch(200, {"x-requests-remaining": "300"}))
    assert all(r.status == "OK" for r in results)
    md = render(results, NOW)
    assert md.count("| `") == 5 and KEY not in md

    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    summary = tmp_path / "summary.md"
    assert main(["--viewer", str(viewer), "--now", "2026-11-13T18:30:00Z", "--summary", str(summary)]) == 0
    assert "nba_lines" in summary.read_text()
    assert main(["--viewer", str(viewer), "--now", "2026-11-20T18:30:00Z"]) == 1
