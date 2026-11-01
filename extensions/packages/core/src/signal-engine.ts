/**
 * PropStein Live Sniper — Signal Engine (State Machine)
 * ====================================================
 * Explicit states per spec §8:
 *
 *   DETECTED → NORMALIZED → MODEL_MATCHED → VALIDATED
 *                                        ├→ ALERTABLE
 *                                        ├→ BELOW_THRESHOLD
 *                                        ├→ UNVERIFIED
 *                                        ├→ STALE
 *                                        ├→ SUSPENDED
 *                                        └→ MODEL_UNAVAILABLE
 *
 * A signal is ALERTABLE only when ALL of:
 *   1. the market is visible (detection pipeline precondition),
 *   2. the player and event are correctly matched,
 *   3. the model supports the market,
 *   4. the market is not known to be suspended,
 *   5. observed odds clear the minimum EV threshold (after haircut),
 *   6. the observation is within its freshness threshold,
 *   7. the live possession identifier remains valid,
 *   8. required upstream data is sufficiently recent.
 *
 * Any failure withdraws the opportunity immediately. Hysteresis (enter vs.
 * exit thresholds) lives in lifecycle.ts; this module is pure evaluation.
 */

import type {
  DriveContext,
  EvEvaluation,
  MatchResult,
  ModelEvaluation,
  NormalizedMarket,
  ObservedMarket,
  SignalEngineConfig,
  SignalSnapshot,
  SignalState,
} from "./market-types.ts";
import { assessFreshness } from "./freshness.ts";
import {
  applyProbabilityHaircut,
  expectedValue,
  impliedProbability,
  probabilityEdge,
} from "./odds-math.ts";

export const DEFAULT_SIGNAL_ENGINE_CONFIG: SignalEngineConfig = {
  evEnterThreshold: 0.05,   // +5% EV per unit (post-haircut) to raise an alert
  evExitThreshold: 0.03,    // hysteresis floor to withdraw an active alert
  probabilityHaircut: 0.02, // 2% shrink of the p-vs-break-even edge for uncertainty
  minDetectionConfidence: 0.6,
  freshness: {},            // per-type defaults come from MARKET_FRESHNESS_DEFAULTS
  defaultFreshness: { maxQuoteAgeMs: 60_000, maxSourceAgeMs: 60_000 },
};

export interface SignalEvaluationInput {
  signalKey: string;
  observed: ObservedMarket;
  normalized?: NormalizedMarket;
  match?: MatchResult;
  model?: ModelEvaluation;
  /** Live drive context for drive-scoped markets. */
  driveContext?: DriveContext;
  /** Whether the market element is still visible in the viewport. */
  visible?: boolean;
  nowMs: number;
  config?: SignalEngineConfig;
  /** Previous state (for hysteresis-aware classification). */
  previousState?: SignalState;
}

function evaluateEv(
  normalized: NormalizedMarket,
  model: ModelEvaluation,
  config: SignalEngineConfig,
): EvEvaluation | undefined {
  const d = normalized.decimalOdds;
  if (d === undefined) return undefined;
  const breakEven = impliedProbability(d);
  const p = model.probability;
  const haircutP = applyProbabilityHaircut(p, breakEven, config.probabilityHaircut);
  return {
    decimalOdds: d,
    impliedProbability: breakEven,
    modelProbability: p,
    probabilityEdge: probabilityEdge(p, d),
    evPerUnit: expectedValue(p, d),
    alertableEvPerUnit: expectedValue(haircutP, d),
  };
}

/**
 * Evaluate one market observation into a full SignalSnapshot.
 * Pure function: no clocks, no IO — `nowMs` is injected.
 */
