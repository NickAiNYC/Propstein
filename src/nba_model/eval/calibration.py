"""Calibration metrics — is the model's probability honest?

Everything here runs on walk-forward RECORDS: one row per (prediction,
line, book-consensus) with the realized outcome. Metrics:
  Brier score, log loss, reliability table, Cox calibration slope.
Comparison columns (market_p, naive_p) are REPORTED, and the market
delta is surfaced honestly — beating the market is evidence, not a gate.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import SMALL_SAMPLE_N

_EPS = 1e-6


def brier(p: pd.Series, y: pd.Series) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def log_loss(p: pd.Series, y: pd.Series) -> float:
    p, y = np.clip(np.asarray(p, float), _EPS, 1 - _EPS), np.asarray(y, float)
    if len(p) == 0:
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_table(p: pd.Series, y: pd.Series, bins: int = 10) -> list[dict]:
    """Decile reliability bins — the table the audit page should render."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return []
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < bins - 1 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            continue
        out.append({
            "bin_lo": round(float(lo), 3),
            "bin_hi": round(float(hi), 3),
            "n": int(mask.sum()),
            "mean_p": round(float(p[mask].mean()), 4),
            "observed_freq": round(float(y[mask].mean()), 4),
        })
    return out


def _logit_fit(X: np.ndarray, y: np.ndarray, iters: int = 30) -> np.ndarray:
    """Newton-Raphson logistic regression (2-3 parameters; no sklearn dep)."""
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        mu = 1.0 / (1.0 + np.exp(-(X @ beta)))
        w = np.clip(mu * (1.0 - mu), 1e-10, None)
        grad = X.T @ (y - mu)
        hess = (X.T * w) @ X
        try:
            step = np.linalg.solve(hess + 1e-9 * np.eye(hess.shape[0]), grad)
        except np.linalg.LinAlgError:
            break
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def calibration_slope(p: pd.Series, y: pd.Series) -> float | None:
    """Cox calibration slope: LOGISTIC regression of the outcome on logit(p).

    logit(P(outcome=1)) = a + b * logit(model_p);  b = 1.0 iff calibrated.
    slope < 1 -> over-confident; slope > 1 -> under-confident.

    (A plain OLS of the 0/1 outcome on logit(p) would NOT give the Cox
    slope — its expectation is the logistic curve itself, whose average
    derivative is ~0.2 even for a perfectly calibrated model.)
    Returns None when logit(p) has ~no variance or n is too small.
    """
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) < SMALL_SAMPLE_N:
        return None
    pc = np.clip(p, _EPS, 1 - _EPS)
    lp = np.log(pc / (1 - pc))
    if lp.var() < 1e-8:
        return None
    X = np.column_stack([np.ones_like(lp), lp])
    beta = _logit_fit(X, y)
    return float(beta[1])


def summarize(records: pd.DataFrame) -> dict:
    """Full calibration summary over walk-forward records.

    Required columns: model_p, outcome (1/0, pushes excluded upstream);
    optional: market_p, naive_p, date.
    """
    if records is None or len(records) == 0:
        return {
            "n": 0, "uncalibrated": True,
            "reason": "no walk-forward records",
        }
    r = records
    slope = calibration_slope(r["model_p"], r["outcome"])
    market_b = brier(r["market_p"], r["outcome"]) if "market_p" in r and r["market_p"].notna().any() else None
    naive_b = brier(r["naive_p"], r["outcome"]) if "naive_p" in r and r["naive_p"].notna().any() else None
    model_b = brier(r["model_p"], r["outcome"])
    summary = {
        "n": int(len(r)),
        "n_dates": int(r["date"].nunique()) if "date" in r else None,
        "brier_model": round(model_b, 5) if math.isfinite(model_b) else None,
        "brier_market": round(market_b, 5) if market_b is not None and math.isfinite(market_b) else None,
        "brier_naive": round(naive_b, 5) if naive_b is not None and math.isfinite(naive_b) else None,
        "brier_vs_market": (
            round(model_b - market_b, 5)
            if market_b is not None and math.isfinite(market_b) and math.isfinite(model_b)
            else None
        ),
        "brier_vs_naive": (
            round(model_b - naive_b, 5)
            if naive_b is not None and math.isfinite(naive_b) and math.isfinite(model_b)
            else None
        ),
        "log_loss_model": round(log_loss(r["model_p"], r["outcome"]), 5),
        "calibration_slope": round(slope, 4) if slope is not None else None,
        "reliability": reliability_table(r["model_p"], r["outcome"]),
        "small_sample": bool(len(r) < SMALL_SAMPLE_N),
    }
    summary["uncalibrated"] = bool(summary["small_sample"] or slope is None)
    return summary
