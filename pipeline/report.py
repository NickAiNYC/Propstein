"""PropStein pipeline — GitHub Actions Job Summary reporter.

Writes a clean Markdown summary to $GITHUB_STEP_SUMMARY (or a given path):
  - run identity, source, duration
  - prediction / event counts, coverage mix
  - day-over-day movement stats
  - self-scoring: Brier, hit rate, calibration table
  - top 5 tightest-confidence outputs of the day (narrowest uncertainty band
    among calibrated rows — descriptive ranking, never a pick list)
  - sanity-check table

All copy passes the charter vocabulary (no picks / edge / urgency language).
"""

from __future__ import annotations

from pathlib import Path

from pipeline.schemas import RunArtifact
from pipeline.validate import ValidationReport


def build_summary_markdown(artifact: RunArtifact, report: ValidationReport) -> str:
    m = artifact.metrics
    duration_ms = sum(s.duration_ms for s in artifact.execution)
    lines: list[str] = []

    lines.append("## PropStein daily model run")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"| --- | --- |")
    lines.append(f"| Run date | `{artifact.run_date}` |")
    lines.append(f"| Run ID | `{artifact.run_id}` |")
    lines.append(f"| Data source | {artifact.source} (`{artifact.odds_provider}`) |")
    lines.append(f"| Pipeline version | {artifact.pipeline_version} |")
    lines.append(f"| Records analyzed | {artifact.n_records_analyzed} |")
    lines.append(f"| Predictions generated | {m.n_predictions} |")
    lines.append(f"| Distinct events | {m.n_events} |")
    lines.append(f"| Execution time | {duration_ms / 1000.0:.1f}s |")
    lines.append(f"| Integrity hash | `{artifact.integrity_hash[:16]}…` |")
    lines.append("")

    lines.append("### Coverage mix")
    lines.append("")
    lines.append("| Calibrated | Uncalibrated | No model |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| {m.coverage_mix.calibrated} | {m.coverage_mix.uncalibrated} | {m.coverage_mix.none} |")
    lines.append("")

    lines.append("### Day-over-day movement (model probability)")
    lines.append("")
    lines.append("| Compared | New | Dropped | Mean abs Δ | Max abs Δ |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| {m.delta.n_compared} | {m.delta.n_new} | {m.delta.n_dropped} | "
        f"{_fmt(m.delta.mean_abs_delta_pp, 'pp')} | {_fmt(m.delta.max_abs_delta_pp, 'pp')} |"
    )
    lines.append("")

    if m.brier is not None:
        lines.append("### Self-scoring (settled history window)")
        lines.append("")
        lines.append("| Scored | Brier | Hit rate |")
        lines.append("| --- | --- | --- |")
        lines.append(f"| {m.n_settled_scored} | {m.brier:.4f} | {_pct(m.hit_rate)} |")
        lines.append("")

    if m.calibration:
        lines.append("### Calibration (predicted vs observed, deciles)")
        lines.append("")
        lines.append("| Bucket | N | Predicted | Observed |")
        lines.append("| --- | --- | --- | --- |")
        for row in m.calibration:
            lines.append(f"| {row.bucket} | {row.n} | {row.predicted:.3f} | {row.observed:.3f} |")
        lines.append("")

    top = _top_confidence(artifact, 5)
    if top:
        lines.append("### Tightest uncertainty bands today (top 5)")
        lines.append("")
        lines.append("| Player | Market | Line | Model P | 95% band | Assessment |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for p in top:
            band = f"[{p.model.uncertainty.lower:.3f}, {p.model.uncertainty.upper:.3f}]" if p.model.uncertainty else "—"
            lines.append(
                f"| {p.player_name} | {p.market_label} | {p.line} | "
                f"{p.model.probability:.3f} | {band} | {p.price_assessment.value} |"
            )
        lines.append("")

    if m.exclusions:
        lines.append("### Exclusions (retained, with reasons)")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("| --- | --- |")
        for exc in m.exclusions:
            lines.append(f"| {exc.reason} | {exc.count} |")
        lines.append("")

    lines.append("### Sanity checks")
    lines.append("")
    lines.append("| Check | Result | Detail |")
    lines.append("| --- | --- | --- |")
    for c in report.checks:
        mark = "✅" if c["passed"] else "❌"
        lines.append(f"| {c['name']} | {mark} | {c['detail']} |")
    lines.append("")

    lines.append("_Descriptive diagnostics only. Not a betting recommendation._")
    lines.append("")
    return "\n".join(lines)


def write_summary(markdown: str, path: str | None = None) -> Path:
    import os

    target = Path(path or os.environ.get("GITHUB_STEP_SUMMARY") or "pipeline_summary.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(markdown)
    return target


def _top_confidence(artifact: RunArtifact, n: int):
    calibrated = [
        p
        for p in artifact.predictions
        if p.model.uncertainty is not None and p.model.probability is not None
    ]
    calibrated.sort(key=lambda p: (p.model.uncertainty.upper - p.model.uncertainty.lower))
    return calibrated[:n]


def _fmt(v: float | None, unit: str) -> str:
    return f"{v:.2f} {unit}" if v is not None else "—"


def _pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


__all__ = ["build_summary_markdown", "write_summary"]
