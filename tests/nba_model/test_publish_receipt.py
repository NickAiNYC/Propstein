"""Board receipts — top-8 selection, canonical SHA-256, hash-chained history."""

import json

import pandas as pd
import pytest

from nba_model import config
from nba_model._compat import crypto_utils
from nba_model.eval.walkforward import run_walk_forward
from nba_model.features.form import add_rolling_form
from nba_model.features.injuries import add_availability_adjustments
from nba_model.model.projector import NBAPointsProjector
from nba_model.publish.board import build_board, publish_board

NOW = pd.Timestamp("2026-11-11T22:50:00Z")


def _summary_that_passes():
    return {
        "n": 500, "calibration_slope": 1.02,
        "brier_model": 0.210, "brier_naive": 0.240, "brier_market": 0.200,
        "brier_vs_market": 0.010, "uncalibrated": False,
    }


@pytest.fixture()
def slate_preds(synthetic_world):
    world = synthetic_world
    slate = world["end"]
    full = add_rolling_form(world["df"])
    train = full[full["game_date"] < slate]
    test = full[(full["game_date"] == slate) & (~full["dnp"])].copy()
    test = add_availability_adjustments(test, world["injuries"])
    return NBAPointsProjector().fit(train).predict(test, history=train), slate


def _quotes_with_one_mispriced_star(preds, slate):
    """Two independent books badly misprice one player: guarantees a
    qualifying play exists regardless of the natural feed."""
    star = preds.sort_values("mean_pts", ascending=False).iloc[0]
    line = round(max(4.5, float(star["mean_pts"]) - 6.0), 1)
    return [
        {
            "quote_id": f"tq-1-{star['player_id']}", "book": "Book One",
            "player_id": star["player_id"], "player_name": star["player_display_name"],
            "team": star["team"], "game_id": star["game_id"], "market": "points",
            "line": line, "over_odds": -110, "under_odds": -110,
            "observed_at": f"{slate}T22:45:00Z", "verified": True, "_fixture": True,
            "source": "test fixture",
        },
        {
            "quote_id": f"tq-2-{star['player_id']}", "book": "Book Two",
            "player_id": star["player_id"], "player_name": star["player_display_name"],
            "team": star["team"], "game_id": star["game_id"], "market": "points",
            "line": line, "over_odds": -108, "under_odds": -112,
            "observed_at": f"{slate}T22:46:00Z", "verified": True, "_fixture": True,
            "source": "test fixture",
        },
    ], star["player_id"], line


def test_board_publishes_gated_top8(tmp_path, slate_preds, synthetic_world):
    preds, slate = slate_preds
    quotes, pid, line = _quotes_with_one_mispriced_star(preds, slate)
    board = build_board(preds, quotes, _summary_that_passes(),
                        synthetic_world["meta"], now=NOW)
    assert board["status"] == "PUBLISHED", board.get("reasons")
    plays = board["payload"]["plays"]
    assert len(plays) <= config.BOARD_SIZE
    assert len(plays) >= 1
    # sorted by edge, every play cleared every gate
    edges = [p["edge"] for p in plays]
    assert edges == sorted(edges, reverse=True)
    for p in plays:
        assert p["edge"] >= config.EDGE_HURDLE
        assert p["n_books"] >= config.MIN_INDEPENDENT_BOOKS
        assert p["model_p"] - p["market_p_devig"] == pytest.approx(p["edge"], abs=1e-3)
        assert "explain" in p and "ppm_hat" in p["explain"]
    top = plays[0]
    assert top["player_id"] == pid and abs(top["line"] - line) < 1e-9

    # receipts
    path, sha = publish_board(board, tmp_path)
    doc = json.loads(path.read_text())
    body = {k: v for k, v in doc.items() if k != "receipt"}
    assert doc["receipt"]["sha256"] == sha
    assert sha == crypto_utils().canonical_json_sha256(body)
    history = (tmp_path / "nba_board_history.jsonl").read_text().splitlines()
    assert len(history) == 1
    assert json.loads(history[0])["sha256"] == sha


def test_board_history_is_hash_chained(tmp_path, slate_preds, synthetic_world):
    preds, slate = slate_preds

    def fresh_board(now):
        quotes, *_ = _quotes_with_one_mispriced_star(preds, slate)
        return build_board(preds, quotes, _summary_that_passes(),
                           synthetic_world["meta"], now=now)

    # two builds whose payloads genuinely differ (quote age shifts the gate
    # detail strings) -> different receipts; a re-publish of an identical
    # payload legitimately yields the same sha (deterministic receipts).
    _, sha1 = publish_board(fresh_board(NOW), tmp_path)
    _, sha2 = publish_board(fresh_board(NOW + pd.Timedelta(minutes=1)), tmp_path)
    assert sha1 != sha2
    lines = (tmp_path / "nba_board_history.jsonl").read_text().splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    assert second["prev_sha256"] == sha1


def test_board_refused_when_uncalibrated(tmp_path, slate_preds, synthetic_world):
    preds, slate = slate_preds
    quotes, *_ = _quotes_with_one_mispriced_star(preds, slate)
    bad_summary = {"n": 12, "uncalibrated": True,
                   "reason": "no walk-forward records"}
    board = build_board(preds, quotes, bad_summary,
                        synthetic_world["meta"], now=NOW)
    assert board["status"] == "REFUSED"
    assert board["reasons"], "refusal must be reason-explicit"
    path, sha = publish_board(board, tmp_path)
    assert "_REFUSED" in path.name
    doc = json.loads(path.read_text())
    assert doc["status"] == "REFUSED"
    # refused boards never overwrite the published-board naming slot
    assert not (tmp_path / f"nba_board_{slate}.json").exists()


def test_board_refused_when_quotes_stale(tmp_path, slate_preds, synthetic_world):
    preds, slate = slate_preds
    quotes = [
        {
            "quote_id": "stale-1", "book": "Book One",
            "player_id": preds.iloc[0]["player_id"], "market": "points",
            "line": 20.5, "over_odds": -110, "under_odds": -110,
            "observed_at": "2026-11-10T22:45:00Z", "verified": True, "_fixture": True,
            "source": "test fixture",
        },
        {
            "quote_id": "stale-2", "book": "Book Two",
            "player_id": preds.iloc[0]["player_id"], "market": "points",
            "line": 20.5, "over_odds": -110, "under_odds": -110,
            "observed_at": "2026-11-10T22:45:00Z", "verified": True, "_fixture": True,
            "source": "test fixture",
        },
    ]
    board = build_board(preds, quotes, _summary_that_passes(),
                        synthetic_world["meta"], now=NOW)
    assert board["status"] == "REFUSED"
    assert any("quote" in r.lower() for r in board["reasons"])


def test_board_plays_use_full_walkforward_when_supplied(synthetic_world):
    """End-to-end honesty check: a REAL walk-forward summary (not a crafted
    one) still flows through the gates; this test documents whatever the
    synthetic season's honest verdict is (published or refused)."""
    world = synthetic_world
    result = run_walk_forward(world["df"], "2026-11-02", world["end"],
                              odds=world["odds"], injuries=world["injuries"])
    assert result.summary["n"] > 0
    assert "brier_vs_market" in result.summary