export function evaluateSignal(input: SignalEvaluationInput): SignalSnapshot {
  const config = input.config ?? DEFAULT_SIGNAL_ENGINE_CONFIG;
  const { observed, nowMs, signalKey } = input;
  const reasons: string[] = [];
  const evaluatedAt = new Date(nowMs).toISOString();

  // ---- Stage 1: DETECTED ------------------------------------------------
  // A brand-new observation with no normalization yet.
  if (!input.normalized) {
    return {
      signalKey,
      state: "DETECTED",
      withdrawn: false,
      observed,
      quoteAgeMs: quoteAgeOf(observed, nowMs),
      evaluatedAt,
      reasons: ["raw observation awaiting normalization"],
    };
  }
  const normalized = input.normalized;
  // Hoisted for the snapshot() helper — must be initialized before any
  // early-return path invokes it (JS temporal-dead-zone safety).
  const match = input.match;
  const model = input.model;

  // ---- Stage 2: NORMALIZED ----------------------------------------------
  // Freshness is computed early so every downstream state carries age data.
  const freshness = assessFreshness(observed, normalized.marketTypeCode, config, nowMs);

  // Visibility precondition (condition 1).
  if (input.visible === false) {
    reasons.push("market element no longer visible in the active viewport");
    return snapshot("STALE", true, "NOT_VISIBLE", freshness);
  }

  // Adapter confidence (adapter identity trust).
  if (observed.detectionConfidence < config.minDetectionConfidence) {
    reasons.push(
      `adapter detection confidence ${observed.detectionConfidence.toFixed(2)} below minimum ${config.minDetectionConfidence.toFixed(2)} — the adapter lost confidence in the market identity`,
    );
    return snapshot("UNVERIFIED", true, "LOW_DETECTION_CONFIDENCE", freshness);
  }

  // A closed or suspended market stays identified as such even if the book
  // no longer supplies a source timestamp with its withdrawn price.
  if (observed.marketStatus === "SUSPENDED" || observed.marketStatus === "CLOSED") {
    const withdrawalReason = observed.marketStatus;
    reasons.push(`market is ${withdrawalReason.toLowerCase()} at the sportsbook`);
    return snapshot("SUSPENDED", true, withdrawalReason, freshness);
  }
  // A DOM observation is not a source receipt. Missing, malformed, or future
  // source timestamps must never reach model matching or value evaluation.
  if (freshness.sourceDataStale && freshness.sourceAgeMs === undefined) {
    reasons.push(...freshness.reasons);
    return snapshot("STALE", true, "SOURCE_TIMESTAMP_UNVERIFIED", freshness);
  }
  if (observed.marketStatus !== "OPEN") {
    reasons.push("sportsbook market status is unverified — open price cannot be confirmed");
    return snapshot("UNVERIFIED", true, "MARKET_STATUS_UNVERIFIED", freshness);
  }

  // ---- Stage 3: MODEL_MATCHED -------------------------------------------
  if (!match) {
    return snapshot("NORMALIZED", false, undefined, freshness);
  }

  if (match.status === "UNVERIFIED") {
    reasons.push(...match.reasons, ...normalized.ambiguityReasons);
    reasons.push("unverified matches never produce value alerts");
    return snapshot("UNVERIFIED", false, undefined, freshness);
  }

  if (match.status === "NO_COVERAGE" || !model) {
    reasons.push(...(match?.reasons ?? []));
    reasons.push("model has no coverage for this market — displayed as NO MODEL COVERAGE");
    return snapshot("MODEL_UNAVAILABLE", false, undefined, freshness);
  }

  // ---- Stage 4: VALIDATED ----------------------------------------------
  // Condition 7: live possession identifier remains valid.
  const isDriveScoped = normalized.marketTypeCode === "drive_reception_1plus"
    || normalized.marketTypeCode === "next_play_reception_1plus";
  if (isDriveScoped) {
    if (!normalized.driveKey) {
      reasons.push("drive-scoped market without a valid drive binding");
      return snapshot("STALE", true, "DRIVE_UNBOUND", freshness);
    }
    if (!input.driveContext) {
      reasons.push("no live drive context available to validate the possession");
      return snapshot("STALE", true, "NO_DRIVE_CONTEXT", freshness);
    }
    const context = input.driveContext;
    if (context.provenance !== "independent-feed"
      && !(observed.source === "demobook" && context.provenance === "synthetic-fixture")) {
      reasons.push("drive context is not from an independent game-state feed");
      return snapshot("UNVERIFIED", true, "DRIVE_SOURCE_UNVERIFIED", freshness);
    }
    const driveSourceMs = Date.parse(context.sourceTimestamp ?? "");
    if (!Number.isFinite(driveSourceMs) || driveSourceMs > nowMs || context.maxDataAgeMs === undefined
      || context.maxDataAgeMs <= 0 || nowMs - driveSourceMs > context.maxDataAgeMs) {
      reasons.push("independent drive-state timestamp is missing, future-dated, or stale");
      return snapshot("STALE", true, "UPSTREAM_DATA_STALE", freshness);
    }
    if (context.eventId !== observed.eventId) {
      reasons.push("independent drive-state event does not match sportsbook event");
      return snapshot("UNVERIFIED", true, "DRIVE_EVENT_MISMATCH", freshness);
    }
    if (!input.driveContext.isActive) {
      reasons.push(`drive ${input.driveContext.driveId} has ended — signals tied to it are invalid even if their old price remains visible`);
      return snapshot("STALE", true, "DRIVE_ENDED", freshness);
    }
    if (input.driveContext.driveId !== observed.driveId) {
      reasons.push(`observed drive ${observed.driveId ?? "?"} does not match live drive ${input.driveContext.driveId}`);
      return snapshot("STALE", true, "DRIVE_MISMATCH", freshness);
    }
    // Condition 8: upstream data recency.
    if (input.driveContext.dataAgeMs !== undefined && input.driveContext.maxDataAgeMs !== undefined
      && input.driveContext.dataAgeMs > input.driveContext.maxDataAgeMs) {
      reasons.push(`possession data age ${Math.round(input.driveContext.dataAgeMs)}ms exceeds ${input.driveContext.maxDataAgeMs}ms`);
      return snapshot("STALE", true, "UPSTREAM_DATA_STALE", freshness);
    }
  }

  // Conditions 6: freshness.
  if (freshness.isStale || freshness.sourceDataStale) {
    reasons.push(...freshness.reasons);
    return snapshot("STALE", true, "QUOTE_EXPIRED", freshness);
  }

  if (observed.source !== "demobook" && model.confidence !== "calibrated") {
    reasons.push("live market model is not prospectively calibrated");
    return snapshot("MODEL_UNAVAILABLE", true, "MODEL_UNCALIBRATED", freshness);
  }

  const evaluation = evaluateEv(normalized, model, config);
  if (!evaluation) {
    reasons.push("no usable odds on this observation — cannot compute EV");
    return snapshot("UNVERIFIED", false, undefined, freshness);
  }

  // ---- Stage 5: ALERTABLE / BELOW_THRESHOLD ---------------------------
  const evForDecision = evaluation.alertableEvPerUnit;
  const wasAlerting = input.previousState === "ALERTABLE";
  // Hysteresis: active alerts persist until the exit threshold; new alerts
  // require the enter threshold.
  const threshold = wasAlerting ? config.evExitThreshold : config.evEnterThreshold;
  if (evForDecision >= threshold) {
    reasons.push(
      `post-haircut EV ${(evForDecision * 100).toFixed(1)}% clears the ${wasAlerting ? "exit" : "enter"} threshold ${(threshold * 100).toFixed(1)}%`,
    );
    return snapshot("ALERTABLE", false, undefined, freshness, evaluation);
  }
  reasons.push(
    `post-haircut EV ${(evForDecision * 100).toFixed(1)}% below the ${wasAlerting ? "exit" : "enter"} threshold ${(threshold * 100).toFixed(1)}%`,
  );
  return snapshot("BELOW_THRESHOLD", false, undefined, freshness, evaluation);

  // ---- helpers ----------------------------------------------------------
  function snapshot(
    state: SignalState,
    withdrawn: boolean,
    withdrawalReason: string | undefined,
    f: ReturnType<typeof assessFreshness>,
    evaluation?: EvEvaluation,
  ): SignalSnapshot {
    return {
      signalKey,
      state,
      withdrawn,
      ...(withdrawalReason ? { withdrawalReason } : {}),
      observed,
      normalized,
      match,
      model,
      ...(evaluation ? { evaluation } : {}),
      quoteAgeMs: f.quoteAgeMs,
      freshnessLimitMs: f.quoteLimitMs,
      evaluatedAt,
      reasons: [...reasons, ...(state === "ALERTABLE" ? [] : [])],
    };
  }
}

