"""Severity gate over pip-audit results. Network lookups are not required."""

from __future__ import annotations

from scripts.pip_audit_gate import blocking, normalize_severity, severity_from_osv_document


def test_moderate_and_low_do_not_fail() -> None:
    findings = [
        ("pip", "24.0", "GHSA-example", "MEDIUM"),
        ("pip", "24.0", "GHSA-other", "LOW"),
    ]
    assert blocking(findings) == []


def test_high_critical_and_unknown_fail() -> None:
    findings = [
        ("cryptography", "1.0", "GHSA-high", "HIGH"),
        ("cryptography", "1.0", "GHSA-crit", "CRITICAL"),
        ("cryptography", "1.0", "GHSA-unk", "UNKNOWN"),
    ]
    assert [row[2] for row in blocking(findings)] == ["GHSA-high", "GHSA-crit", "GHSA-unk"]


def test_osv_moderate_normalizes() -> None:
    assert normalize_severity("MODERATE") == "MEDIUM"
    assert severity_from_osv_document({"database_specific": {"severity": "HIGH"}}) == "HIGH"
    assert severity_from_osv_document({}) == "UNKNOWN"
