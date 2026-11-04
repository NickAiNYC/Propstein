from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.line_history import LineHistoryStore, init_db


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_line_history.db"
    return db_file


def test_schema_initialization(temp_db: Path):
    conn = init_db(temp_db)
    cursor = conn.cursor()

    # Verify tables exist
    tables = [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "events" in tables
    assert "players" in tables
    assert "books" in tables
    assert "lines" in tables

    # Verify indexes exist
    indexes = [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    ]
    assert "ux_lines_dedupe" in indexes
    assert "idx_lines_series" in indexes
    assert "idx_lines_steam" in indexes
    conn.close()


def test_deduplication_and_change_detection(temp_db: Path):
    store = LineHistoryStore(temp_db)

    store.upsert_book("draftkings", "DraftKings")
    store.upsert_event("event_1", "NE", "CHI", "2026-10-20T17:00:00Z")
    store.upsert_player("player_1", "Hunter Henry", "NE", "TE")

    # 1. First observation: should be recorded
    rec1 = store.record_line(
        book_id="draftkings",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=31.5,
        over_price=-110,
        under_price=-110,
        captured_at="2026-10-20T06:00:00Z",
    )
    assert rec1 is True

    # 2. Identical observation 5 minutes later: should be skipped
    rec2 = store.record_line(
        book_id="draftkings",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=31.5,
        over_price=-110,
        under_price=-110,
        captured_at="2026-10-20T06:05:00Z",
    )
    assert rec2 is False

    # 3. Odds change: -110 -> -115: should be recorded
    rec3 = store.record_line(
        book_id="draftkings",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=31.5,
        over_price=-115,
        under_price=-105,
        captured_at="2026-10-20T06:10:00Z",
    )
    assert rec3 is True

    # 4. Line change: 31.5 -> 33.5: should be recorded
    rec4 = store.record_line(
        book_id="draftkings",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=33.5,
        over_price=-115,
        under_price=-105,
        captured_at="2026-10-20T06:15:00Z",
    )
    assert rec4 is True

    stats = store.stats()
    assert stats["lines"] == 3
    store.close()


def test_multi_book_capture_and_series(temp_db: Path):
    store = LineHistoryStore(temp_db)

    quotes = [
        {
            "book": "Pinnacle",
            "game_id": "event_1",
            "player_id": "player_aj",
            "player_name": "A.J. Brown",
            "team": "NE",
            "opponent": "CHI",
            "market": "receiving_yards",
            "line": 61.5,
            "over_odds": -108,
            "under_odds": -112,
            "observed_at": "2026-10-20T10:00:00Z",
            "verified": True,
        },
        {
            "book": "DraftKings",
            "game_id": "event_1",
            "player_id": "player_aj",
            "player_name": "A.J. Brown",
            "team": "NE",
            "opponent": "CHI",
            "market": "receiving_yards",
            "line": 62.5,
            "over_odds": -110,
            "under_odds": -110,
            "observed_at": "2026-10-20T10:00:00Z",
            "verified": False,
        },
    ]

    res = store.ingest_quotes(quotes)
    assert res["recorded"] == 2
    assert res["skipped"] == 0

    # Re-ingesting exact same quotes -> 0 recorded, 2 skipped
    res_repeat = store.ingest_quotes(quotes)
    assert res_repeat["recorded"] == 0
    assert res_repeat["skipped"] == 2

    series = store.get_series("player_aj", "receiving_yards")
    assert "pinnacle" in series
    assert "draftkings" in series
    assert len(series["pinnacle"]) == 1
    assert series["pinnacle"][0]["line"] == 61.5
    assert series["pinnacle"][0]["verified"] is True
    assert series["draftkings"][0]["line"] == 62.5
    assert series["draftkings"][0]["verified"] is False

    store.close()


def test_detect_steam(temp_db: Path):
    store = LineHistoryStore(temp_db)

    # 2 books moving line on player_1
    store.record_line(
        book_id="pinnacle",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=45.5,
        over_price=-110,
        under_price=-110,
        captured_at="2026-10-20T12:00:00Z",
    )
    store.record_line(
        book_id="draftkings",
        event_id="event_1",
        player_id="player_1",
        market="receiving_yards",
        line=47.5,
        over_price=-110,
        under_price=-110,
        captured_at="2026-10-20T12:05:00Z",
    )

    signals = store.detect_steam(
        event_id="event_1", market="receiving_yards", min_books=2, min_line_delta=1.5
    )
    assert len(signals) == 1
    assert signals[0]["player_id"] == "player_1"
    assert signals[0]["delta"] == 2.0
    assert set(signals[0]["books"]) == {"pinnacle", "draftkings"}

    store.close()


def test_static_export(temp_db: Path, tmp_path: Path):
    store = LineHistoryStore(temp_db)
    store.record_line(
        book_id="pinnacle",
        event_id="event_1",
        player_id="00-0035676",
        market="receiving_yards",
        line=61.5,
        over_price=-110,
        under_price=-110,
        captured_at="2026-10-20T10:00:00Z",
    )

    out_dir = tmp_path / "api_lines"
    exported = store.export_static_series(out_dir)
    assert exported == 1

    target = out_dir / "00-0035676" / "receiving-yards.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["player_id"] == "00-0035676"
    assert data["market"] == "receiving_yards"
    assert "pinnacle" in data["series"]
    assert data["series"]["pinnacle"][0]["line"] == 61.5

    store.close()
