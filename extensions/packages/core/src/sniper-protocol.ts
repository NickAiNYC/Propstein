/**
 * PropStein Live Sniper — Execution Surface Protocol
 * ==================================================
 * Defines the 5-state sniper workflow, verification lock hierarchy,
 * audit receipt structures, and alert routing policies.
 *
 * Layer 4: Execution only. No model recalculation, no pricing projections.
 */

export type SniperWorkflowState =
  | "MATCH"
  | "VERIFY"
  | "OVERLAY"
  | "HANDOFF"
  | "STALE";

export type OverlayLockState =
  | "QUALIFIED"
  | "LOCKED"
  | "STALE";

export type LockReasonCode =
  | "UNVERIFIED"
  | "QUOTE_EXPIRED"
  | "INJURY_STALE"
  | "GATE_NOT_PASSED"
  | "BOOK_REPRICING_DELAY"
  | "KILL_SWITCH_ACTIVE"
  | "PANIC_DISENGAGED";

export interface BackendLiveSignal {
  signalId: string;
  playerId: string;
  playerName: string;
  marketType: string;
  selection: "OVER" | "UNDER";
  line: number;
  price: number;
  modelFairLine: number;
  pOver: number;
  gapPts: number;
  edgePct: number;
  verificationStatus: "VERIFIED" | "OBSERVED" | "UNAUDITED";
  gatePassed: boolean;
  capturedAt: string; // ISO 8601
  injuryContextAgeSec?: number;
  book?: string;
  repriceDelayMs?: number;
}

export interface ExtractedMarketNode {
  rawPlayer: string;
  rawMarket: string;
  line: number | null;
  price: number | null;
  selection?: "OVER" | "UNDER";
  book: string;
  element?: unknown;
}

export interface NormalizedEntityKey {
  lastName: string;
  marketScope: string;
  lineBucket: number;
  canonicalKey: string;
}

export interface PlacedAuditRecord {
  recordId: string;
  signalId: string;
  timestamp: string; // ISO 8601
  book: string;
  playerName: string;
  market: string;
  displayedLine: number;
  modelFairLine: number;
  pOver: number;
  achievedPrice: number;
  auditReceiptSha256: string;
}

export interface BookRepriceTelemetry {
  book: string;
  marketType: string;
  sampleCount: number;
  avgRepriceLagMs: number;
  isSlowest: boolean;
}

export type AlertRoutingAction =
  | "push_priority"
  | "side_panel_only"
  | "suppress_all";

export const KILL_SWITCH_ODDS_MAX_AGE_SEC = 20;
export const KILL_SWITCH_INJURY_MAX_AGE_SEC = 90;

/**
 * Evaluates whether a live signal is VERIFIED, fresh, and qualified.
 * Fail-closed: returns LOCKED with clear descriptive reason if any check fails.
 */
export function evaluateSignalVerification(
  signal: BackendLiveSignal,
  nowMs: number = Date.now(),
  panicKillActive: boolean = false
): {
  state: OverlayLockState;
  reasonCode?: LockReasonCode;
  reasonText: string;
  ageSec: number;
} {
  if (panicKillActive) {
    return {
      state: "LOCKED",
      reasonCode: "PANIC_DISENGAGED",
      reasonText: "Local kill-switch engaged (Ctrl+Shift+K)",
      ageSec: 0,
    };
  }

  const capturedMs = new Date(signal.capturedAt).getTime();
  const ageSec = Math.max(0, Math.floor((nowMs - capturedMs) / 1000));

  if (signal.verificationStatus !== "VERIFIED") {
    return {
      state: "LOCKED",
      reasonCode: "UNVERIFIED",
      reasonText: "Not sizing until verified",
      ageSec,
    };
  }

  if (ageSec > KILL_SWITCH_ODDS_MAX_AGE_SEC) {
    return {
      state: "LOCKED",
      reasonCode: "QUOTE_EXPIRED",
      reasonText: `Quote expired (${ageSec}s > ${KILL_SWITCH_ODDS_MAX_AGE_SEC}s kill switch)`,
      ageSec,
    };
  }

  if (
    signal.injuryContextAgeSec !== undefined &&
    signal.injuryContextAgeSec > KILL_SWITCH_INJURY_MAX_AGE_SEC
  ) {
    return {
      state: "LOCKED",
      reasonCode: "INJURY_STALE",
      reasonText: `Injury context stale (${signal.injuryContextAgeSec}s > ${KILL_SWITCH_INJURY_MAX_AGE_SEC}s)`,
      ageSec,
    };
  }

  if (!signal.gatePassed) {
    return {
      state: "LOCKED",
      reasonCode: "GATE_NOT_PASSED",
      reasonText: "Model gate closed",
      ageSec,
    };
  }

  return {
    state: "QUALIFIED",
    reasonText: `VERIFIED ${ageSec}s`,
    ageSec,
  };
}

/**
 * Determines alert routing action based on strict verification and kill-switch state.
 * Never pushes notification for unverified or stale quote.
 */
export function routeSignalAlert(
  signal: BackendLiveSignal,
  thresholdEdgePct: number = 4.0,
  staleKillSwitchActive: boolean = false
): AlertRoutingAction {
  if (staleKillSwitchActive) {
    return "suppress_all";
  }

  const isVerified = signal.verificationStatus === "VERIFIED";
  const passesGate = signal.gatePassed;
  const clearsEdge = signal.edgePct >= thresholdEdgePct;

  if (clearsEdge && isVerified && passesGate) {
    return "push_priority";
  }

  if (clearsEdge) {
    return "side_panel_only";
  }

  return "side_panel_only";
}
