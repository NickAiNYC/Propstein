/**
 * PropStein Live Sniper — Drive-Level Reception Model (DRIVE-REC-V1)
 * =================================================================
 *
 * PRICING TARGET (spec §6):
 *   P(player records >= 1 reception before the current offensive drive ends)
 *
 * SCOPE WARNING — READ FIRST:
 *   The existing PropStein full-game model (compound NegBin/Gamma over game
 *   receptions, src/model.py) is a FULL-GAME model and MUST NOT be used to
 *   price drive-level markets. This module is the dedicated possession-level
 *   baseline. It is a BASELINE, not a calibrated production model:
 *
 *   1. `independentPlayBaseline` — the spec's simplified approximation
 *        P = 1 - (1-q)^N
 *      explicitly NOT sufficient for production (no drive termination,
 *      no correlated play calls, no personnel changes, no state dependence).
 *
 *   2. `driveSurvivalAdjusted` — the DRIVE-REC-V1 default. Adds an absorbing
 *      drive-termination adjustment:
 *        P = q * (1 - (s(1-q))^N) / (1 - s(1-q))
 *      where s = probability the drive produces another play (conditioned on
 *      not having ended), N = capped projected remaining plays.
 *
 *   3. A seeded Monte Carlo possession simulator for research/calibration.
 *
 *   4. Calibration metrics (Brier, log loss, reliability buckets, ECE) with
 *      hard sample-count gating: below MIN_CALIBRATION_SAMPLES the harness
 *      reports "insufficient_evidence" and the UI must show
 *      NO MODEL COVERAGE for uncalibrated real-money evaluation.
 *
 * NO parameter defaults are fabricated for real players. Parameters arrive
 * from the server coverage registry or from explicitly labeled synthetic
 * fixtures. Nothing here invents confidence.
 */

import type { ModelEvaluation, ModelConfidence } from "./market-types.ts";

export const DRIVE_REC_MODEL_VERSION = "DRIVE-REC-V1";

/** Minimum drive-level samples before calibration metrics may be reported. */
export const MIN_CALIBRATION_SAMPLES = 200;

export interface DriveReceptionParams {
  /** q — probability this player records a reception on a single offensive
   *  play of the drive (route participation × target share × catch rate). */
  perPlayReceptionProb: number;
  /** N — projected remaining offensive plays in the drive (capped). */
  projectedRemainingPlays: number;
  /** s — probability the drive produces another play (1 - end-of-drive rate
   *  per play: punt/turnover/score/turnover-on-downs/field-goal attempt). */
  drivePlaySurvival: number;
  /** q uncertainty (±) used for the probability interval. */
  uncertaintyBand?: number;
}

/** Independent-play approximation — the spec's baseline. NOT production. */
export function independentPlayBaseline(q: number, n: number): number {
  // s = 1 by definition here (no drive termination); validate q and n only.
  if (!Number.isFinite(q) || q <= 0 || q >= 1) {
    throw new Error(`perPlayReceptionProb must be in (0,1), got ${String(q)}`);
  }
  if (!Number.isFinite(n) || n < 1 || n > 40) {
    throw new Error(`projectedRemainingPlays must be in [1,40], got ${String(n)}`);
  }
  return 1 - Math.pow(1 - q, Math.floor(n));
}

/**
 * DRIVE-REC-V1 closed form with absorbing drive termination:
 *   P = q * Σ_{k=1..N} [s(1-q)]^(k-1) = q * (1 - (s(1-q))^N) / (1 - s(1-q))
 * Reduces to the independent-play baseline when s = 1.
 */
export function driveSurvivalAdjusted(params: DriveReceptionParams): number {
  assertParams(params.perPlayReceptionProb, params.projectedRemainingPlays, params.drivePlaySurvival);
  const q = params.perPlayReceptionProb;
  const n = Math.floor(params.projectedRemainingPlays);
  const s = params.drivePlaySurvival;
  const r = s * (1 - q);
  if (r === 1) return Math.min(1, q * n); // degenerate boundary
  return (q * (1 - Math.pow(r, n))) / (1 - r);
}

/** Interval from q-sensitivity: evaluate at q ± band (clamped to (0,1)). */
export function driveReceptionInterval(params: DriveReceptionParams): [number, number] {
  const band = params.uncertaintyBand ?? 0;
  if (band <= 0) {
    const p = driveSurvivalAdjusted(params);
    return [p, p];
  }
  const lo = driveSurvivalAdjusted({ ...params, perPlayReceptionProb: Math.max(0.0001, params.perPlayReceptionProb - band) });
  const hi = driveSurvivalAdjusted({ ...params, perPlayReceptionProb: Math.min(0.9999, params.perPlayReceptionProb + band) });
  return [lo, hi];
}

