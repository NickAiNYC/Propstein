#!/usr/bin/env python3
"""
v172 three-piece cache-bust sweep (mission W3/W5 — viewer assets changed).

Bumps, in ALL viewer HTML pages + sw.js + site.webmanifest:
  buster     2026_v171          -> 2026_v172
  SW cache   propwire-v171-prod -> propwire-v172-prod
  build-hash 2026-w8-v24        -> 2026-w8-v25

NOTE: the PAGES list intentionally omits `ledger/index.html` — that path never
existed in any revision of this repo (verified via `git log --all` in Task 58);
the /ledger route is a vercel.json rewrite to /index.html.
"""

from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VIEWER = BASE / "viewer"

PAGES = [
    VIEWER / "index.html",
    VIEWER / "ledger.html",
    VIEWER / "ledger" / "index.html",
    VIEWER / "audit.html",
    VIEWER / "verify.html",
]
EXTRAS = [
    VIEWER / "sw.js",
    VIEWER / "site.webmanifest",
]

SWAPS = [
    ("2026_v171", "2026_v172"),
    ("propwire-v171-prod", "propwire-v172-prod"),
    ("2026-w8-v24", "2026-w8-v25"),
]


def sweep() -> None:
    changed = 0
    for path in PAGES + EXTRAS:
        if not path.exists():
            raise SystemExit(f"FATAL: expected file missing: {path}")
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in SWAPS:
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1
            print(f"[sweep] updated {path.relative_to(BASE)}")
        else:
            print(f"[sweep] no change  {path.relative_to(BASE)}")

    # Verification pass: zero stale v171 markers anywhere in viewer assets.
    stale = []
    for path in PAGES + EXTRAS:
        text = path.read_text(encoding="utf-8")
        for old, _new in SWAPS:
            if old in text:
                stale.append(f"{path.relative_to(BASE)} contains stale {old}")
    if stale:
        for line in stale:
            print(f"[sweep] STALE: {line}")
        raise SystemExit("SWEEP FAILED — stale v171 refs remain")

    print("SWEEP CLEAN — zero stale v171 refs; all viewer assets on v172 discipline.")


if __name__ == "__main__":
    sweep()
