import pytest
from src.ledger.paired_scoring import compute_paired_market_comparison


def test_empty_observations():
    comp = compute_paired_market_comparison([])
    assert comp.n_pairs == 0
    assert comp.paired_diff == 0.0
    assert comp.is_copycat is False


def test_perfect_copycat_detected():
    obs = [
        {"p_model": 0.30 + 0.004 * i, "p_market": 0.30 + 0.004 * i + 0.0001, "outcome": 1 if i % 2 == 0 else 0, "event_id": f"g_{i % 5}"}
        for i in range(100)
    ]
    comp = compute_paired_market_comparison(obs)
    assert comp.n_pairs == 100
    assert comp.corr_model_market > 0.99
    assert comp.is_copycat is True
    assert comp.median_abs_gap_pts < 0.1


def test_superior_model_has_negative_paired_diff():
    # Model assigns 0.85 when outcome is 1, market assigns 0.50
    obs = []
    for i in range(60):
        y = 1 if i % 2 == 0 else 0
        pm = 0.80 if y == 1 else 0.20
        pk = 0.50
        obs.append({"p_model": pm, "p_market": pk, "outcome": y, "event_id": f"game_{i % 6}"})

    comp = compute_paired_market_comparison(obs)
    assert comp.n_pairs == 60
    assert comp.brier_model < comp.brier_market
    assert comp.paired_diff < 0  # negative = model outperforms
    assert comp.paired_diff_ci95[1] < 0  # 95% CI upper bound is below zero


def test_cluster_bootstrap_structure():
    obs = [
        {"p_model": 0.60, "p_market": 0.50, "outcome": 1, "event_id": "game_1"},
        {"p_model": 0.60, "p_market": 0.50, "outcome": 1, "event_id": "game_1"},
        {"p_model": 0.40, "p_market": 0.50, "outcome": 0, "event_id": "game_2"},
        {"p_model": 0.40, "p_market": 0.50, "outcome": 0, "event_id": "game_2"},
    ]
    comp = compute_paired_market_comparison(obs, n_boot=200)
    assert comp.n_events == 2
    assert comp.paired_diff < 0
    assert len(comp.paired_diff_ci95) == 2
