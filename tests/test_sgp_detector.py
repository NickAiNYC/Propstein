from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.sgp_detector import SGPDetector


def test_evaluate_pair():
    detector = SGPDetector(alpha=0.1097, k=1.555, n_sims=30_000, seed=42)
    candidates = detector.evaluate_pair(
        player_name="DeMario Douglas",
        player_id="00-0038555",
        team="NE",
        opponent="CHI",
        mu_rec=4.5,
        mu_ypr=10.8,
        rec_line=3.5,
        yd_line=34.5,
        rec_odds=-110,
        yd_odds=-110,
    )

    assert len(candidates) == 2
    over_over = [c for c in candidates if c.pairing == "OVER_OVER"][0]
    under_under = [c for c in candidates if c.pairing == "UNDER_UNDER"][0]

    # Verify strong positive correlation and lift
    assert 0.50 <= over_over.phi_correlation <= 0.80
    assert over_over.correlation_lift >= 1.25
    assert over_over.p_model_joint > over_over.p_independent
    assert over_over.player_name == "DeMario Douglas"


def test_scan_slate(tmp_path: Path):
    snapshots_file = ROOT = Path(__file__).resolve().parent.parent / "viewer" / "snapshots_2026_w7.json"
    if not snapshots_file.exists():
        pytest.skip("Snapshots file not found")

    detector = SGPDetector(alpha=0.1097, k=1.555, n_sims=10_000, seed=7)
    candidates = detector.scan_slate(snapshots_file)

    assert len(candidates) > 0
    # Results should be sorted by EV descending
    evs = [c.expected_value_pct for c in candidates]
    assert evs == sorted(evs, reverse=True)
