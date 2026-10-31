import hashlib
import json
from datetime import datetime, timezone

import pytest

from scripts.check_odds_freshness import check


NOW = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)


def sample_viewer(tmp_path, updated_at="2026-10-31T12:00:00Z", game_day="2026-11-01"):
    viewer = tmp_path / "viewer"
    (viewer / "feeds").mkdir(parents=True)
    (viewer / "feeds/slate-index.json").write_text(json.dumps({
        "sports": {"nfl": {"default_slate": "2026_w8", "slates": {
            "2026_w8": {"games": "games_2026_w8.json"}}}}
    }))
    (viewer / "games_2026_w8.json").write_text(json.dumps([{"gameday": game_day}]))
    raw = json.dumps({"updated_at": updated_at, "feed_status": "LIVE_POLYMARKET_CLOB_UNVERIFIED",
                      "polymarket_quotes_count": 1}).encode()
    (viewer / "live_odds_feed.json").write_bytes(raw)
    (viewer / "live_odds_feed.manifest.json").write_text(json.dumps({
        "status": "PASS_ATOMIC_PUBLISHED", "sha256": hashlib.sha256(raw).hexdigest()}))
    return viewer


def test_fresh_active_feed_passes_without_claiming_verification(tmp_path):
    result = check(sample_viewer(tmp_path), now=NOW)
    assert "manifest hash matches" in result
    assert "unverified" in result


def test_stale_active_feed_fails_loudly(tmp_path):
    viewer = sample_viewer(tmp_path, updated_at="2026-10-31T07:00:00Z")
    with pytest.raises(ValueError, match="8.00 hours old"):
        check(viewer, now=NOW)


def test_manifest_mismatch_fails_even_when_timestamp_is_fresh(tmp_path):
    viewer = sample_viewer(tmp_path)
    (viewer / "live_odds_feed.json").write_text('{"updated_at":"2026-10-31T14:00:00Z"}')
    with pytest.raises(ValueError, match="provenance manifest"):
        check(viewer, now=NOW)


def test_no_upcoming_games_skips_alarm(tmp_path):
    viewer = sample_viewer(tmp_path, updated_at="2026-01-01T12:00:00Z", game_day="2026-10-01")
    assert "skipped" in check(viewer, now=NOW)
