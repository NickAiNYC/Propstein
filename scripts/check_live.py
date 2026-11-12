#!/usr/bin/env python3
"""Public GET check for the five live strings. No credentials."""

from __future__ import annotations

import sys
import urllib.request

CHECKS = (
    ("https://propstein.com/", "2/37"),
    (
        "https://propstein.com/performance/",
        "Auto-grade off. No close tape with captured_at < kickoff_at exists.",
    ),
    (
        "https://propstein.com/nfl/00-0039075/receiving_yards/",
        "This is not a pick and not a price.",
    ),
    (
        "https://propstein.com/precommit",
        "COMMITTED and AWAITING_CLOSE only",
    ),
    (
        "https://propstein.com/app.js",
        "Grading off. Log 1u rows stay UNGRADED until a proved close tape exists.",
    ),
)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "PropStein-check-live"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def main() -> int:
    failed = False
    for url, needle in CHECKS:
        try:
            body = fetch(url)
        except Exception as exc:
            print(f"FAIL {url} {exc.__class__.__name__}", file=sys.stderr)
            failed = True
            continue
        if needle not in body:
            print(f"FAIL {url} missing required string", file=sys.stderr)
            failed = True
            continue
        print(f"ok {url}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
