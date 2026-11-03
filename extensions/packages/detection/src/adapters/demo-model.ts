/**
 * PropStein Live Sniper — Synthetic Demo Model Provider
 * ==================================================
 * Phase 1 demo coverage: SYNTHETIC DRIVE-REC-V1 parameters for the DemoBook
 * fixture ONLY, so the full pipeline (detection → matching → pricing → UI)
 * can be exercised end-to-end with zero sportsbook access. Every output is
 * labeled SYNTHETIC; nothing here is presented as calibrated model output,
 * and it is never used for real-book markets (provenance is checked).
 */

import {
  MarketMatcher,
  evaluateDriveReception,
  type DriveReceptionParams,
  type MatchResult,
  type ModelEvaluation,
  type NormalizedMarket,
  type RosterEntry,
} from "@propstein/core";

export interface DemoModelRow {
  roster: RosterEntry;
  params: DriveReceptionParams;
}

/**
 * Synthetic parameters (q, N, s) per demo player. Chosen so the demo renders
 * the documented mix — verified numerically against driveSurvivalAdjusted:
 *   Kelce   q=0.1841 → P=0.4399  → the spec's worked example: +160 break-even
 *                                    38.46%, P 44.0%, EV +14.4%; after the
 *                                    +115 move → break-even 46.51%, EV −5.4%
 *                                    (BELOW THRESHOLD — the critical reprice test)
 *   Rice    q=0.2276 → P=0.5081  → near-threshold (raw EV +4.2%, below the
 *                                    5% enter threshold after the haircut)
 *   Henry   q=0.105  → P=0.2865  → negative EV (−5.5% at +230)
 *   Johnson q=0.091  → P=0.2545  → negative EV (−0.7% at +290)
 * DEMO DATA — never calibrated.
 */
export const SYNTHETIC_DEMO_ROWS: DemoModelRow[] = [
  {
    roster: { playerId: "nfl_travis_kelce", playerName: "Travis Kelce", team: "KC", eventId: "2026_09_NE_KC", league: "NFL" },
    params: { perPlayReceptionProb: 0.1841, projectedRemainingPlays: 8, drivePlaySurvival: 0.72, uncertaintyBand: 0.04 },
  },
  {
    roster: { playerId: "nfl_rashee_rice", playerName: "Rashee Rice", team: "KC", eventId: "2026_09_NE_KC", league: "NFL" },
    params: { perPlayReceptionProb: 0.2276, projectedRemainingPlays: 8, drivePlaySurvival: 0.72, uncertaintyBand: 0.04 },
  },
  {
    roster: { playerId: "nfl_hunter_henry", playerName: "Hunter Henry", team: "NE", eventId: "2026_09_NE_KC", league: "NFL" },
    params: { perPlayReceptionProb: 0.105, projectedRemainingPlays: 8, drivePlaySurvival: 0.72, uncertaintyBand: 0.04 },
  },
  {
    roster: { playerId: "nfl_juwan_johnson", playerName: "Juwan Johnson", team: "NE", eventId: "2026_09_NE_KC", league: "NFL" },
    params: { perPlayReceptionProb: 0.091, projectedRemainingPlays: 8, drivePlaySurvival: 0.72, uncertaintyBand: 0.04 },
  },
];

export interface DemoModelProvider {
  readonly label: string;
  match(normalized: NormalizedMarket): MatchResult;
  evaluate(normalized: NormalizedMarket): ModelEvaluation | undefined;
}

export function createSyntheticDemoModelProvider(): DemoModelProvider {
  const matcher = new MarketMatcher({
    roster: SYNTHETIC_DEMO_ROWS.map((r) => r.roster),
    coverage: SYNTHETIC_DEMO_ROWS.map((r) => ({
      key: {
        league: r.roster.league,
        eventId: r.roster.eventId,
        playerId: r.roster.playerId,
        marketType: "drive_reception_1plus",
      },
      available: true,
    })),
  });
  return {
    label: "DRIVE-REC-V1 · SYNTHETIC DEMO PARAMETERS",
    match(normalized) {
      return matcher.match(normalized);
    },
    evaluate(normalized) {
      const match = matcher.match(normalized);
      if (match.status !== "MATCHED" || !match.key) return undefined;
      const row = SYNTHETIC_DEMO_ROWS.find((r) => r.roster.playerId === match.key!.playerId);
      if (!row) return undefined;
      return evaluateDriveReception(row.params);
    },
  };
}
