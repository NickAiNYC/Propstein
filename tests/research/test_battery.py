from pathlib import Path
import pytest
from src.research.battery import (
    benjamini_hochberg,
    evaluate_battery,
    run_null_world_simulation,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def test_benjamini_hochberg_controls_fdr():
    # 4 tests: one strong real signal, three noise
    p_vals = [0.001, 0.04, 0.20, 0.80]
    bh = benjamini_hochberg(p_vals, alpha=0.05)
    # p=0.001 should survive (q = 0.001 * 4 / 1 = 0.004 <= 0.05)
    assert bh[0][1] is True
    # p=0.04 ranked 2nd: q = 0.04 * 4 / 2 = 0.08 > 0.05 -> rejected!
    assert bh[1][1] is False
    assert bh[2][1] is False
    assert bh[3][1] is False


def test_null_world_simulation_collapses_ndr():
    ndr_raw, ndr_fdr = run_null_world_simulation(n_variants=6, n_reps=200, alpha=0.05)
    # With 6 independent tests at alpha=0.05 under null, raw discovery rate is ~ 1 - (0.95)^6 = ~26%
    assert ndr_raw > 0.15
    # FDR correction collapses false discovery rate back towards or below nominal ~5%
    assert ndr_fdr < ndr_raw
    assert ndr_fdr <= 0.10


def test_evaluate_battery_from_yaml():
    yaml_path = ROOT / "research" / "battery.v1.yaml"
    assert yaml_path.is_file()

    mock_p_values = {
        "resid-calib-band": 0.002,  # strong candidate
        "resid-role-confidence": 0.035,
        "resid-absence-shock": 0.08,
        "resid-composite-l2": 0.001,  # strong candidate
        "baseline-market-anchor": 0.45,
        "hier-shrinkage-empirical": 0.25,
    }

    res = evaluate_battery(yaml_path, mock_p_values, n_null_reps=100)
    assert res.battery_id == "propstein-receiving-v1"
    assert res.n_variants_registered == 6
    assert len(res.battery_sha256) == 64
    assert "resid-composite-l2" in res.discoveries_fdr_corrected
    assert "resid-calib-band" in res.discoveries_fdr_corrected
    # 0.035 should be filtered out by FDR
    assert "resid-role-confidence" not in res.discoveries_fdr_corrected
