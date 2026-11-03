"""
boxscore_validator.py — Dual-Source Boxscore Cross-Validation Fetcher for Stage B

Cross-validates boxscore stats between Sleeper and ESPN/Gamebook.
Prevents premature VOIDs and enforces 0.0 stat tolerance and participation consensus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.crypto_utils import canonical_json_sha256
from src.settlement_engine import OfficialBoxscoreStat


@dataclass(frozen=True)
class NormalizedPlayerBoxscore:
    source: str
    game_final: bool
    active_gameday_roster: bool
    offensive_snaps: Optional[int]
    targets: int
    receptions: int
    receiving_yards: Optional[float]
    raw_excerpt_sha256: str


def parse_sleeper_player_stat(
    player_sleeper_id: str,
    game_status: str,
    sleeper_stats_obj: Dict[str, Any]
) -> NormalizedPlayerBoxscore:
    """Extracts receiving yards & offensive snaps from Sleeper stats payload."""
    p_stats = sleeper_stats_obj.get(player_sleeper_id, {})
    excerpt_hash = canonical_json_sha256({"sleeper_id": player_sleeper_id, "stats": p_stats})
    is_final = str(game_status).lower() in ("complete", "post", "final")
    gms_active = float(p_stats.get("gms_active", 0) or 0) == 1.0

    raw_snaps = p_stats.get("off_snp")
    offensive_snaps = int(raw_snaps) if raw_snaps is not None else None
    targets = int(p_stats.get("rec_tgt", 0) or 0)
    receptions = int(p_stats.get("rec", 0) or 0)

    if "rec_yd" in p_stats and p_stats["rec_yd"] is not None:
        rec_yards = float(p_stats["rec_yd"])
    elif gms_active and offensive_snaps is not None and offensive_snaps > 0 and receptions == 0:
        rec_yards = 0.0
    else:
        rec_yards = None

    return NormalizedPlayerBoxscore(
        source="sleeper_official",
        game_final=is_final,
        active_gameday_roster=gms_active,
        offensive_snaps=offensive_snaps,
        targets=targets,
        receptions=receptions,
        receiving_yards=rec_yards,
        raw_excerpt_sha256=excerpt_hash,
    )


def parse_espn_player_stat(
    player_espn_id: str,
    espn_competition_status: str,
    espn_boxscore_athletes: Dict[str, Dict[str, Any]]
) -> NormalizedPlayerBoxscore:
    """Extracts receiving stats & participation from ESPN summary boxscore payload."""
    athlete_entry = espn_boxscore_athletes.get(player_espn_id, {})
    excerpt_hash = canonical_json_sha256({"espn_id": player_espn_id, "entry": athlete_entry})
    is_final = str(espn_competition_status).upper() in ("STATUS_FINAL", "FINAL", "POST")
    did_not_play = athlete_entry.get("didNotPlay", False)
    active_roster = bool(athlete_entry) and not did_not_play

    raw_snaps = athlete_entry.get("offensiveSnaps")
    offensive_snaps = int(raw_snaps) if raw_snaps is not None else None
    targets = int(athlete_entry.get("receivingTargets", 0) or 0)
    receptions = int(athlete_entry.get("receptions", 0) or 0)

    if "receivingYards" in athlete_entry and athlete_entry["receivingYards"] is not None:
        rec_yards = float(athlete_entry["receivingYards"])
    elif active_roster and (targets > 0 or (offensive_snaps is not None and offensive_snaps > 0)):
        rec_yards = 0.0
    else:
        rec_yards = None

    return NormalizedPlayerBoxscore(
        source="espn_gamebook",
        game_final=is_final,
        active_gameday_roster=active_roster,
        offensive_snaps=offensive_snaps,
        targets=targets,
        receptions=receptions,
        receiving_yards=rec_yards,
        raw_excerpt_sha256=excerpt_hash,
    )


def cross_validate_boxscore(
    provider_game_id: str,
    primary: NormalizedPlayerBoxscore,
    secondary: NormalizedPlayerBoxscore,
) -> OfficialBoxscoreStat:
    """
    Fail-closed cross-validator between Primary (Sleeper) and Secondary (ESPN/Gamebook).
    Only marks stat_matches_across_sources=True when both feeds are FINAL and agree.
    """
    both_final = primary.game_final and secondary.game_final

    # 1. Exact receiving yards match (or both None)
    yards_match = (
        primary.receiving_yards is not None
        and secondary.receiving_yards is not None
        and abs(primary.receiving_yards - secondary.receiving_yards) < 1e-6
    )

    # 2. Verify active participation / Zero-Snap consensus
    primary_played = primary.active_gameday_roster and (
        (primary.offensive_snaps is not None and primary.offensive_snaps > 0)
        or primary.targets > 0
        or primary.receptions > 0
    )
    secondary_played = secondary.active_gameday_roster and (
        (secondary.offensive_snaps is not None and secondary.offensive_snaps > 0)
        or secondary.targets > 0
        or secondary.receptions > 0
    )

    primary_confirm_zero_snap = (
        not primary.active_gameday_roster
        or (primary.offensive_snaps is not None and primary.offensive_snaps == 0 and primary.targets == 0)
    )
    secondary_confirm_zero_snap = (
        not secondary.active_gameday_roster
        or (secondary.offensive_snaps is not None and secondary.offensive_snaps == 0 and secondary.targets == 0)
    )

    participation_consensus = (primary_played and secondary_played) or (
        primary_confirm_zero_snap and secondary_confirm_zero_snap
    )

    if primary_confirm_zero_snap and secondary_confirm_zero_snap:
        consensus_matches = both_final
        resolved_snaps = 0
        resolved_yards = 0.0
        resolved_active = primary.active_gameday_roster and secondary.active_gameday_roster
    else:
        consensus_matches = both_final and yards_match and participation_consensus
        resolved_snaps = (
            primary.offensive_snaps
            if (primary.offensive_snaps is not None and primary.offensive_snaps > 0)
            else (1 if primary_played else None)
        )
        resolved_yards = primary.receiving_yards if yards_match else None
        resolved_active = primary_played and secondary_played

    combined_proof_hash = canonical_json_sha256({
        "provider_game_id": provider_game_id,
        "primary_source": primary.source,
        "primary_hash": primary.raw_excerpt_sha256,
        "secondary_source": secondary.source,
        "secondary_hash": secondary.raw_excerpt_sha256,
        "consensus_matches": consensus_matches,
        "resolved_yards": resolved_yards,
        "resolved_snaps": resolved_snaps,
    })

    return OfficialBoxscoreStat(
        provider_game_id=provider_game_id,
        game_status="FINAL_OFFICIAL" if both_final else "PROVISIONAL_OR_IN_PROGRESS",
        active_gameday_roster=resolved_active,
        offensive_snaps=resolved_snaps,
        receiving_yards=resolved_yards,
        source_primary=primary.source,
        source_secondary=secondary.source,
        stat_matches_across_sources=consensus_matches,
        boxscore_payload_sha256=combined_proof_hash,
    )
