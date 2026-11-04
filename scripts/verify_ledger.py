"""Fail closed unless the ledger migration, registry, and invariant tests pass."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    return pytest.main(["tests/ledger", "-q", "--tb=short"])


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
