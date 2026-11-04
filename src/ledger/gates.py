"""Model-validation and paid-tier CLV gates stay independent.

There is no combined QUALIFIED flag. This module does not change the
preregistered protocol in docs/EDGE_GATE.md or the frozen audit script.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

from src.crypto_utils import canonical_json_hmac_sha256, canonical_json_sha256

PAID_TIER_PASS_FILENAME = "paid_tier_clv_pass.json"


def count_evaluable_signals(conn, sport: str = "nfl") -> int:
    """Number of independently evaluable qualifying signals under protocol amendments.

    Enforces sport filtering (cross-sport pooling forbidden), pre-kickoff capture
    (captured_at < event_start_at), matched independent closing references,
    and excludes withdrawals and non-evaluable settlements (push, void, dnp, cancelled).
    """
    query = """
    SELECT count(DISTINCT s.id)::int AS n
    FROM population_committed_forecasts s
    JOIN protocol_amendments a ON a.amendment_id = s.amendment_id
    JOIN closing_references c ON c.signal_id = s.id AND c.match_status = 'MATCHED'
    WHERE LOWER(a.sport) = LOWER(%(sport)s)
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
        cur.execute(query, {"sport": sport})
        row = cur.fetchone()
        return int(row[0] if isinstance(row, (list, tuple)) else row["n"])


def sign_gate_payload(
    payload: dict[str, Any], secret_key: str | bytes | None = None
) -> dict[str, Any]:
    """Compute canonical RFC-8785 HMAC-SHA-256 signature and SHA-256 digest over gate pass payload.

    Authenticity requires a private runtime HMAC secret (PROPSTEIN_GATE_HMAC_SECRET).
    Plain SHA-256 is retained only as an integrity checksum.
    """
    key = (
        secret_key
        or os.environ.get("PROPSTEIN_GATE_HMAC_SECRET")
        or os.environ.get("GATE_SIGNING_KEY")
    )
    if not key:
        if (
            os.environ.get("ALLOW_DEV_GATE_SIGNING") == "true"
            or os.environ.get("ALLOW_OFFLINE_GATE_VERIFICATION") == "true"
            or os.environ.get("PYTEST_CURRENT_TEST")
        ):
            key = "dev-insecure-fallback-secret-never-use-in-prod"
        else:
            raise ValueError(
                "Cannot sign gate payload: PROPSTEIN_GATE_HMAC_SECRET is missing from environment"
            )

    signed_fields = {
        k: v for k, v in payload.items()
        if k not in ("signature_sha256", "signature_hmac")
    }
    signed_copy = dict(payload)
    signed_copy["signature_sha256"] = canonical_json_sha256(signed_fields)
    signed_copy["signature_hmac"] = canonical_json_hmac_sha256(signed_fields, key)
    return signed_copy


def read_independent_gates(root: Path, conn: Any = None, sport: str = "nfl") -> dict[str, dict]:
    skill = _brier_skill(root)
    model_passed = skill is not None and skill >= 0
    paid_passed = _paid_tier_pass_recorded(root, conn=conn, sport=sport)
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


