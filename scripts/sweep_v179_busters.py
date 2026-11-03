#!/usr/bin/env python3
"""
v179 three-piece cache-bust sweep (Ice-blue PropStein brand alignment).
Bumps:
  buster     2026_v178 / 2026_v176 / 2026_v177 -> 2026_v179
  SW cache   propstein-v178-prod               -> propstein-v179-prod
  build-hash 2026-w8-v29                       -> 2026-w8-v30
"""

from __future__ import annotations
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent.parent
VIEWER = BASE / "viewer"

FILES = [
    VIEWER / "index.html",
    VIEWER / "ledger.html",
    VIEWER / "ledger" / "index.html",
    VIEWER / "audit.html",
    VIEWER / "verify.html",
    VIEWER / "site.webmanifest",
    VIEWER / "sw.js",
    BASE / "scripts" / "verify_v152_books.mjs",
    BASE / "scripts" / "verify_v153_rebrand.mjs",
    BASE / "scripts" / "verify_v154_dropwire.mjs",
]

def main():
    for f in FILES:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        text = re.sub(r'2026_v17[1-8]', '2026_v179', text)
        text = re.sub(r'prop(?:wire|stein)-v17[1-8]-prod', 'propstein-v179-prod', text)
        text = re.sub(r'2026-w8-v2[0-9]', '2026-w8-v30', text)
        f.write_text(text, encoding="utf-8")
        print(f"Updated {f}")

if __name__ == "__main__":
    main()
