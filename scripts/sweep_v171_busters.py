#!/usr/bin/env python3
"""v171 buster sweep — cache-bust + CSP-clean rescue for the Antigravity
Polymarket arb pane / Alert Routing UI commits (ab04158, 3337233).

Bumps every 2026_v170 -> 2026_v171, the SW cache propwire-v170-prod ->
propwire-v171-prod, and the build-hash meta 2026-w8-v23 -> 2026-w8-v24
across the 5 terminal pages, sw.js, and site.webmanifest.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "viewer"
PAGES = [
    ROOT / "index.html",
    ROOT / "ledger.html",
    ROOT / "audit.html",
    ROOT / "verify.html",
    ROOT / "ledger" / "index.html",
]
EXTRAS = [ROOT / "sw.js", ROOT / "site.webmanifest"]

SWAPS = [
    ("2026_v170", "2026_v171"),
    ("propwire-v170-prod", "propwire-v171-prod"),
    ("2026-w8-v23", "2026-w8-v24"),
]

failures = []
for f in PAGES + EXTRAS:
    if not f.exists():
        failures.append(f"MISSING: {f}")
        continue
    text = f.read_text(encoding="utf-8")
    orig = text
    for old, new in SWAPS:
        text = text.replace(old, new)
    if text != orig:
        f.write_text(text, encoding="utf-8")
        print(f"swept: {f.relative_to(ROOT.parent)}")
    else:
        print(f"no-op: {f.relative_to(ROOT.parent)}")

# verification pass
leftover = []
for f in PAGES + EXTRAS:
    t = f.read_text(encoding="utf-8")
    for old, _ in SWAPS:
        if old in t:
            leftover.append(f"{f.name}: stale '{old}'")
if leftover:
    print("\n".join(leftover))
    sys.exit(1)
print("SWEEP CLEAN — zero stale v170 refs")
