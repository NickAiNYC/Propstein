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


def verify_commit(ref: str) -> bool:
    try:
        _git("rev-parse", "--verify", f"{ref}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def try_fetch(ref: str) -> bool:
    try:
        subprocess.check_output(
            ["git", "fetch", "origin", ref, "--depth=2"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
        return verify_commit(ref)
    except subprocess.CalledProcessError:
        return False


def get_merge_base(target: str = "origin/main", head: str = "HEAD") -> str | None:
    try:
        out = _git("merge-base", target, head).strip()
        if out:
            return out
    except subprocess.CalledProcessError:
        pass

    target_ref = target.removeprefix("origin/")
    if try_fetch(target_ref):
        try:
            out = _git("merge-base", target, head).strip()
            if out:
                return out
        except subprocess.CalledProcessError:
            pass
    return None


def resolve_base() -> str | None:
    raw_base = os.environ.get("SIZE_GATE_BASE", "").strip()
    if raw_base and set(raw_base) != {"0"}:
        if verify_commit(raw_base):
            return raw_base
        if try_fetch(raw_base):
            return raw_base

        fallback = get_merge_base("origin/main", "HEAD")
        if not fallback:
            if verify_commit("HEAD~1"):
                fallback = "HEAD~1"
            else:
                try_fetch("HEAD")
                if verify_commit("HEAD~1"):
                    fallback = "HEAD~1"

        if fallback:
            print(
                f"WARNING: Size-gate base commit '{raw_base}' is not available in local tree or remote. "
                f"Falling back to {fallback}.",
                file=sys.stderr,
            )
            return fallback

        print(
            f"WARNING: Size-gate base commit '{raw_base}' is not available and no fallback commit could be resolved.",
            file=sys.stderr,
        )
        return raw_base

    fallback = get_merge_base("origin/main", "HEAD")
    if fallback:
        try:
            head = _git("rev-parse", "HEAD").strip()
            if fallback == head:
                return None
            return fallback
        except subprocess.CalledProcessError:
            return fallback

    if verify_commit("origin/main"):
        try:
            head = _git("rev-parse", "HEAD").strip()
            main = _git("rev-parse", "origin/main").strip()
            if head == main:
                return None
            return "origin/main"
        except subprocess.CalledProcessError:
            pass

    return None


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


def blob_sizes(paths: list[str]) -> list[tuple[str, int]]:
    if not paths:
        return []
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch-check=%(objectsize)"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    input_data = "\n".join(f"HEAD:{p}" for p in paths) + "\n"
    stdout, _ = proc.communicate(input_data)
    results = []
    for path, line in zip(paths, stdout.splitlines()):
        try:
            results.append((path, int(line.strip())))
        except ValueError:
            results.append((path, blob_size(path)))
    return results


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
    paths = added_paths(base)
    added = blob_sizes(paths)
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