function assertParams(q: number, n: number, s: number): void {
  if (!Number.isFinite(q) || q <= 0 || q >= 1) {
    throw new Error(`perPlayReceptionProb must be in (0,1), got ${String(q)}`);
  }
  if (!Number.isFinite(n) || n < 1 || n > 40) {
    throw new Error(`projectedRemainingPlays must be in [1,40], got ${String(n)}`);
  }
  // s = 1 is the degenerate no-drive-termination case (reduces to the
  // independent-play baseline); it is a valid input.
  if (!Number.isFinite(s) || s <= 0 || s > 1) {
    throw new Error(`drivePlaySurvival must be in (0,1], got ${String(s)}`);
  }
}

/**
 * Evaluate a drive-reception market. `calibration` (optional, real data only)
 * decides the honest confidence label.
 */
export function evaluateDriveReception(
  params: DriveReceptionParams,
  calibration?: { sampleCount: number },
): ModelEvaluation {
  const probability = driveSurvivalAdjusted(params);
  const interval = driveReceptionInterval(params);
  let confidence: ModelConfidence;
  if (calibration && calibration.sampleCount >= MIN_CALIBRATION_SAMPLES) {
    confidence = "calibrated";
  } else if (calibration && calibration.sampleCount > 0) {
    confidence = "insufficient_evidence";
  } else {
    confidence = "uncalibrated";
  }
  return {
    probability,
    modelVersion: DRIVE_REC_MODEL_VERSION,
    confidence,
    ...(interval[0] !== interval[1] ? { probabilityInterval: interval } : {}),
    ...(calibration ? { sampleCount: calibration.sampleCount } : {}),
  };
}

// ---------------------------------------------------------------------------
// Seeded Monte Carlo possession simulator (research / calibration harness)
// ---------------------------------------------------------------------------

/** Deterministic small-step PRNG (mulberry32) — reproducible research runs. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface DriveSimParams extends DriveReceptionParams {
  /** Plays are capped at N regardless of survival draws. */
  maxPlays?: number;
}

/**
 * Simulate one drive: plays occur while the drive survives (probability s per
 * play) up to N plays; reception occurs with probability q per play.
 * Returns whether the player recorded >= 1 reception.
 */
export function simulateOneDrive(params: DriveSimParams, rand: () => number): boolean {
  const n = Math.min(Math.floor(params.projectedRemainingPlays), params.maxPlays ?? 40);
  for (let play = 0; play < n; play += 1) {
    if (play > 0 && rand() >= params.drivePlaySurvival) return false; // drive ended
    if (rand() < params.perPlayReceptionProb) return true;
  }
  return false;
}

/** Monte Carlo estimate of P(>=1 reception) with a fixed seed. */
export function monteCarloDriveReception(params: DriveSimParams, runs: number, seed: number): number {
  const rand = mulberry32(seed);
  let hits = 0;
  for (let i = 0; i < runs; i += 1) {
    if (simulateOneDrive(params, rand)) hits += 1;
  }
  return hits / runs;
}

// ---------------------------------------------------------------------------
// Calibration metrics (drive-level) — honest, sample-gated
// ---------------------------------------------------------------------------

export interface CalibrationInput {
  /** Model probability at decision time. */
  predicted: number;
  /** Observed outcome (1 = reception recorded during drive). */
  observed: 0 | 1;
}

export interface CalibrationReport {
  sampleCount: number;
  status: "ok" | "insufficient_evidence";
  brierScore?: number;
  logLoss?: number;
  calibrationError?: number;
  reliabilityCurve?: Array<{ bucket: number; predicted: number; observed: number; n: number }>;
}

const RELIABILITY_BUCKETS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];

/**
 * Compute calibration metrics over chronological drive-level outcomes.
 * Below MIN_CALIBRATION_SAMPLES the report status is
 * "insufficient_evidence" and every metric is undefined — never fabricated.
 */
export function computeCalibration(samples: CalibrationInput[]): CalibrationReport {
  const n = samples.length;
  if (n < MIN_CALIBRATION_SAMPLES) {
    return { sampleCount: n, status: "insufficient_evidence" };
  }
  let brier = 0;
  let logLoss = 0;
  const buckets = new Map<number, { sumP: number; hits: number; count: number }>();
  for (const s of samples) {
    const p = Math.min(Math.max(s.predicted, 1e-6), 1 - 1e-6);
    brier += (p - s.observed) ** 2;
    logLoss += -(s.observed * Math.log(p) + (1 - s.observed) * Math.log(1 - p));
    const bucket = RELIABILITY_BUCKETS.find((edge) => p <= edge) ?? 1.0;
    const b = buckets.get(bucket) ?? { sumP: 0, hits: 0, count: 0 };
    b.sumP += p;
    b.hits += s.observed;
    b.count += 1;
    buckets.set(bucket, b);
  }
  const reliabilityCurve = [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([bucketEdge, b]) => ({
      bucket: bucketEdge,
      predicted: b.sumP / b.count,
      observed: b.hits / b.count,
      n: b.count,
    }));
  let ece = 0;
  for (const r of reliabilityCurve) {
    ece += (r.n / n) * Math.abs(r.predicted - r.observed);
  }
  return {
    sampleCount: n,
    status: "ok",
    brierScore: brier / n,
    logLoss: logLoss / n,
    calibrationError: ece,
    reliabilityCurve,
  };
}
