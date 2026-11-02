// lib/types/slate.ts — Slate Overview typed contracts.
//
// Viewer-side projection of the frozen Python model layer (src/ is the sole
// truth source; this file types what the artifacts already carry and never
// recomputes pricing). Verification vocabulary mirrors verification.v1:
// VERIFIED / OBSERVED / STALE / CONFLICT. FAIL CLOSED: only VERIFIED is
// actionable; every other status locks the action field.

export type VerificationStatus = "VERIFIED" | "OBSERVED" | "STALE" | "CONFLICT";

export interface GateClause {
  clause_id: string;
  label: string;
  operator: ">=" | ">" | "<=" | "<" | "==" | "!=";
  actual: number;
  threshold: number;
  passed: boolean;
  severity: "hard" | "soft"; // drives card state
}

export interface QualifiedPlaySummary {
  play_id: string;
  player_name: string;
  side: "over" | "under";
  line: number;
  market: string;
  book_id: string;
  source_id: string;
  /** Percentage points. From evaluation.prob_edge * 100 in the feed artifact. */
  edge_pct: number | null;
  /** From a frozen Python pricing artifact only. Null when absent. */
  fair_prob: number | null;
  fair_line: number;
  /** Expected value per unit staked. From evaluation.expected_return. */
  ev_per_unit: number | null;
  /** From a frozen Python pricing artifact only. Null when absent. */
  kelly_fraction: number | null;
  verification_status: VerificationStatus;
  gate_reasoning: GateClause[];
  quote_age_seconds: number | null;
  fetched_at: string; // ISO
}

export interface FeedSourceHealth {
  source_id: string;
  book_id?: string | null;
  status: VerificationStatus;
  quote_count: number;
  last_success_at: string; // ISO
  /** Hash audit configured for this source (receipts/manifest present). */
  verification_configured: boolean;
  tier: "primary" | "secondary"; // drives panel hierarchy
}

export interface SlateOverview {
  slate_id: string;
  generated_at: string; // ISO — render time
  /** Freshest source timestamp — the data this page speaks for. */
  data_cutoff_timestamp: string;
  plays: QualifiedPlaySummary[];
  sources: FeedSourceHealth[];
  /** Any primary source CONFLICT — persistent banner territory. */
  conflict: boolean;
}

export type CardState = "QUALIFIED" | "WATCH" | "BLOCKED_DATA" | "BLOCKED_GATE";

export function deriveCardState(play: QualifiedPlaySummary): CardState {
  // Transient — data trust failure. Resolves when the feed recovers.
  if (play.verification_status === "STALE" || play.verification_status === "CONFLICT") {
    return "BLOCKED_DATA";
  }
  if (play.verification_status === "OBSERVED") return "BLOCKED_DATA";

  // A VERIFIED quote without a frozen, explicit gate decision is still locked.
  if (play.gate_reasoning.length === 0) return "BLOCKED_GATE";

  // Structural — the model said no.
  if (play.gate_reasoning.some((c) => c.severity === "hard" && !c.passed)) {
    return "BLOCKED_GATE";
  }
  if (play.gate_reasoning.some((c) => c.severity === "soft" && !c.passed)) {
    return "WATCH";
  }
  return "QUALIFIED";
}

export function firstFailingHardClause(play: QualifiedPlaySummary): GateClause | null {
  return play.gate_reasoning.find((c) => c.severity === "hard" && !c.passed) ?? null;
}
