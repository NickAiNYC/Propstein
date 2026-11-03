"""
Edge-Decay & Kickoff Urgency Scoring Engine
===========================================
Specification:
1. Urgency Score (0.0 to 1.0):
   - max(0, (90 - minutes_until_kickoff) / 90)
   - Cliff at kickoff -15 min -> 1.0
   - >90 min -> 0.0
2. Edge Tiers:
   - ALPHA: edge >= 10.0%
   - LEAN: 5.0% <= edge < 10.0%
   - BASE: 3.0% <= edge < 5.0%
   - SUB: edge < 3.0%
3. Decaying Edge Detection:
   - "⚠️ DECAYING EDGE" badge triggers ONLY when:
     edge_tier >= LEAN AND minutes_until_kickoff <= 15 AND current_edge < 0.95 * edge_when_detected.
4. Alpha Feed Sorting:
   - Ranked by: edge_tier DESC, then urgency_score DESC, then edge_pct DESC.
"""

from __future__ import annotations

from typing import Any, Optional

EDGE_TIER_ALPHA = "ALPHA"  # >= 10.0%
EDGE_TIER_LEAN = "LEAN"    # 5.0% - 10.0%
EDGE_TIER_BASE = "BASE"    # 3.0% - 5.0%
EDGE_TIER_SUB = "SUB"      # < 3.0%

EDGE_TIER_RANK: dict[str, int] = {
    EDGE_TIER_ALPHA: 3,
    EDGE_TIER_LEAN: 2,
    EDGE_TIER_BASE: 1,
    EDGE_TIER_SUB: 0,
}


def compute_urgency_score(minutes_until_kickoff: float) -> float:
    """
    Computes kickoff urgency score in [0.0, 1.0].
    - Cliff at <= 15 min: 1.0
    - Between 15 and 90 min: (90 - minutes) / 90
    - >= 90 min: 0.0
    """
    mins = float(minutes_until_kickoff)
    if mins <= 15.0:
        return 1.0
    if mins >= 90.0:
        return 0.0
    return round(max(0.0, min(1.0, (90.0 - mins) / 90.0)), 4)


def classify_edge_tier(edge: float) -> str:
    """
    Classify edge into ALPHA (>= 10%), LEAN (5-10%), BASE (3-5%), or SUB (< 3%).
    Handles both percentage values (e.g. 10.5) and fractional probabilities (e.g. 0.105).
    """
    pct = edge * 100.0 if abs(edge) <= 1.0 else edge
    if pct >= 10.0:
        return EDGE_TIER_ALPHA
    if pct >= 5.0:
        return EDGE_TIER_LEAN
    if pct >= 3.0:
        return EDGE_TIER_BASE
    return EDGE_TIER_SUB


def should_show_decaying_badge(
    *,
    edge_when_detected: float,
    current_edge: float,
    minutes_until_kickoff: float,
) -> bool:
    """
    '⚠️ DECAYING EDGE' badge triggers ONLY when:
      edge_tier >= LEAN AND minutes_until_kickoff <= 15 AND current_edge < 0.95 * edge_when_detected
    """
    initial_tier = classify_edge_tier(edge_when_detected)
    if EDGE_TIER_RANK.get(initial_tier, 0) < EDGE_TIER_RANK[EDGE_TIER_LEAN]:
        return False

    if minutes_until_kickoff > 15.0:
        return False

    # Must have strictly decayed below 95% of detected edge
    if current_edge >= 0.95 * edge_when_detected:
        return False

    return True


def sort_alpha_feed(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sorts alpha feed items by:
      1. edge_tier DESC (ALPHA > LEAN > BASE > SUB)
      2. urgency_score DESC (1.0 down to 0.0)
      3. edge_pct DESC
    """
    def _sort_key(item: dict[str, Any]) -> tuple[int, float, float]:
        edge = float(item.get("edge_pct") or item.get("edge") or 0.0)
        tier = item.get("edge_tier") or classify_edge_tier(edge)
        tier_rank = EDGE_TIER_RANK.get(tier, 0)
        urgency = float(item.get("urgency_score", 0.0))
        return (tier_rank, urgency, edge)

    return sorted(items, key=_sort_key, reverse=True)
