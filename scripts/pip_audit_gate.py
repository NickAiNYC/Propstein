#!/usr/bin/env python3
"""Fail the build when pip-audit reports a high or critical vulnerability.

Low, moderate, and medium advisories are printed and do not fail the gate.
Unknown severity fails closed. The locked requirements and the installed
environment (including pip itself) are both audited.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
FAIL_SEVERITIES = {"HIGH", "CRITICAL", "UNKNOWN"}
_SEVERITY_CACHE: dict[str, str] = {}


def normalize_severity(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    label = value.strip().upper()
    if label == "MODERATE":
        return "MEDIUM"
    if label in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        return label
    return "UNKNOWN"


def severity_from_osv_document(doc: dict) -> str:
    database = doc.get("database_specific") or {}
    label = normalize_severity(database.get("severity") if isinstance(database, dict) else None)
    if label != "UNKNOWN":
        return label
    return "UNKNOWN"


def lookup_severity(vuln_id: str) -> str:
    cached = _SEVERITY_CACHE.get(vuln_id)
    if cached is not None:
        return cached
    url = "https://api.osv.dev/v1/vulns/" + urllib.parse.quote(vuln_id)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            doc = json.load(response)
    except Exception:
        label = "UNKNOWN"
    else:
        label = severity_from_osv_document(doc)
    _SEVERITY_CACHE[vuln_id] = label
    return label


def resolve_severity(vuln: dict) -> str:
    ids = [vuln.get("id"), *(vuln.get("aliases") or [])]
    for vuln_id in ids:
        if not vuln_id:
            continue
        label = lookup_severity(str(vuln_id))
        if label != "UNKNOWN":
            return label
    return "UNKNOWN"


def blocking(findings: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    """findings are (name, version, vuln id, severity)."""
    return [row for row in findings if row[3] in FAIL_SEVERITIES]


def _audit_args(extra: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip_audit",
        *extra,
        "--format",
        "json",
        "--progress-spinner",
        "off",
        "--desc",
        "off",
    ]


def run_pip_audit(extra: list[str]) -> dict:
    with tempfile.NamedTemporaryFile(prefix="pip-audit-", suffix=".json") as handle:
        cmd = _audit_args([*extra, "--output", handle.name])
        completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        raw = Path(handle.name).read_text() or "{}"
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(completed.stderr or completed.stdout or "")
        raise SystemExit(f"pip-audit did not return JSON ({exc})") from exc
    if completed.returncode not in (0, 1):
        sys.stderr.write(completed.stderr or "")
        raise SystemExit(f"pip-audit failed (exit {completed.returncode})")
    if not isinstance(report, dict):
        raise SystemExit("pip-audit JSON was not an object")
    return report


def collect(report: dict) -> list[tuple[str, str, dict]]:
    rows = []
    for dep in report.get("dependencies") or []:
        name = str(dep.get("name"))
        version = str(dep.get("version"))
        for vuln in dep.get("vulns") or []:
            rows.append((name, version, vuln))
    return rows


def main() -> int:
    reports = [
        run_pip_audit(["--requirement", str(LOCK), "--no-deps", "--disable-pip"]),
        run_pip_audit([]),
    ]
    seen: set[tuple[str, str, str]] = set()
    findings: list[tuple[str, str, str, str]] = []
    for report in reports:
        for name, version, vuln in collect(report):
            vuln_id = str(vuln.get("id") or "UNKNOWN-ID")
            key = (name, version, vuln_id)
            if key in seen:
                continue
            seen.add(key)
            severity = resolve_severity(vuln)
            findings.append((name, version, vuln_id, severity))
            print(f"{severity}\t{name}=={version}\t{vuln_id}")
    blocked = blocking(findings)
    if blocked:
        print(f"{len(blocked)} high/critical/unknown advisory(ies); failing.", file=sys.stderr)
        return 1
    if findings:
        print(f"{len(findings)} advisory(ies) below high; not failing.")
    else:
        print("No known vulnerabilities in the locked set or the installed environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