function quoteAgeOf(observed: ObservedMarket, nowMs: number): number {
  const t = Date.parse(observed.observedAt);
  return Number.isFinite(t) ? Math.max(0, nowMs - t) : Number.POSITIVE_INFINITY;
}

/** True when a signal state qualifies for positive-value alerting. */
export function isAlertableState(state: SignalState): boolean {
  return state === "ALERTABLE";
}

/** UI-facing status label for a snapshot. */
export function signalStatusLabel(s: SignalSnapshot): string {
  if (s.withdrawn && s.withdrawalReason === "DRIVE_ENDED") return "DRIVE ENDED";
  if (s.withdrawn && s.withdrawalReason === "SUSPENDED") return "SUSPENDED";
  if (s.withdrawn && s.withdrawalReason === "CLOSED") return "CLOSED";
  if (s.withdrawn && s.withdrawalReason === "QUOTE_EXPIRED") return "QUOTE EXPIRED";
  if (s.withdrawn && s.withdrawalReason === "SOURCE_TIMESTAMP_UNVERIFIED") return "STALE · SOURCE UNVERIFIED";
  if (s.withdrawn && s.withdrawalReason === "NOT_VISIBLE") return "NOT VISIBLE";
  switch (s.state) {
    case "ALERTABLE": return "ALERTABLE";
    case "BELOW_THRESHOLD": return "BELOW THRESHOLD";
    case "UNVERIFIED": return "UNVERIFIED";
    case "STALE": return "STALE";
    case "SUSPENDED": return "SUSPENDED";
    case "MODEL_UNAVAILABLE": return "NO MODEL COVERAGE";
    case "MODEL_MATCHED": return "MODEL MATCHED";
    case "NORMALIZED": return "NORMALIZED";
    case "DETECTED": return "DETECTED";
    default: return "UNKNOWN";
  }
}
