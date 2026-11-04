#!/usr/bin/env python3
"""Fail when a newly added git path exceeds the size threshold and is not allowlisted.

"Newly added" is relative to SIZE_GATE_BASE (a commit). Updates to paths that
already exist on that commit are not treated as new files. The allowlist holds
the frozen snapshots and hash-gated artifacts that are already in the tree.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / ".github" / "large-file-allowlist.txt"
THRESHOLD_BYTES = 500 * 1024


def load_allowlist(path: Path = ALLOWLIST_PATH) -> set[str]:
    entries: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def violations(added: list[tuple[str, int]], allow: set[str], threshold: int = THRESHOLD_BYTES) -> list[tuple[str, int]]:
    return [(path, size) for path, size in added if size > threshold and path not in allow]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.PIPE)


def resolve_base() -> str | None:
    base = os.environ.get("SIZE_GATE_BASE", "").strip()
    if base and set(base) != {"0"}:
        return base
    try:
        _git("rev-parse", "--verify", "origin/main")
    except subprocess.CalledProcessError:
        return None
    head = _git("rev-parse", "HEAD").strip()
    main = _git("rev-parse", "origin/main").strip()
    if head == main:
        return None
    return "origin/main"


def added_paths(base: str) -> list[str]:
    out = _git("diff", "--name-status", "--diff-filter=AR", base, "HEAD")
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("A") or status.startswith("R"):
            paths.append(parts[-1])
    return paths


def blob_size(path: str) -> int:
    return int(_git("cat-file", "-s", f"HEAD:{path}").strip())


def main() -> int:
    base = resolve_base()
    if base is None:
        print("No size-gate base commit; no newly added files to check.")
        return 0
    try:
        _git("rev-parse", "--verify", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        print(f"Size-gate base commit is not available: {base}", file=sys.stderr)
        return 1
    allow = load_allowlist()
    added = [(path, blob_size(path)) for path in added_paths(base)]
    failed = violations(added, allow)
    if not failed:
        print(f"No new files over {THRESHOLD_BYTES} bytes (base {base}).")
        return 0
    print(f"Newly added files over {THRESHOLD_BYTES} bytes must be allowlisted in {ALLOWLIST_PATH}:", file=sys.stderr)
    for path, size in failed:
        print(f"  {size} bytes  {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        print(detail or f"git command failed: {exc.cmd}", file=sys.stderr)
        raise SystemExit(1)
