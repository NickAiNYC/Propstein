"""Small shared numeric helpers."""

from __future__ import annotations

import math


def finite_or(value, default: float) -> float:
    """float(value) if finite, else default. NOTE: `nan or default` does NOT
    work in Python — NaN is truthy — so every std() that can be NaN on tiny
    windows goes through this guard."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    return v if math.isfinite(v) else float(default)
