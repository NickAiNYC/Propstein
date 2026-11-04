/**
 * PropStein — Evidence-First Research Terminal
 * Shared domain types.
 *
 * Design invariants (see docs):
 *  - No picks, no stake advice, no urgency language anywhere in this codebase.
 *  - Every model output carries version, uncertainty, freshness, provenance, coverage.
 *  - Fail closed: missing provenance/freshness/entitlement/coverage => explicit
 *    unavailable state, never an invented answer.
 *  - Ledger records are append-only; corrections create revisions.
 */

// ---------------------------------------------------------------------------
// Odds & markets
// ---------------------------------------------------------------------------

export type Selection = 'over' | 'under';

export type MarketId = string;

export interface TwoWayQuote {
  /** American odds for the over (or the recorded side's primary book quote). */
  overAmericanOdds: number;
  /** American odds for the under at the same book/moment. */
  underAmericanOdds: number;
}

export interface ComparisonQuote {
  provider: string;
  book: string;
  /** Two-way quote at the comparison book for the same market+line. */
  overAmericanOdds: number;
  underAmericanOdds: number;
  capturedAtUtc: string; // ISO-8601
  licensed: boolean;     // server-side entitlement verified
  rawRef?: string;
}

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

export interface ProvenanceInput {
  /** e.g. "spread", "total", "weather", "injury_status", "player_form", "opponent_coverage", "market_quote" */
  key: string;
  label: string;
  sourceId: string;
  observedAtUtc: string | null; // null => never observed
  value?: string;
  rawCaptureRef?: string | null;
}

export interface ProvenanceRecord {
  inputs: ProvenanceInput[];
  /** Latest timestamp at which the entered price could still be considered "priced". */
  pricingCutoffUtc: string;
  snapshotHash: string;
}

/** Inputs that MUST carry an observed-at <= pricing cutoff (hard rule). */
export const REQUIRED_CONTEXT_INPUTS: Record<string, (sport: string) => boolean> = {
  spread: () => true,
  total: () => true,
  // weather only applies to outdoor sports
  weather: (sport) => ['NFL'].includes(sport),
};

// ---------------------------------------------------------------------------
// Model coverage
// ---------------------------------------------------------------------------

export type ModelCoverageStatus = 'calibrated' | 'uncalibrated' | 'none' | 'unavailable';

export interface ModelAssessment {
  coverage: ModelCoverageStatus;
  modelName: string | null;
  modelVersion: string | null;
  probability: number | null;          // fair P(selection) from the model
  uncertainty: { lower: number; upper: number } | null;
  calibrationStatus: 'calibrated' | 'uncalibrated' | 'none';
  limitations: string[];
  dataFreshnessUtc: string | null;
  corpusGames: number | null;
}

// ---------------------------------------------------------------------------
// Price assessment (the 9 allowed categorical outputs — nothing else)
// ---------------------------------------------------------------------------

export type PriceAssessment =
  | 'PRICE ABOVE MARKET HURDLE'
  | 'PRICE AT MARKET HURDLE'
  | 'PRICE BELOW MARKET HURDLE'
  | 'INSUFFICIENT MARKET DATA'
  | 'STALE QUOTE'
  | 'NO MODEL COVERAGE'
  | 'UNVERIFIED CONTEXT'
  | 'MODEL UNAVAILABLE'
  | 'SETTLED';

export const ALL_PRICE_ASSESSMENTS: PriceAssessment[] = [
  'PRICE ABOVE MARKET HURDLE',
  'PRICE AT MARKET HURDLE',
  'PRICE BELOW MARKET HURDLE',
  'INSUFFICIENT MARKET DATA',
  'STALE QUOTE',
  'NO MODEL COVERAGE',
  'UNVERIFIED CONTEXT',
  'MODEL UNAVAILABLE',
  'SETTLED',
];

/** Categoricals that must never appear on any surface. */
export const FORBIDDEN_CATEGORICALS = [
  'LEAN OVER', 'LEAN UNDER', 'PASS', 'AVOID', 'VALUE', 'EDGE',
  'RECOMMENDED', 'BEST BET', 'LOCK',
] as const;

export type AssessmentMode = 'market' | 'model';

export interface HurdleInput {
  sport: string;
  league: string;
  market: string;
  selection: Selection;
  line: number;
  enteredAmericanOdds: number;
  /** Comparison two-way quote, only where rights & data permit. */
  comparison: ComparisonQuote | null;
  /** Why no comparison? Used for explicit fail-closed reason codes. */
  comparisonUnavailableReason?: 'no_license' | 'no_data' | 'entitlement_failure' | null;
  provenance: ProvenanceRecord;
  model: ModelAssessment;
  mode: AssessmentMode;
  nowUtc: string;
  /** Set once a settlement exists — the card then shows SETTLED. */
  settled?: { status: string; result: string | null } | null;
}

export interface FreshnessState {
  ageSeconds: number | null;
  thresholdSeconds: number;
  state: 'fresh' | 'stale' | 'unknown';
}

