"""
Unit Tests for PropStein Ingestion Data Contracts & Fail-Closed Gate
"""

import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from src.contracts.odds import OddsQuote, LiveOddsFeed
from src.contracts.slate import SlateRow, SlateUniverse
from src.contracts.availability import InjuryEntry, AvailabilityFeed
from src.contracts.gate import validate_and_publish


def test_valid_odds_quote_contract():
    valid = {
        "quote_id": "dk_harden_ast_8_5",
        "player_id": "nba-201935",
        "player_name": "James Harden",
        "market": "assists",
        "line": 8.5,
        "over_odds": -115,
        "under_odds": -105,
        "book": "draftkings",
        "observed_at": "2026-10-29T14:00:00Z",
    }
    quote = OddsQuote.model_validate(valid)
    assert quote.player_name == "James Harden"
    assert quote.line == 8.5
    assert quote.over_odds == -115


def test_invalid_odds_fails_closed():
    # Negative line
    with pytest.raises(ValidationError):
        OddsQuote.model_validate({
            "quote_id": "q1",
            "player_id": "p1",
            "player_name": "Test",
            "market": "assists",
            "line": -5.5,
            "over_odds": -110,
            "under_odds": -110,
            "book": "draftkings",
            "observed_at": "2026-10-29T14:00:00Z",
        })

    # American odds between -99 and +99 (invalid)
    with pytest.raises(ValidationError):
        OddsQuote.model_validate({
            "quote_id": "q1",
            "player_id": "p1",
            "player_name": "Test",
            "market": "assists",
            "line": 5.5,
            "over_odds": 50,
            "under_odds": -110,
            "book": "draftkings",
            "observed_at": "2026-10-29T14:00:00Z",
        })

    # Inverted / broken vig sum (e.g. +300 and +300 on a 2-way line has vig sum 0.50 -> impossible)
    with pytest.raises(ValidationError):
        OddsQuote.model_validate({
            "quote_id": "q1",
            "player_id": "p1",
            "player_name": "Test",
            "market": "assists",
            "line": 5.5,
            "over_odds": +300,
            "under_odds": +300,
            "book": "draftkings",
            "observed_at": "2026-10-29T14:00:00Z",
        })


def test_slate_row_contract_and_inverted_ci():
    # Valid slate row
    row = SlateRow.model_validate({
        "player_id": "00-0030035",
        "player_display_name": "Adam Thielen",
        "market": "receiving_yards",
        "fair_line": 43.5,
        "ci_low": 30.0,
        "ci_high": 58.0,
    })
    assert row.fair_line == 43.5

    # Negative fair line fails
    with pytest.raises(ValidationError):
        SlateRow.model_validate({
            "player_id": "00-0030035",
            "fair_line": -10.0,
        })

    # Inverted CI bounds (ci_low > ci_high) fails
    with pytest.raises(ValidationError):
        SlateRow.model_validate({
            "player_id": "00-0030035",
            "fair_line": 40.0,
            "ci_low": 50.0,
            "ci_high": 30.0,
        })


def test_slate_universe_duplicate_detection():
    # Duplicate (player_id, market) records fail closed
    rows = [
        {"player_id": "p1", "market": "points", "fair_line": 20.0},
        {"player_id": "p2", "market": "points", "fair_line": 15.0},
        {"player_id": "p1", "market": "points", "fair_line": 22.0},  # duplicate!
    ]
    with pytest.raises(ValidationError, match="duplicate player/market records"):
        SlateUniverse.model_validate({"rows": rows, "min_players_threshold": 2})


def test_slate_universe_minimum_threshold():
    # Fewer rows than threshold fails
    rows = [
        {"player_id": "p1", "market": "points", "fair_line": 20.0},
    ]
    with pytest.raises(ValidationError, match="minimum threshold"):
        SlateUniverse.model_validate({"rows": rows, "min_players_threshold": 5})


def test_injury_entry_contract():
    # Valid injury
    inj = InjuryEntry.model_validate({
        "player_name": "Romeo Doubs",
        "team": "GB",
        "status": "OUT",
        "vacated_targets": 6.5,
        "vacated_minutes": 28.0,
    })
    assert inj.status == "OUT"

    # Unknown random status fails
    with pytest.raises(ValidationError):
        InjuryEntry.model_validate({
            "player_name": "Unknown Player",
            "team": "GB",
            "status": "NOT_FEELING_WELL_MAYBE",
        })

    # Negative vacated volume fails
    with pytest.raises(ValidationError):
        InjuryEntry.model_validate({
            "player_name": "Doubs",
            "team": "GB",
            "status": "OUT",
            "vacated_targets": -5.0,
        })


def test_gate_atomic_publish_and_manifest(tmp_path):
    target = tmp_path / "test_feed.json"
    manifest_file = tmp_path / "test_feed.manifest.json"

    feed_data = {
        "feed_status": "OK",
        "updated_at": "2026-10-29T14:00:00Z",
        "slate": "2026_w7",
        "total_quotes": 1,
        "quotes": [
            {
                "quote_id": "q1",
                "player_id": "p1",
                "player_name": "Test Player",
                "market": "receptions",
                "line": 4.5,
                "over_odds": -110,
                "under_odds": -110,
                "book": "draftkings",
                "observed_at": "2026-10-29T14:00:00Z",
            }
        ]
    }

    success, manifest = validate_and_publish(
        schema_cls=LiveOddsFeed,
        raw_data=feed_data,
        target_path=target,
        source_feed="draftkings_api",
    )

    assert success is True
    assert target.exists()
    assert manifest_file.exists()
    assert manifest["status"] == "PASS_ATOMIC_PUBLISHED"
    assert manifest["rows_valid"] == 1
    assert manifest["rows_rejected"] == 0
    assert manifest["sha256"] is not None


def test_gate_fail_closed_and_quarantine(tmp_path):
    target = tmp_path / "live_odds.json"
    target.write_text('{"original": "safe_production_data"}')
    manifest_file = tmp_path / "live_odds.manifest.json"

    # Poisoned payload (negative line and invalid odds)
    bad_feed = {
        "feed_status": "OK",
        "updated_at": "2026-10-29T14:00:00Z",
        "slate": "2026_w7",
        "total_quotes": 1,
        "quotes": [
            {
                "quote_id": "q1",
                "player_id": "p1",
                "player_name": "Test Player",
                "market": "receptions",
                "line": -99.0,  # POISON!
                "over_odds": -110,
                "under_odds": -110,
                "book": "draftkings",
                "observed_at": "2026-10-29T14:00:00Z",
            }
        ]
    }

    success, manifest = validate_and_publish(
        schema_cls=LiveOddsFeed,
        raw_data=bad_feed,
        target_path=target,
        source_feed="poisoned_api",
    )

    assert success is False
    assert manifest["status"] == "FAIL_CLOSED_QUARANTINED"
    assert manifest["quarantine_path"] is not None
    assert Path(manifest["quarantine_path"]).exists()

    # CRITICAL: Production target file was NEVER touched!
    assert json.loads(target.read_text()) == {"original": "safe_production_data"}