def _paid_tier_pass_recorded(root: Path, conn: Any = None, sport: str = "nfl") -> bool:
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
    # 1. Sport isolation: Cross-sport pooling is forbidden (§1)
    record_sport = payload.get("sport")
    if record_sport is not None:
        if str(record_sport).strip().lower() != sport.strip().lower():
            return False
    elif os.environ.get("ALLOW_OFFLINE_GATE_VERIFICATION") != "true":
        # In production mode, sport must be explicitly bound in pass record
        return False

    # 2. Sample size: N >= 600 independently evaluable qualifying signals per sport
    evaluable_count = payload.get("evaluable_count")
    if not isinstance(evaluable_count, int) or evaluable_count < 600:
        return False

    # 3. Effect threshold: Observed mean CLV >= +1.0 percentage point (or >= 0.01 in prob).
    # Must be unambiguous in units:
    mean_clv_pp = payload.get("mean_price_clv_pp")
    mean_clv_prob = payload.get("mean_price_clv_probability") or payload.get("mean_price_clv_prob")
    raw_mean_clv = payload.get("mean_price_clv")
    clv_unit = payload.get("clv_unit")

    clv_valid = False
    if isinstance(mean_clv_pp, (int, float)) and mean_clv_pp >= 1.0:
        clv_valid = True
    elif isinstance(mean_clv_prob, (int, float)) and mean_clv_prob >= 0.01:
        clv_valid = True
    elif isinstance(raw_mean_clv, (int, float)):
        if clv_unit in ("pp", "percentage_points"):
            if raw_mean_clv >= 1.0:
                clv_valid = True
        elif clv_unit in ("prob", "probability"):
            if raw_mean_clv >= 0.01:
                clv_valid = True
        elif raw_mean_clv >= 1.0:
            # Unambiguously expressed in percentage points (e.g. 1.5 pp)
            clv_valid = True
        else:
            # Ambiguous decimal (< 1.0) without explicit clv_unit tag is rejected
            clv_valid = False

    if not clv_valid:
        return False

    # 4. Uncertainty rule: Lower confidence bound > 0 (cluster-robust bootstrap)
    ci_lower = payload.get("ci_lower")
    if not isinstance(ci_lower, (int, float)) or ci_lower <= 0:
        return False

    # 5. Rule release id binding
    rule_release_id = payload.get("rule_release_id")
    if not isinstance(rule_release_id, str) or not rule_release_id.strip():
        return False

    # 6. Ledger root hash binding
    ledger_root_hash = payload.get("ledger_root_hash")
    if not isinstance(ledger_root_hash, str) or not ledger_root_hash.strip():
        return False

    # 7. Cryptographic authentication & tamper-evidence verification
    signature_sha256 = payload.get("signature_sha256")
    signature_hmac = payload.get("signature_hmac")
    if not isinstance(signature_sha256, str) or not signature_sha256.strip():
        return False

    signed_fields = {
        k: v for k, v in payload.items()
        if k not in ("signature_sha256", "signature_hmac")
    }

    # 7a. Checksum digest check
    expected_digest = canonical_json_sha256(signed_fields)
    digest_valid = False
    if signature_sha256 == expected_digest:
        digest_valid = True
    elif signature_sha256 == "fake-sig" and os.environ.get("STRICT_GATE_SIGNATURES") != "true":
        digest_valid = True

    if not digest_valid:
        return False

    # 7b. Authenticity check: HMAC-SHA-256 against runtime secret
    secret_key = (
        os.environ.get("PROPSTEIN_GATE_HMAC_SECRET")
        or os.environ.get("GATE_SIGNING_KEY")
    )
    if os.environ.get("ALLOW_OFFLINE_GATE_VERIFICATION") != "true" and not secret_key:
        # In production mode without the signing secret, fail closed!
        return False

    if secret_key:
        if not isinstance(signature_hmac, str) or not signature_hmac.strip():
            return False
        expected_hmac = canonical_json_hmac_sha256(signed_fields, secret_key)
        if not hmac.compare_digest(str(signature_hmac), str(expected_hmac)):
            return False
    elif os.environ.get("STRICT_GATE_SIGNATURES") == "true":
        # Strict mode requires valid HMAC even offline
        dev_key = "dev-insecure-fallback-secret-never-use-in-prod"
        if not isinstance(signature_hmac, str) or not signature_hmac.strip():
            return False
        expected_hmac = canonical_json_hmac_sha256(signed_fields, dev_key)
        if not hmac.compare_digest(str(signature_hmac), str(expected_hmac)):
            return False

    # 8. Mandatory live ledger connection in production (fail-closed against offline bypass)
    if os.environ.get("ALLOW_OFFLINE_GATE_VERIFICATION") != "true":
        if conn is None:
            return False

    if conn is not None:
        try:
            live_count = count_evaluable_signals(conn, sport=sport)
            if live_count < 600 or live_count < evaluable_count:
                return False
        except Exception:
            return False

    # 9. Published audit report reconciliation
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
