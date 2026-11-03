/**
 * PropStein Live Sniper — Canonical Market Types
 * ==============================================
 * The single source of truth for market data shapes shared by the Chrome
 * extension, the Safari companion, the web companion, and the FastAPI
 * intelligence endpoints.
 *
 * Design invariants (audited against repo contracts `src/contracts/odds.py`):
 *  - `observedAt` is when THIS CLIENT SAW the quote on screen.
 *    `sourceTimestamp` is when the sportsbook GENERATED it (when knowable).
 *    These are never conflated.
 *  - American odds follow the repo convention |odds| >= 100.
 *  - Anything ambiguous is UNVERIFIED, never silently matched.
 */

export type BookSource =
  | "draftkings"
  | "fanduel"
  | "polymarket"
  | "demobook";

export type MarketStatus =
  | "OPEN"
  | "SUSPENDED"
  | "CLOSED"
  | "UNKNOWN";

/** Canonical market type codes. Strictly disjoint — never conflated. */
export type MarketTypeCode =
  | "drive_reception_1plus"        // >=1 reception during CURRENT offensive drive
  | "next_play_reception_1plus"    // >=1 reception on the NEXT play only
  | "game_reception_over"          // full-game receptions over/under
  | "game_reception_under"
  | "game_receiving_yards_over"    // full-game receiving yards over/under
  | "game_receiving_yards_under"
  | "game_anytime_td"              // anytime touchdown scorer
  | "unknown";                     // unclassifiable → UNVERIFIED, no alerts

export type MatchStatus =
  | "MATCHED"
  | "UNVERIFIED"
  | "NO_COVERAGE";

export type DetectionProvenance =
  | "visible-page"    // parsed from elements visible in the active viewport
  | "manual-entry"    // typed in by the user (web companion)
  | "synthetic-fixture"; // deterministic test fixture (never in production UI)

/** Raw observation extracted by a site adapter (or entered manually). */
export interface ObservedMarket {
  source: BookSource;
  eventId?: string;
  sport: string;
  league: string;
  homeTeam?: string;
  awayTeam?: string;
  playerId?: string;
  playerName: string;
  marketType: string;          // raw label as displayed (pre-normalization)
  marketLabel: string;
  selection: string;
  line?: number;
  americanOdds?: number;
  decimalOdds?: number;
  driveId?: string;
  marketStatus: MarketStatus;
  /** ISO-8601 UTC — when this client observed the quote. */
  observedAt: string;
  /** ISO-8601 UTC — when the source generated the quote, when knowable. */
  sourceTimestamp?: string;
  adapterVersion: string;
  detectionConfidence: number; // 0..1 — adapter's own confidence
  provenance: DetectionProvenance;
}

/** Canonical, normalized market ready for matching against model coverage. */
export interface NormalizedMarket {
  observed: ObservedMarket;
  marketTypeCode: MarketTypeCode;
  playerNameKey: string;       // canonical name key (e.g. "jamarr chase")
  teamKey?: string;            // canonical team abbreviation
  selectionKey: "YES" | "NO" | "OVER" | "UNDER" | "OTHER";
  americanOdds?: number;
  decimalOdds?: number;
  driveKey?: string;           // `${eventId}::${driveId}` when present
  ambiguityReasons: string[];
  normalizationNotes: string[];
}

/** Identity of a modeled market inside the coverage registry. */
export interface ModelCoverageKey {
  league: string;
  eventId: string;
  playerId: string;
  marketType: MarketTypeCode;
  line?: number;
}

export interface MatchResult {
  status: MatchStatus;
  key?: ModelCoverageKey;
  reasons: string[];
}

/** Model evaluation for a covered market. */
export interface ModelEvaluation {
  probability: number;
  modelVersion: string;                      // e.g. "DRIVE-REC-V1"
  confidence: ModelConfidence;
  probabilityInterval?: [number, number];    // uncertainty band
  sampleCount?: number;                      // calibration sample count (real only)
}

