"""Model-validation and paid-tier CLV gates stay independent.

There is no combined QUALIFIED flag. This module does not change the
preregistered protocol in docs/EDGE_GATE.md or the frozen audit script.
"""

from __future__ import annotations

import json
from pathlib import Path

PAID_TIER_PASS_FILENAME = "paid_tier_clv_pass.json"


def read_independent_gates(root: Path) -> dict[str, dict]:
    skill = _brier_skill(root)
    model_passed = skill is not None and skill >= 0
    paid_passed = _paid_tier_pass_recorded(root)
    return {
        "model_validation": {
            "passed": model_passed,
            "basis": (
                "Published holdout Brier skill decides this flag alone. "
                "A negative skill keeps it closed. It is not the paid-tier CLV flag."
            ),
        },
        "paid_tier_clv": {
            "passed": paid_passed,
            "basis": (
                "This flag is closed unless a separate confirmatory pass file exists. "
                "The N=600 protocol is unchanged. N=300 remains a descriptive checkpoint "
                "in that protocol and does not open this flag."
            ),
        },
    }


def public_gate_flags(flags: dict[str, dict]) -> dict[str, bool]:
    return {
        "model_validation_passed": bool(flags["model_validation"]["passed"]),
        "paid_tier_clv_passed": bool(flags["paid_tier_clv"]["passed"]),
    }


def _brier_skill(root: Path) -> float | None:
    path = root / "viewer" / "holdout_eval_2026_w1.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return float(payload["metrics"]["brier_skill_score_pct"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _paid_tier_pass_recorded(root: Path) -> bool:
    path = root / "governance" / PAID_TIER_PASS_FILENAME
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("passed") is True
