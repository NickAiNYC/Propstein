"""PropStein pipeline — daily run snapshot store.

Storage contract:
  data/runs/YYYY-MM-DD.json   immutable daily snapshots (history is never
                              overwritten: same hash -> no-op, different hash
                              on an existing date -> loud conflict error)
  data/latest_predictions.json today's board (rewritten every run; a copy of
                              the day's artifact plus nothing else — the web
                              app reads this with zero post-processing)
  data/runs_index.json         telemetry index (health, dates, counts)

Idempotency: re-running a date either reproduces the identical artifact
(hash-verified) or fails with RunConflictError — yesterday's predictions are
never blindly overwritten (Phase 3 requirement).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline import config
from pipeline.determinism import sha256_hex
from pipeline.schemas import IndexEntry, RunArtifact, RunsIndex


class RunConflictError(RuntimeError):
    """An existing run artifact for the date differs from the new one."""


class ArtifactCorruptError(RuntimeError):
    """A stored artifact failed schema validation or integrity checking."""


def run_path(run_date: str) -> Path:
    return config.RUNS_DIR / f"{run_date}.json"


def load_run(run_date: str) -> RunArtifact | None:
    """Load and fully validate one run artifact (fail closed on corruption)."""
    path = run_path(run_date)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactCorruptError(f"{path}: invalid JSON: {exc}") from exc
    try:
        artifact = RunArtifact.model_validate(doc)
    except Exception as exc:  # pydantic ValidationError
        raise ArtifactCorruptError(f"{path}: schema validation failed: {exc}") from exc
    if artifact.integrity_hash != compute_integrity_hash(artifact):
        raise ArtifactCorruptError(f"{path}: integrity hash mismatch")
    return artifact


def list_run_dates() -> list[str]:
    if not config.RUNS_DIR.exists():
        return []
    return sorted(
        p.stem for p in config.RUNS_DIR.glob("*.json") if _is_date(p.stem)
    )


def load_prior_runs(run_date: str, window: int) -> list[RunArtifact]:
    """Load the N most recent artifacts strictly before run_date."""
    priors: list[RunArtifact] = []
    for d in reversed(list_run_dates()):
        if d >= run_date:
            continue
        run = load_run(d)
        if run is not None:
            priors.append(run)
        if len(priors) >= window:
            break
    return priors


def write_run(artifact: RunArtifact) -> str:
    """Write the daily snapshot. Returns 'written' | 'unchanged' (idempotent)."""
    path = run_path(artifact.run_date)
    payload = artifact.model_dump_json(indent=2)
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip("\n")
        if existing == payload:
            return "unchanged"
        raise RunConflictError(
            f"{path} exists with different content; daily snapshots are immutable "
            "(investigate the non-determinism before overwriting history)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")
    return "written"


def write_latest(artifact: RunArtifact) -> None:
    config.LATEST_PATH.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")


def compute_integrity_hash(artifact: RunArtifact) -> str:
    """Hash over the artifact content with the hash field itself excluded."""
    doc = artifact.model_dump()
    doc.pop("integrity_hash", None)
    doc.pop("execution", None)  # durations are environment-dependent
    return sha256_hex(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def rebuild_index(health_override: str | None = None) -> RunsIndex:
    """Rebuild runs_index.json from the stored snapshots."""
    entries: list[IndexEntry] = []
    runs: list[RunArtifact] = []
    for d in list_run_dates():
        run = load_run(d)
        if run is None:
            continue
        runs.append(run)
        entries.append(
            IndexEntry(
                run_date=run.run_date,
                run_id=run.run_id,
                prediction_count=len(run.predictions),
                n_records_analyzed=run.n_records_analyzed,
                integrity_hash=run.integrity_hash,
                duration_ms=sum(s.duration_ms for s in run.execution),
                source=run.source,
                pipeline_version=run.pipeline_version,
                generated_at_utc=run.generated_at_utc,
            )
        )

    now = datetime.now(timezone.utc)
    health, reason = _health_of(runs, now)
    if health_override:
        health = health_override
    index = RunsIndex(
        updated_at_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        latest_run_date=runs[-1].run_date if runs else None,
        health=health,
        health_reason=reason,
        runs=entries,
    )
    config.INDEX_PATH.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return index


def _health_of(runs: list[RunArtifact], now: datetime) -> tuple[str, str]:
    if not runs:
        return "down", "No run artifacts stored."
    latest = runs[-1]
    generated = datetime.strptime(latest.generated_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    age_hours = (now - generated).total_seconds() / 3600.0
    if age_hours > config.MAX_BOARD_AGE_HOURS:
        return "down", f"Last run is {age_hours:.1f}h old (threshold {config.MAX_BOARD_AGE_HOURS}h)."
    if age_hours > config.MAX_BOARD_AGE_HOURS / 2.0:
        return "degraded", f"Last run is {age_hours:.1f}h old; approaching staleness threshold."
    if latest.source == "synthetic":
        return "healthy", "Pipeline completed on schedule. Data source: simulated (reference deployment)."
    return "healthy", "Pipeline completed on schedule."


def _is_date(stem: str) -> bool:
    try:
        date.fromisoformat(stem)
        return True
    except ValueError:
        return False


__all__ = [
    "ArtifactCorruptError",
    "RunConflictError",
    "compute_integrity_hash",
    "list_run_dates",
    "load_prior_runs",
    "load_run",
    "rebuild_index",
    "run_path",
    "write_latest",
    "write_run",
]
