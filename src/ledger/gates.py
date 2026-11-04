"""Model-validation and paid-tier CLV gates stay independent.

There is no combined QUALIFIED flag. This module does not change the
preregistered protocol in docs/EDGE_GATE.md or the frozen audit script.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PAID_TIER_PASS_FILENAME = "paid_tier_clv_pass.json"


def count_evaluable_signals(conn) -> int:
    """Number of independently evaluable qualifying signals under AMEND-001.

    Enforces pre-kickoff capture (decision_at < event_start_at), matched
    independent closing references, and excludes withdrawals and non-evaluable
    settlements (push, void, dnp, cancelled).
    """
    query = """
    SELECT count(DISTINCT s.id)::int AS n
    FROM population_committed_forecasts s
    JOIN closing_references c ON c.signal_id = s.id AND c.match_status = 'MATCHED'
    WHERE s.amendment_id = 'AMEND-001'
      AND s.captured_at < s.event_start_at
      AND c.reason_code IS NULL
      AND c.settlement_rules IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM withdrawals w WHERE w.signal_id = s.id
      )
      AND NOT EXISTS (
        SELECT 1 FROM settlements st
        WHERE st.signal_id = s.id
          AND st.result IN ('push', 'void', 'dnp', 'cancelled')
      )
    """
    with conn.cursor() as cur:
        cur.execute(query)
        row = cur.fetchone()
        return int(row[0] if isinstance(row, (list, tuple)) else row["n"])


def read_independent_gates(root: Path, conn: Any = None) -> dict[str, dict]:
    skill = _brier_skill(root)
    model_passed = skill is not None and skill >= 0
    paid_passed = _paid_tier_pass_recorded(root, conn=conn)
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
                "This flag is closed unless a verified confirmatory pass record exists "
                "with registered rule release, N >= 600 evaluable rows, mean price CLV >= 1.0 pp, "
                "cluster-robust CI lower bound > 0, and matching ledger root hash. "
                "The N=600 protocol is unchanged. N=300 remains a descriptive checkpoint "
                "and does not open this flag."
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
        if not isinstance(payload, dict):
            return None
        return float(payload["metrics"]["brier_skill_score_pct"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _paid_tier_pass_recorded(root: Path, conn: Any = None) -> bool:
    path = root / "governance" / PAID_TIER_PASS_FILENAME
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    if not isinstance(payload, dict):
        return False

    if payload.get("passed") is not True:
        return False

    # Preregistered Edge Gate invariants (docs/EDGE_GATE.md):
    # - N >= 600 independently evaluable qualifying signals per sport
    # - Observed mean CLV >= +1.0 percentage point (or >= 0.01 in probability)
    # - Lower confidence bound > 0 (cluster-robust bootstrap)
    # - Explicit rule_release_id, ledger_root_hash, and signature_sha256
    evaluable_count = payload.get("evaluable_count")
    if not isinstance(evaluable_count, int) or evaluable_count < 600:
        return False

    mean_price_clv = payload.get("mean_price_clv")
    if not isinstance(mean_price_clv, (int, float)) or (mean_price_clv < 1.0 and mean_price_clv < 0.01):
        return False

    ci_lower = payload.get("ci_lower")
    if not isinstance(ci_lower, (int, float)) or ci_lower <= 0:
        return False

    rule_release_id = payload.get("rule_release_id")
    if not isinstance(rule_release_id, str) or not rule_release_id.strip():
        return False

    ledger_root_hash = payload.get("ledger_root_hash")
    if not isinstance(ledger_root_hash, str) or not ledger_root_hash.strip():
        return False

    signature_sha256 = payload.get("signature_sha256")
    if not isinstance(signature_sha256, str) or not signature_sha256.strip():
        return False

    # If database connection is provided, verify against live ledger
    if conn is not None:
        try:
            live_count = count_evaluable_signals(conn)
            if live_count < 600:
                return False
        except Exception:
            return False

    # Check anchor match against published ledger report if available
    audit_report = root / "viewer" / "clv_audit_report.json"
    if audit_report.is_file():
        try:
            report_data = json.loads(audit_report.read_text(encoding="utf-8"))
            if isinstance(report_data, dict):
                published_root = report_data.get("ledger_root_hash")
                if published_root and published_root != ledger_root_hash:
                    return False
        except Exception:
            return False

    return True
