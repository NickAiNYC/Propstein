"""Dependency-lock consistency (fail-closed).

P0 debt item "Python dependency lock and CI test job" (docs/TECH-DEBT.md):
CI installs requirements.lock — never the open ranges — so the lock and the
intent spec (requirements.txt) must never drift apart silently. These tests
run inside the normal pytest invocation, which means the same CI job that
installs the lock also proves the lock still satisfies every declared range.

Rules pinned here:
  1. Every requirement declared in requirements.txt is pinned in
     requirements.lock at a version satisfying its specifier.
  2. The lock contains no duplicate pins.
  3. The lock pins are exact (==) — a bare name or a range in the lock is a
     bug, not a lock.
  4. numpy/pandas majors are what the suite was validated against
     (numpy 2.x, pandas 3.x per the 2026-11-02 freeze) — a major rollover in
     the lock must re-run the full suite before merge (see lock header).
"""

from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "requirements.txt"
LOCK_PATH = ROOT / "requirements.lock"


def _canonical(name: str) -> str:
    """PEP 503: hyphens/underscores/dots are equivalent in package names."""
    return name.lower().replace("_", "-")


def _spec_requirements() -> dict[str, Requirement]:
    reqs = {}
    for raw in SPEC_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        key = _canonical(req.name)
        assert key not in reqs, f"duplicate requirement: {req.name}"
        reqs[key] = req
    return reqs


def _lock_pins() -> dict[str, Version]:
    pins: dict[str, Version] = {}
    for raw in LOCK_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"lock line is not an exact pin: {line!r}"
        name, _, version = line.partition("==")
        key = _canonical(name.strip())
        assert key not in pins, f"duplicate lock pin: {key}"
        pins[key] = Version(version.strip())
    return pins


def test_requirements_txt_is_nonempty_intent_spec() -> None:
    assert len(_spec_requirements()) >= 15, "requirements.txt lost its floor ranges?"


def test_every_declared_requirement_is_satisfied_by_the_lock() -> None:
    pins = _lock_pins()
    missing = []
    unsatisfied = []
    for name, req in _spec_requirements().items():
        if name not in pins:
            missing.append(str(req))
            continue
        if not req.specifier.contains(pins[name], prereleases=True):
            unsatisfied.append(f"{req} not satisfied by lock pin {pins[name]}")
    assert not missing, "requirements.txt entries missing from requirements.lock (refresh the lock): " + "; ".join(missing)
    assert not unsatisfied, "lock pins drifted below the declared floors (bump spec + lock together): " + "; ".join(unsatisfied)


def test_lock_pins_are_exact_unique_versions() -> None:
    _lock_pins()  # assertions inside the parser cover duplicates and non-pins


@pytest.mark.parametrize(
    "package",
    ["numpy", "pandas", "scipy", "scikit-learn", "statsmodels", "fastapi", "pydantic"],
)
def test_quant_stack_is_locked_at_validated_majors(package: str) -> None:
    """The 2026-11-02 lock was suite-validated on these majors; a rollover
    here is a compatibility event, not a routine refresh."""
    expected_major = {
        "numpy": 2,
        "pandas": 3,
        "scipy": 1,
        "scikit-learn": 1,
        "statsmodels": 0,
        "fastapi": 0,
        "pydantic": 2,
    }[package]
    pin = _lock_pins()[_canonical(package)]
    assert pin.major == expected_major, (
        f"{package} lock pin moved to major {pin.major} (validated on {expected_major}) — "
        "re-run the full pytest suite against the new set before merging, then update this pin"
    )
