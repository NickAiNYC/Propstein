"""
Edge-Decay & Kickoff Urgency Scoring Tests
===========================================
Asserts:
1. urgency_score is strictly monotonic with time-to-kickoff.
2. urgency_score cliffs to 1.0 at kickoff -15min and stays 1.0 for <= 15min.
3. urgency_score is 0.0 for >= 90min.
4. "⚠️ DECAYING EDGE" badge triggers ONLY when:
   edge_tier >= LEAN AND minutes_until_kickoff <= 15 AND current_edge < 0.95 * edge_when_detected.
5. "⚠️ DECAYING EDGE" does NOT trigger when edge is stable near tip (e.g. at 10m to tip).
6. Alpha feed sorting orders by edge_tier DESC, then urgency_score DESC.
"""

import pytest
from src.agents.urgency import (
    compute_urgency_score,
    classify_edge_tier,
    should_show_decaying_badge,
    sort_alpha_feed,
    EDGE_TIER_ALPHA,
    EDGE_TIER_LEAN,
    EDGE_TIER_BASE,
    EDGE_TIER_SUB,
)


def test_urgency_score_cliff_and_bounds():
    """Urgency score must cliff at 15m to 1.0, and be 0.0 at >= 90m."""
    assert compute_urgency_score(15.0) == 1.0
    assert compute_urgency_score(10.0) == 1.0
    assert compute_urgency_score(0.0) == 1.0
    assert compute_urgency_score(-5.0) == 1.0  # Already started/live

    assert compute_urgency_score(90.0) == 0.0
    assert compute_urgency_score(120.0) == 0.0


def test_urgency_score_monotonic():
    """Urgency score must be monotonically non-increasing as time-to-kickoff increases."""
    times = [0, 5, 10, 15, 20, 30, 45, 60, 75, 90, 120]
    scores = [compute_urgency_score(t) for t in times]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], f"Failed monotonicity: {times[i]}m ({scores[i]}) vs {times[i+1]}m ({scores[i+1]})"


def test_edge_tier_classification():
    """Validate tier classifications: ALPHA >= 10%, LEAN 5-10%, BASE 3-5%, SUB < 3%."""
    assert classify_edge_tier(12.5) == EDGE_TIER_ALPHA
    assert classify_edge_tier(0.125) == EDGE_TIER_ALPHA
    assert classify_edge_tier(10.0) == EDGE_TIER_ALPHA

    assert classify_edge_tier(7.5) == EDGE_TIER_LEAN
    assert classify_edge_tier(0.075) == EDGE_TIER_LEAN
    assert classify_edge_tier(5.0) == EDGE_TIER_LEAN

    assert classify_edge_tier(4.0) == EDGE_TIER_BASE
    assert classify_edge_tier(0.035) == EDGE_TIER_BASE

    assert classify_edge_tier(2.0) == EDGE_TIER_SUB
    assert classify_edge_tier(0.015) == EDGE_TIER_SUB


def test_decaying_badge_triggers_only_when_edge_shrinks():
    """Badge must trigger when edge shrinks below 0.95 * detected edge near kickoff."""
    # LEAN tier (8.0%), detected at 8.0%, decayed to 7.0% (< 0.95 * 8.0 = 7.6%), 10m to tip -> Triggers!
    assert should_show_decaying_badge(
        edge_when_detected=8.0,
        current_edge=7.0,
        minutes_until_kickoff=10.0,
    ) is True

    # ALPHA tier (12.0%), decayed to 10.0% (< 0.95 * 12.0 = 11.4%), 12m to tip -> Triggers!
    assert should_show_decaying_badge(
        edge_when_detected=12.0,
        current_edge=10.0,
        minutes_until_kickoff=12.0,
    ) is True


def test_decaying_badge_does_not_trigger_when_edge_stable_near_tip():
    """CRITICAL INVARIANT: Edge decay badge does NOT trigger when edge is stable near tip."""
    # 5 minutes until tip, but edge is exactly stable (8.0% -> 8.0%) -> MUST NOT TRIGGER
    assert should_show_decaying_badge(
        edge_when_detected=8.0,
        current_edge=8.0,
        minutes_until_kickoff=5.0,
    ) is False

    # 10 minutes until tip, edge only had microscopic noise (8.0% -> 7.9%, > 95% threshold 7.6%) -> MUST NOT TRIGGER
    assert should_show_decaying_badge(
        edge_when_detected=8.0,
        current_edge=7.9,
        minutes_until_kickoff=10.0,
    ) is False

    # Edge decayed significantly, but game is 45 minutes away (> 15m window) -> MUST NOT TRIGGER
    assert should_show_decaying_badge(
        edge_when_detected=8.0,
        current_edge=5.0,
        minutes_until_kickoff=45.0,
    ) is False

    # Edge decayed near tip, but was only BASE tier (4.0%, < LEAN) -> MUST NOT TRIGGER
    assert should_show_decaying_badge(
        edge_when_detected=4.0,
        current_edge=2.0,
        minutes_until_kickoff=5.0,
    ) is False


def test_sort_alpha_feed():
    """Assert alpha feed sorts by edge_tier DESC (ALPHA > LEAN > BASE), then urgency_score DESC."""
    items = [
        {"player": "Player Base High Urgency", "edge_pct": 4.5, "edge_tier": "BASE", "urgency_score": 1.0},
        {"player": "Player Lean Low Urgency", "edge_pct": 7.0, "edge_tier": "LEAN", "urgency_score": 0.2},
        {"player": "Player Alpha High Urgency", "edge_pct": 12.0, "edge_tier": "ALPHA", "urgency_score": 0.9},
        {"player": "Player Lean High Urgency", "edge_pct": 8.0, "edge_tier": "LEAN", "urgency_score": 0.8},
        {"player": "Player Alpha Low Urgency", "edge_pct": 11.0, "edge_tier": "ALPHA", "urgency_score": 0.1},
    ]

    sorted_items = sort_alpha_feed(items)
    order = [i["player"] for i in sorted_items]

    # Expected:
    # 1. Player Alpha High Urgency (ALPHA, 0.9)
    # 2. Player Alpha Low Urgency (ALPHA, 0.1)
    # 3. Player Lean High Urgency (LEAN, 0.8)
    # 4. Player Lean Low Urgency (LEAN, 0.2)
    # 5. Player Base High Urgency (BASE, 1.0)
    assert order == [
        "Player Alpha High Urgency",
        "Player Alpha Low Urgency",
        "Player Lean High Urgency",
        "Player Lean Low Urgency",
        "Player Base High Urgency",
    ]
