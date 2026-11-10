"""PropStein pipeline — CLI orchestrator.

Usage:
  python -m pipeline run   [--date YYYY-MM-DD] [--source auto|synthetic|licensed]
                           [--backfill N] [--fail-on-conflict]
  python -m pipeline validate
  python -m pipeline report  [--summary-path PATH]
  python -m pipeline index

Determinism: PYTHONHASHSEED=0 is exported at startup (canonical JSON sorts
keys anyway; this is belt-and-braces parity with the TS domain core).

Exit codes: 0 ok · 2 validation failure · 3 immutability conflict ·
4 feed unavailable.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date, timedelta

# Determinism first, before any hashing runs.
os.environ.setdefault("PYTHONHASHSEED", "0")

from pipeline import config
from pipeline.engine import build_run
from pipeline.http import FeedUnavailableError
from pipeline.providers.base import select_feed
from pipeline.report import build_summary_markdown, write_summary
from pipeline.runs import (
    RunConflictError,
    ArtifactCorruptError,
    load_prior_runs,
    rebuild_index,
    write_latest,
    write_run,
)
from pipeline.validate import validate_artifact, validate_latest_json

EXIT = {
    "ok": config.EXIT_OK,
    "validation": config.EXIT_VALIDATION,
    "conflict": config.EXIT_CONFLICT,
    "feed": config.EXIT_FEED,
}


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_run(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    end = _parse_date(args.date) if args.date else date.today()
    dates = [end - timedelta(days=i) for i in range(args.backfill - 1, -1, -1)]

    feed = select_feed(args.source)
    print(f"[pipeline] source={args.source} feed={feed.id} dates={[d.isoformat() for d in dates]}")

    for run_date in dates:
        try:
            slate = feed.fetch_slate(run_date)
        except FeedUnavailableError as exc:
            print(f"[pipeline] FEED FAILURE on {run_date}: {exc}", file=sys.stderr)
            return EXIT["feed"]

        priors = load_prior_runs(run_date.isoformat(), config.SCORING_WINDOW_RUNS)
        artifact = build_run(slate, priors)

        validation = validate_artifact(artifact)
        if not validation.ok:
            _print_validation(run_date, validation)
            return EXIT["validation"]

        try:
            status = write_run(artifact)
        except RunConflictError as exc:
            _print_validation(run_date, validate_artifact(artifact))
            if args.fail_on_conflict:
                print(f"[pipeline] CONFLICT on {run_date}: {exc}", file=sys.stderr)
                return EXIT["conflict"]
            print(f"[pipeline] conflict on {run_date} treated as advisory: {exc}", file=sys.stderr)

        if run_date == dates[-1]:
            write_latest(artifact)
            summary = build_summary_markdown(artifact, validation)
            write_summary(summary, args.summary_path)

        print(
            f"[pipeline] run {run_date} {status}: "
            f"{len(artifact.predictions)} predictions, "
            f"{artifact.metrics.n_events} events, "
            f"brier={artifact.metrics.brier} "
            f"hash={artifact.integrity_hash[:12]}"
        )

    index = rebuild_index()
    print(
        f"[pipeline] index rebuilt: {len(index.runs)} runs, "
        f"latest={index.latest_run_date}, health={index.health}"
    )
    return EXIT["ok"]


def cmd_validate(_args: argparse.Namespace) -> int:
    report = validate_latest_json()
    for c in report.checks:
        mark = "OK " if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['name']}: {c['detail']}")
    return EXIT["ok"] if report.ok else EXIT["validation"]


def cmd_report(args: argparse.Namespace) -> int:
    from pipeline.runs import list_run_dates, load_run

    dates = list_run_dates()
    if not dates:
        print("[pipeline] no runs stored; nothing to report", file=sys.stderr)
        return EXIT["validation"]
    artifact = load_run(dates[-1])
    if artifact is None:
        return EXIT["validation"]
    validation = validate_artifact(artifact)
    markdown = build_summary_markdown(artifact, validation)
    path = write_summary(markdown, args.summary_path)
    print(f"[pipeline] summary written to {path}")
    return EXIT["ok"] if validation.ok else EXIT["validation"]


def cmd_index(_args: argparse.Namespace) -> int:
    index = rebuild_index()
    print(f"[pipeline] {len(index.runs)} runs, health={index.health} ({index.health_reason})")
    return EXIT["ok"]


def _print_validation(run_date: date, validation) -> None:
    print(f"[pipeline] VALIDATION FAILURE on {run_date}:", file=sys.stderr)
    for c in validation.checks:
        if not c["passed"]:
            print(f"  [FAIL] {c['name']}: {c['detail']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="PropStein daily pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="fetch, infer, score, and store one or more runs")
    p_run.add_argument("--date", help="run date YYYY-MM-DD (default: today)")
    p_run.add_argument("--source", choices=["auto", "synthetic", "licensed"], default="auto")
    p_run.add_argument("--backfill", type=int, default=1, help="number of consecutive days ending at --date")
    p_run.add_argument("--fail-on-conflict", action="store_true")
    p_run.add_argument("--summary-path", default=None)
    p_run.set_defaults(func=cmd_run)

    p_val = sub.add_parser("validate", help="sanity-check the stored latest artifact")
    p_val.set_defaults(func=cmd_validate)

    p_rep = sub.add_parser("report", help="write the job summary from the latest run")
    p_rep.add_argument("--summary-path", default=None)
    p_rep.set_defaults(func=cmd_report)

    p_idx = sub.add_parser("index", help="rebuild the runs index / telemetry")
    p_idx.set_defaults(func=cmd_index)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FeedUnavailableError as exc:
        print(f"[pipeline] FEED FAILURE: {exc}", file=sys.stderr)
        return EXIT["feed"]
    except RunConflictError as exc:
        print(f"[pipeline] CONFLICT: {exc}", file=sys.stderr)
        return EXIT["conflict"]
    except ArtifactCorruptError as exc:
        print(f"[pipeline] CORRUPT ARTIFACT: {exc}", file=sys.stderr)
        return EXIT["validation"]
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
