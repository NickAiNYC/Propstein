#!/usr/bin/env python3
"""nba_model local worker — the residential-IP leg of the free topology.

NBA's official feeds block datacenter IPs (empirically confirmed
2026-11-03: stats.nba.com blackholes cloud hosts including GitHub Actions
runners; cdn.nba.com Akamai-403s them — see src/nba_model/DECISIONS.md
D7). This script runs the SAME pipeline the Actions workflow would run,
from a residential IP (your machine, or a self-hosted runner pointed at
it), and commits the artifacts to viewer/feeds/nba_model/ — the exact
commit the workflow would have made. Git stays the cache layer; Vercel
serves it statically.

Usage:
  python3 scripts/nba_model_local_worker.py                 # run + commit
  python3 scripts/nba_model_local_worker.py --push          # run + commit + push
  python3 scripts/nba_model_local_worker.py --season-start 2026-10-20

Schedule it with cron/launchd, e.g. weekdays 07:00 ET:
  0 7 * * *  cd /path/to/Propstein && python3 scripts/nba_model_local_worker.py --push

Exit codes mirror the CLI: 0 ok (gates REFUSED counts as ok — the refusal
artifact is the honest outcome); any provider failure exits non-zero and
commits NOTHING (fail-closed, no partial artifacts).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "nba_model" / "out"
FEED = REPO / "viewer" / "feeds" / "nba_model"
SEASON_START_DEFAULT = "2026-10-20"

ARTIFACTS = [
    "nba_board_*.json",
    "nba_board_history.jsonl",
    "nba_walkforward_summary.json",
    "nba_dataset_meta.json",
]


def run(cmd: list, env: dict) -> int:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=str(REPO), env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season-start", default=SEASON_START_DEFAULT,
                    help="NBA season opening night, ET (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, default=45,
                    help="rolling window length in days (bounded runtime)")
    ap.add_argument("--push", action="store_true", help="git push after committing")
    args = ap.parse_args()

    end = date.today() - timedelta(days=1)   # data through yesterday ET
    start = max(date.fromisoformat(args.season_start),
                end - timedelta(days=max(0, args.days - 1)))
    window = (start.isoformat(), end.isoformat())
    print(f"NBA model window: {window[0]} .. {window[1]} (ET, stats.nba.com free path)")

    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}

    if run([sys.executable, "src/nba_model/cli.py", "prepare",
            "--provider", "nbacom", "--start", window[0], "--end", window[1]],
           env) != 0:
        print("prepare failed — fail-closed, nothing committed.", file=sys.stderr)
        return 5

    code = run([sys.executable, "src/nba_model/cli.py", "publish",
                "--provider", "nbacom", "--start", window[0], "--end", window[1]],
               env)
    if code not in (0, 10):
        print(f"publish failed with exit {code} — fail-closed, nothing committed.",
              file=sys.stderr)
        return code
    if code == 10:
        print("publish REFUSED by gates (expected while uncalibrated / no odds "
              "feed wired) — committing the refusal artifact as the honest record.")

    FEED.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pattern in ARTIFACTS:
        for artifact in OUT.glob(pattern):
            target = FEED / artifact.name
            target.write_bytes(artifact.read_bytes())
            copied += 1
    print(f"staged {copied} artifact(s) -> {FEED.relative_to(REPO)}")
    if copied == 0:
        print("no artifacts produced — nothing to commit.", file=sys.stderr)
        return 5

    git = ["git", "-C", str(REPO)]
    if run(git + ["add", "viewer/feeds/nba_model"], env) != 0:
        return 1
    dirty = subprocess.run(git + ["diff", "--staged", "--quiet"], env=env).returncode != 0
    if not dirty:
        print("No artifact changes — nothing to commit.")
        return 0
    if run(git + ["commit", "-m",
                  f"chore(data): NBA model local-worker refresh {date.today().isoformat()} [skip ci]"],
           env) != 0:
        return 1
    if args.push:
        if run(git + ["pull", "--rebase", "origin", "main"], env) != 0:
            return 1
        return run(git + ["push", "origin", "HEAD:main"], env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
