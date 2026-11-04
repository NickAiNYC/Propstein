"""Size gate: newly added files over 500 KB must be allowlisted."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_large_files import THRESHOLD_BYTES, load_allowlist, violations

ROOT = Path(__file__).resolve().parents[1]


def test_threshold_is_500_kib() -> None:
    assert THRESHOLD_BYTES == 500 * 1024


def test_unlisted_new_file_over_threshold_fails() -> None:
    allow = load_allowlist()
    failed = violations([("notes/new-export.json", THRESHOLD_BYTES + 1)], allow)
    assert failed == [("notes/new-export.json", THRESHOLD_BYTES + 1)]


def test_allowlisted_snapshot_over_threshold_passes() -> None:
    allow = load_allowlist()
    path = "viewer/snapshots_2026_w7.json"
    assert path in allow
    assert violations([(path, 2_000_000)], allow) == []


def test_file_at_threshold_passes() -> None:
    assert violations([("notes/exact.bin", THRESHOLD_BYTES)], load_allowlist()) == []


def test_allowlist_entries_are_tracked() -> None:
    missing = []
    for path in sorted(load_allowlist()):
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{path}"],
            cwd=ROOT,
            capture_output=True,
        )
        if probe.returncode != 0:
            missing.append(path)
    assert missing == []


def test_existing_branch_adds_no_oversized_files() -> None:
    completed = subprocess.run(
        ["python3", "scripts/check_large_files.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