export type ModelConfidence =
  | "calibrated"
  | "uncalibrated"
  | "insufficient_evidence";

export interface CalibrationRecord {
  modelVersion: string;
  sampleCount: number;
  brierScore?: number;
  logLoss?: number;
  calibrationError?: number;
  reliabilityCurve?: Array<{ bucket: number; predicted: number; observed: number; n: number }>;
  evaluatedAt?: string;
}

/** Full priced evaluation of a visible market against a book quote. */
export interface EvEvaluation {
  decimalOdds: number;
  impliedProbability: number;    // 1/d — break-even probability
  modelProbability: number;
  probabilityEdge: number;       // p - 1/d
  evPerUnit: number;             // p(d-1) - (1-p)
  /** EV computed after the configurable uncertainty haircut — alerting basis. */
  alertableEvPerUnit: number;
}

/** Signal states — explicit state machine per spec §8. */
export type SignalState =
  | "DETECTED"
  | "NORMALIZED"
  | "MODEL_MATCHED"
  | "VALIDATED"
  | "ALERTABLE"
  | "BELOW_THRESHOLD"
  | "UNVERIFIED"
  | "STALE"
  | "SUSPENDED"
  | "MODEL_UNAVAILABLE";

/** A fully evaluated signal as consumed by the UI. */
export interface SignalSnapshot {
  signalKey: string;
  state: SignalState;
  withdrawn: boolean;
  withdrawalReason?: string;
  observed: ObservedMarket;
  normalized?: NormalizedMarket;
  match?: MatchResult;
  model?: ModelEvaluation;
  evaluation?: EvEvaluation;
  quoteAgeMs: number;
  freshnessLimitMs?: number;
  evaluatedAt: string;
  reasons: string[];
}

/** Live possession context used for drive-validity gating. */
export interface DriveContext {
  driveId: string;
  eventId: string;
  /** Must come from a separate game-state feed, except on the demo fixture. */
  provenance?: "independent-feed" | "synthetic-fixture";
  /** Timestamp supplied by that feed, never the sportsbook DOM observation. */
  sourceTimestamp?: string;
  startedAt?: string;
  /** False once the drive is known to have ended. */
  isActive: boolean;
  /** Game-state recency (PBP feed etc.), when available. */
  dataAgeMs?: number;
  maxDataAgeMs?: number;
}

export interface FreshnessRules {
  /** Max age of the on-screen quote before it is considered stale. */
  maxQuoteAgeMs: number;
  /** Max age of upstream source data (when a sourceTimestamp is known). */
  maxSourceAgeMs?: number;
}

export interface SignalEngineConfig {
  /** Minimum EV per unit (post-haircut) to raise an alert. */
  evEnterThreshold: number;
  /** Hysteresis floor — an active alert is withdrawn below this. */
  evExitThreshold: number;
  /** Haircut applied to model probability for uncertainty/stale-price risk
   *  before the alert decision (display values stay raw). */
  probabilityHaircut: number;
  /** Minimum adapter detection confidence to consider a market verified. */
  minDetectionConfidence: number;
  /** Per-market-type freshness rules. */
  freshness: Partial<Record<MarketTypeCode, FreshnessRules>>;
  /** Default freshness when a market type has no specific rule. */
  defaultFreshness: FreshnessRules;
}

/** DOM change events emitted by the detection layer. */
export type MarketChangeKind =
  | "ADDED"
  | "ODDS_CHANGED"
  | "LABEL_CHANGED"
  | "STATUS_CHANGED"
  | "REMOVED"
  | "SUSPENDED"
  | "NAVIGATED";

export interface MarketChangeEvent {
  kind: MarketChangeKind;
  signalKey?: string;
  market?: ObservedMarket;
  detail?: string;
  at: string;
}

/** Notification definitions (configurable, deduplicated). */
export interface NotificationPrefs {
  onPositiveEv: boolean;
  onPriceImprovement: boolean;
  onQuoteInvalid: boolean;
  onSuspension: boolean;
  onDisconnect: boolean;
  soundEnabled: boolean;
}
