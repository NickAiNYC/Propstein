#!/usr/bin/env python3
"""
Root entry point for the CLV Validation Engine.
Usage: python3 grade_clv.py [--snapshots PATH] [--output PATH] [--hurdle 0.10]
       python3 grade_clv.py --sport ufc   # UFC ledger -> viewer/ufc_ledger.json
"""

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.grade_clv import main

if __name__ == "__main__":
    if "--sport" in sys.argv and sys.argv[sys.argv.index("--sport") + 1:][:1] == ["ufc"]:
        # UFC: h2h CLV vs lock snapshot; draw/NC/cancel/scratch = void (push).
        import subprocess
        sys.exit(subprocess.call([sys.executable, str(BASE_DIR / "scripts" / "fetch_ufc_odds.py"), "--grade"]))
    main()
