"""Structural slip audit on already-confirmed legs.

Overlap findings are same player, same team, same event, and duplicate
selections. There is no shared-assumption finding. Unconfirmed legs are
rejected and are not analyzed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.ledger.registry import STRUCTURAL_DISCLAIMER, RegistryMismatch, require_active_registration

SCOPE_MARKETS = frozenset({"player_receptions", "player_reception_yds"})


class UnconfirmedLegRejected(ValueError):
    """A leg was not confirmed. Nothing is analyzed and nothing is saved."""


@dataclass(frozen=True)
class Leg:
    player_id: str
    event_id: str
    event_start_at: str
    market: str
    selection: str
    line: float
    user_confirmed: bool
    team: str | None = None
    book: str | None = None
    research_reference_id: str | None = None
    ocr_confidence: float | None = None
    ocr_confirmed: bool | None = None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    leg_indexes: tuple[int, ...]
    detail: str
    disclaimer: str


@dataclass(frozen=True)
class AuditResult:
    findings: tuple[Finding, ...]
    disclaimer: str
    registration_id: str | None


def _groups(indexes: list[int]) -> list[tuple[int, ...]]:
    if len(indexes) < 2:
        return []
    return [tuple(indexes)]


def audit_confirmed_legs(
    legs: list[Leg],
    registration: dict | None,
    *,
    reference_exists=None,
) -> AuditResult:
    artifact = require_active_registration(registration)
    if not legs:
        raise ValueError("a slip needs at least one leg")
    if any(not leg.user_confirmed for leg in legs):
        raise UnconfirmedLegRejected("unconfirmed legs are rejected and are not analyzed")
    for leg in legs:
        if not str(leg.event_id).strip() or not str(leg.event_start_at).strip():
            raise ValueError("event_id and event_start_at are required on every leg")

    enabled = set(artifact["enabled_rules"])
    disabled = set(artifact["disabled_rules"])
    disclaimer = artifact["structural_disclaimer"]
    if disclaimer != STRUCTURAL_DISCLAIMER:
        raise RegistryMismatch("disclaimer mismatch")
    threshold = float(artifact["parameters"]["ocr_low_confidence_below"])
    scope = set(artifact["scope"]["markets"])
    findings: list[Finding] = []

    def add(rule_id: str, indexes: tuple[int, ...], detail: str) -> None:
        if rule_id not in enabled or rule_id in disabled:
            return
        findings.append(Finding(rule_id, indexes, detail, disclaimer))

    by_player: dict[str, list[int]] = {}
    by_team: dict[str, list[int]] = {}
    by_event: dict[str, list[int]] = {}
    by_selection: dict[tuple, list[int]] = {}
    for index, leg in enumerate(legs):
        by_player.setdefault(leg.player_id, []).append(index)
        if leg.team:
            by_team.setdefault(leg.team, []).append(index)
        by_event.setdefault(leg.event_id, []).append(index)
        key = (leg.player_id, leg.event_id, leg.market, leg.selection, round(float(leg.line), 4), leg.book or "")
        by_selection.setdefault(key, []).append(index)
        if leg.market not in scope:
            add("MARKET_UNSUPPORTED", (index,), f"Confirmed leg {index + 1} names a market outside the registered scope.")
        if leg.ocr_confidence is not None and leg.ocr_confidence < threshold:
            add("OCR_LOW_CONFIDENCE", (index,), f"Confirmed leg {index + 1} carries an OCR confidence below the registered threshold.")
        if leg.ocr_confirmed is False:
            add("OCR_UNCONFIRMED", (index,), f"Confirmed leg {index + 1} carries an OCR read that was not confirmed.")
        missing_ref = not leg.research_reference_id
        if leg.research_reference_id and reference_exists is not None:
            missing_ref = not reference_exists(leg.research_reference_id)
        if missing_ref:
            add("MISSING_REFERENCE", (index,), f"Confirmed leg {index + 1} has no research reference.")

    for indexes in by_player.values():
        grouped = _groups(indexes)
        if grouped:
            add("STRUCT_SAME_PLAYER", grouped[0], "Confirmed legs name the same player.")
    for indexes in by_team.values():
        grouped = _groups(indexes)
        if grouped:
            add("STRUCT_SAME_TEAM", grouped[0], "Confirmed legs name the same team.")
    for indexes in by_event.values():
        grouped = _groups(indexes)
        if grouped:
            add("STRUCT_SAME_GAME", grouped[0], "Confirmed legs name the same event.")
    for indexes in by_selection.values():
        grouped = _groups(indexes)
        if grouped:
            add("STRUCT_DUPLICATE_SELECTION", grouped[0], "Confirmed legs repeat the same selection.")

    if any(finding.rule_id in disabled for finding in findings):
        raise RegistryMismatch("a disabled rule emitted a finding")
    return AuditResult(tuple(findings), disclaimer, registration.get("id") if registration else None)