export interface HurdleResult {
  assessment: PriceAssessment;
  /** Deterministic reason path for the categorical outcome. */
  reasonCode:
    | 'PROVENANCE_INCOMPLETE'
    | 'COMPARISON_STALE'
    | 'MODEL_SERVICE_UNAVAILABLE'
    | 'COMPARISON_UNAVAILABLE'
    | 'NO_CALIBRATED_MODEL'
    | 'MARKET_HURDLE_BAND'
    | 'SETTLED_OVERRIDE';
  detail: string;
  breakEvenProbability: number;
  comparisonImpliedProbability: number | null;
  /** enteredBreakEven - comparisonImplied, in percentage points. Negative = better than comparison. */
  priceDeltaPp: number | null;
  /** Descriptive only. Never an actionable-signal claim. */
  deltaVerdict: 'better' | 'worse' | 'at' | null;
  freshness: FreshnessState | null;
  marketComparisonAvailable: boolean;
  modelAssessmentAvailable: boolean;
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

export type LedgerSourceType = 'manual_entry' | 'screenshot_upload' | 'extension_observation';

export type SettlementStatus = 'pending' | 'settled' | 'void' | 'canceled' | 'push' | 'dnp';

export interface LedgerRevisionRecord {
  revisionNo: number;
  reasonCode: string;
  reasonText: string;
  actor: string;
  changedFields: string[];
  priorHash: string;
  newHash: string;
  createdAtUtc: string;
}

export interface ClosingReferenceRecord {
  provider: string | null;
  capturedAtUtc: string | null;
  americanOdds: number | null;
  counterpartAmericanOdds: number | null;
  impliedProbability: number | null;
  fairProbability: number | null;
  integrityHash: string | null;
  quality: 'fresh' | 'stale' | 'missing' | 'conflicting';
  secondSource: { provider: string; impliedProbability: number } | null;
  independenceVerified: boolean;
}

// ---------------------------------------------------------------------------
// Grading / record
// ---------------------------------------------------------------------------

/** Reason codes for exclusion or unevaluability. Never silently dropped. */
export type ExclusionReason =
  | 'PUSH'
  | 'VOID'
  | 'CANCELED'
  | 'DNP'
  | 'MISSING_CLOSE'
  | 'STALE_CLOSE'
  | 'CONFLICTING_CLOSE'
  | 'NOT_INDEPENDENT_CLOSE'
  | 'DUPLICATE'
  | 'CORRELATED'
  | 'UNSETTLED'
  | 'PRE_REGISTRATION';

export interface ClvOutcome {
  ledgerId: string;
  sport: string;
  gameClusterId: string;
  market: string;
  modelVersion: string | null;
  entrySource: LedgerSourceType;
  oddsBand: 'short' | 'near_even' | 'long';
  /** price CLV in percentage points; positive = entry price better than closing reference. */
  clvPp: number | null;
  evaluable: boolean;
  reasonCode: ExclusionReason | null;
  beatClose: boolean | null;
  modelProbability: number | null;
  modelCalibrated: boolean;
  result: 'win' | 'loss' | 'push' | 'void' | null;
}

export interface ReasonCodeCount {
  reason: ExclusionReason;
  count: number;
}

// ---------------------------------------------------------------------------
// Luck Meter verdicts
// ---------------------------------------------------------------------------

export type RecordVerdict =
  | 'NO RECORD'
  | 'INSUFFICIENT SAMPLE'
  | 'DESCRIPTIVE ONLY'
  | 'INCONCLUSIVE'
  | 'POSITIVE BUT UNPROVEN'
  | 'GATE PASSED';

export interface LuckMeterReport {
  verdict: RecordVerdict;
  verdictDisplayRule: string;
  evaluableCount: number;
  excludedCount: number;
  exclusions: ReasonCodeCount[];
  meanClvPp: number | null;
  shrunkClvPp: number | null;
  confidenceIntervalPp: { lower: number; upper: number } | null;
  bootstrapReplicates: number;
  bootstrapSeed: number;
  beatClosePct: number | null;
  calibration: {
    nWithModelProbability: number;
    brierScore: number | null;
    deciles: { bucket: string; n: number; predicted: number; observed: number }[];
  } | null;
  slices: RecordSlice[];
  minSampleThreshold: number;
  notes: string[];
}

export interface RecordSlice {
  dimension: string;
  value: string;
  n: number;
  meanClvPp: number | null;
  shrunkClvPp: number | null;
  beatClosePct: number | null;
  belowMinSample: boolean;
}

// ---------------------------------------------------------------------------
// Gate (preregistered, per-sport)
// ---------------------------------------------------------------------------

export type GateVerdict =
  | 'PENDING'
  | 'IN_PROGRESS'
  | 'INTERIM'
  | 'PASS'
  | 'FAIL'
  | 'INCONCLUSIVE'
  | 'RETIRED';

export interface GateSignal {
  signalId: string;
  sport: 'NFL' | 'NBA' | 'UFC' | string;
  gameClusterId: string;
  playerId: string;
  clvPp: number;
  evaluable: boolean;
  reasonCode: ExclusionReason | null;
  modelVersion: string | null;
  recordedAtUtc: string;
}

export interface GateAttemptResult {
  sport: string;
  attemptNo: number;
  nEvaluable: number;
  distinctClusters: number;
  meanClvPp: number;
  bootstrapLbPp: number;
  verdict: GateVerdict;
  seed: number;
  replicates: number;
  modelVersions: string[];
  evaluatedAtUtc: string;
  notes: string[];
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export type AlertType =
  | 'quote_changed'
  | 'quote_aged'
  | 'player_status'
  | 'market_suspended'
  | 'closing_available'
  | 'entry_settled'
  | 'entry_unevaluable';

export interface AlertPayload {
  alertId: string;
  ledgerEntryId: string | null;
  type: AlertType;
  message: string;
  snapshotTimeUtc: string;
  sourceProvider: string;
  createdAtUtc: string;
  delivered: boolean;
  batchKey: string | null;
}
