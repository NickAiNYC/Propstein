/* ============================================================
   PropStein — domain types
   Fail-closed data contracts. A quote never pretends to be
   live: every observation carries a capturedAt timestamp and
   an evidence status. Missing data is UNAVAILABLE, never zero.
   ============================================================ */

import type { DistLaw } from "./distributions";

/** The one status vocabulary of the platform. */
export type EvidenceStatus =
  | "MODEL_ONLY"
  | "OBSERVED_UNVERIFIED"
  | "VERIFIED"
  | "STALE"
  | "ARCHIVED"
  | "UNAVAILABLE";

export const EVIDENCE_STATUS_META: Record<
  EvidenceStatus,
  { label: string; short: string; color: string; description: string }
> = {
  MODEL_ONLY: {
    label: "Model only",
    short: "MODEL",
    color: "var(--status-model)",
    description: "No market quote captured for this market. Figures are model output only.",
  },
  OBSERVED_UNVERIFIED: {
    label: "Observed — unverified",
    short: "OBSERVED",
    color: "var(--status-observed)",
    description: "Quote captured from a single source and not yet independently verified.",
  },
  VERIFIED: {
    label: "Verified",
    short: "VERIFIED",
    color: "var(--status-verified)",
    description: "Quote independently verified against a second source at capture time.",
  },
  STALE: {
    label: "Stale capture",
    short: "STALE",
    color: "var(--status-stale)",
    description: "Captured quote is old relative to kickoff. Treat as archived context, not current.",
  },
  ARCHIVED: {
    label: "Archived",
    short: "ARCHIVED",
    color: "var(--status-archived)",
    description: "Event completed. Market data preserved as an archived snapshot.",
  },
  UNAVAILABLE: {
    label: "Unavailable",
    short: "UNAVAIL",
    color: "var(--status-unavailable)",
    description: "Market data is not currently available for this market.",
  },
};

export interface PairedMarketComparison {
  n_pairs: number;
  brier_model: number;
  brier_market: number;
  paired_diff: number;
  paired_diff_ci95: [number, number];
  median_abs_gap_pts: number;
  corr_model_market: number;
  n_events: number;
  is_copycat: boolean;
  paired_win_rate?: number;
}

/* ---------- sports ---------- */

export type Sport = "nfl" | "nba";

export const SPORTS: Sport[] = ["nfl", "nba"];

export const SPORT_META: Record<
  Sport,
  { label: string; periodLabel: string; venueLabel: string }
> = {
  nfl: { label: "NFL", periodLabel: "Week 9", venueLabel: "stadium" },
  nba: { label: "NBA", periodLabel: "Nov 6 slate", venueLabel: "arena" },
};

/* ---------- markets (sport-scoped) ---------- */

export type MarketKey =
  | "receptions"
  | "receiving_yards"
  | "points"
  | "rebounds"
  | "assists";

export const MARKET_META: Record<
  MarketKey,
  { label: string; short: string; unit: string; step: number; sport: Sport }
> = {
  receptions: { label: "Receptions", short: "REC", unit: "rec", step: 0.5, sport: "nfl" },
  receiving_yards: { label: "Receiving yards", short: "YDS", unit: "yds", step: 0.5, sport: "nfl" },
  points: { label: "Points", short: "PTS", unit: "pts", step: 0.5, sport: "nba" },
  rebounds: { label: "Rebounds", short: "REB", unit: "reb", step: 0.5, sport: "nba" },
  assists: { label: "Assists", short: "AST", unit: "ast", step: 0.5, sport: "nba" },
};

export const MARKET_KEYS_BY_SPORT: Record<Sport, MarketKey[]> = {
  nfl: ["receiving_yards", "receptions"],
  nba: ["points", "rebounds", "assists"],
};

export function marketSport(market: MarketKey): Sport {
  return MARKET_META[market].sport;
}

export interface Team {
  abbr: string;
  city: string;
  name: string;
  /** one restrained accent for the compact team mark */
  color: string;
}

export interface GameInfo {
  id: string;
  sport: Sport;
  week: number;
  /** ISO with offset — the authoritative scheduled kickoff */
  kickoff: string;
  away: string; // team abbr
  home: string;
  spread: number; // home-relative spread, e.g. -3.5 = home favored
  total?: number;
  venue: string;
  /** compact venue label for identity cards */
  venueShort: string;
  slot: "THU" | "SUN_EARLY" | "SUN_LATE" | "SUN_NIGHT" | "MON" | "FRI" | "SAT";
}

export type InjuryDesignation = "OK" | "QUESTIONABLE" | "OUT";

export type Position = "WR" | "TE" | "RB" | "PG" | "SG" | "SF" | "PF" | "C";

export interface Player {
  id: string; // slug
  sport: Sport;
  name: string;
  team: string; // abbr
  pos: Position;
  gameId: string;
  /** NFL: share of offensive snaps · NBA: share of available minutes (last 4 games, 0-1) */
  snapShare: number;
  /** NFL: share of team targets · NBA: usage rate (share of team possessions, 0-1) */
  targetShare: number;
  injury: InjuryDesignation;
  injuryNote?: string;
  /** one-line role description for identity context */
  role: string;
  /** alignment/usage mix summary (for assumptions panel) */
  depth?: string;
}

export interface Projection {
  playerId: string;
  market: MarketKey;
  law: DistLaw;
  modelVersion: string;
  /** data window used by the fit */
  dataWindow: string;
  /** when this projection was produced */
  producedAt: string;
  /** snapshot lineage key in the capture pipeline */
  snapshotKey: string;
}

export interface Quote {
  playerId: string;
  market: MarketKey;
  line: number;
  overOdds: number;
  underOdds: number;
  source: string;
  /** ISO with offset — never fabricated, always shown */
  capturedAt: string;
  status: Exclude<EvidenceStatus, "MODEL_ONLY" | "ARCHIVED" | "UNAVAILABLE">;
  verifiedAgainst?: string;
}

/** Settled historical market used by the public performance dashboard. */
export interface ArchivedMarket {
  id: string;
  week: number;
  season: number;
  playerId: string;
  playerName: string;
  market: MarketKey;
  modelVersion: string;
  fairLine: number;
  closeLine: number | null;
  sd: number;
  /** model P(over) at the closing line */
  predictedOverAtClose: number | null;
  overHit: boolean | null;
  evaluable: boolean;
  exclusionReason?: "NO_CLOSE" | "STALE_CLOSE" | "POSTPONED" | "VOID";
}

export interface CaptureEvent {
  id: string;
  at: string;
  kind: "capture" | "verification" | "grades" | "model" | "system";
  text: string;
}

/** Fixed snapshot instant — the preview is a snapshot, never "live". */
export const SNAPSHOT_AT = "2026-11-04T14:15:00-05:00";

export const MODEL_VERSION = "v3.2.1";
export const DATA_WINDOW = "2024–2026 regular season, excl. preseason";
export const GOVERNANCE = {
  screenedThreshold: 300,
  confirmatoryThreshold: 600,
  paidTiersActive: false,
};
