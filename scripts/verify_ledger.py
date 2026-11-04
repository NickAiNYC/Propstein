"""Fail closed unless the ledger migration, registry, and invariant tests pass."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def check_governance_pass_file() -> int:
    pass_file = ROOT / "governance" / "paid_tier_clv_pass.json"
    if pass_file.is_file():
        from src.ledger.gates import read_independent_gates

        gates = read_independent_gates(ROOT)
        if not gates["paid_tier_clv"]["passed"]:
            print(
                "FAIL CLOSED: governance/paid_tier_clv_pass.json exists but does not match computed ledger evidence.",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> int:
    gov_code = check_governance_pass_file()
    if gov_code != 0:
        return gov_code
    return pytest.main(["tests/ledger", "-q", "--tb=short"])


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
