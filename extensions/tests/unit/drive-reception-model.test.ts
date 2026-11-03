/**
 * Unit tests — DRIVE-REC-V1 baseline model.
 * Closed-form verification against brute-force summation, boundary behavior,
 * and honest confidence labeling.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  independentPlayBaseline,
  driveSurvivalAdjusted,
  driveReceptionInterval,
  evaluateDriveReception,
  monteCarloDriveReception,
  computeCalibration,
  DRIVE_REC_MODEL_VERSION,
  MIN_CALIBRATION_SAMPLES,
} from "@propstein/core";

// ---------------------------------------------------------------------------
// Independent-play baseline (spec formula)
// ---------------------------------------------------------------------------

test("independentPlayBaseline matches 1-(1-q)^N exactly", () => {
  assert.ok(Math.abs(independentPlayBaseline(0.2, 5) - (1 - Math.pow(0.8, 5))) < 1e-15);
  assert.ok(Math.abs(independentPlayBaseline(0.18, 7) - (1 - Math.pow(0.82, 7))) < 1e-15);
});

test("baseline extremes: q→1 gives 1; N=1 gives q", () => {
  assert.ok(Math.abs(independentPlayBaseline(0.999, 5) - 0.99999999) < 1e-8);
  assert.equal(independentPlayBaseline(0.25, 1), 0.25);
});

// ---------------------------------------------------------------------------
// Drive-survival adjusted closed form (DRIVE-REC-V1)
// ---------------------------------------------------------------------------

test("driveSurvivalAdjusted reduces to the independent-play baseline when s=1", () => {
  const q = 0.2, n = 8;
  assert.ok(Math.abs(driveSurvivalAdjusted({ perPlayReceptionProb: q, projectedRemainingPlays: n, drivePlaySurvival: 1 }) - independentPlayBaseline(q, n)) < 1e-12);
});

test("closed form equals brute-force summation Σ s^(k-1) q (1-q)^(k-1)", () => {
  const q = 0.22, n = 9, s = 0.72;
  let brute = 0;
  for (let k = 1; k <= n; k += 1) {
    brute += Math.pow(s, k - 1) * q * Math.pow(1 - q, k - 1);
  }
  const closed = driveSurvivalAdjusted({ perPlayReceptionProb: q, projectedRemainingPlays: n, drivePlaySurvival: s });
  assert.ok(Math.abs(brute - closed) < 1e-12, `brute=${brute} closed=${closed}`);
});

test("lower drive survival strictly lowers the probability", () => {
  const params = { perPlayReceptionProb: 0.25, projectedRemainingPlays: 8 };
  const pHigh = driveSurvivalAdjusted({ ...params, drivePlaySurvival: 0.95 });
  const pLow = driveSurvivalAdjusted({ ...params, drivePlaySurvival: 0.55 });
  assert.ok(pLow < pHigh);
  assert.ok(pLow > 0 && pHigh < 1);
});

test("probability is monotone increasing in N and in q", () => {
  const base = { perPlayReceptionProb: 0.2, drivePlaySurvival: 0.8 };
  assert.ok(driveSurvivalAdjusted({ ...base, projectedRemainingPlays: 3 }) < driveSurvivalAdjusted({ ...base, projectedRemainingPlays: 10 }));
  const base2 = { projectedRemainingPlays: 6, drivePlaySurvival: 0.8 };
  assert.ok(driveSurvivalAdjusted({ ...base2, perPlayReceptionProb: 0.1 }) < driveSurvivalAdjusted({ ...base2, perPlayReceptionProb: 0.3 }));
});

test("parameters are validated — no silent garbage in, garbage out", () => {
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: 0, projectedRemainingPlays: 5, drivePlaySurvival: 0.8 }));
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: 1, projectedRemainingPlays: 5, drivePlaySurvival: 0.8 }));
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: 0.2, projectedRemainingPlays: 0, drivePlaySurvival: 0.8 }));
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: 0.2, projectedRemainingPlays: 5, drivePlaySurvival: 0 }));   // s must be > 0
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: 0.2, projectedRemainingPlays: 5, drivePlaySurvival: 1.5 })); // s may equal 1 (degenerate) but not exceed it
  assert.throws(() => driveSurvivalAdjusted({ perPlayReceptionProb: Number.NaN, projectedRemainingPlays: 5, drivePlaySurvival: 0.8 }));
});

test("uncertainty band produces a bracketing interval", () => {
  const params = { perPlayReceptionProb: 0.25, projectedRemainingPlays: 7, drivePlaySurvival: 0.75, uncertaintyBand: 0.05 };
  const [lo, hi] = driveReceptionInterval(params);
  const mid = driveSurvivalAdjusted(params);
  assert.ok(lo < mid && mid < hi);
});

// ---------------------------------------------------------------------------
// Honest confidence labeling
// ---------------------------------------------------------------------------

test("evaluateDriveReception labels uncalibrated params honestly", () => {
  const e = evaluateDriveReception({ perPlayReceptionProb: 0.25, projectedRemainingPlays: 7, drivePlaySurvival: 0.75 });
  assert.equal(e.modelVersion, DRIVE_REC_MODEL_VERSION);
  assert.equal(e.confidence, "uncalibrated");
  assert.equal(e.sampleCount, undefined);
});

test("evaluateDriveReception reports insufficient_evidence below the sample gate", () => {
  const e = evaluateDriveReception(
    { perPlayReceptionProb: 0.25, projectedRemainingPlays: 7, drivePlaySurvival: 0.75 },
    { sampleCount: MIN_CALIBRATION_SAMPLES - 1 },
  );
  assert.equal(e.confidence, "insufficient_evidence");
});

test("evaluateDriveRecession labels calibrated only at/above the sample gate", () => {
  const e = evaluateDriveReception(
    { perPlayReceptionProb: 0.25, projectedRemainingPlays: 7, drivePlaySurvival: 0.75 },
    { sampleCount: MIN_CALIBRATION_SAMPLES },
  );
  assert.equal(e.confidence, "calibrated");
});

// ---------------------------------------------------------------------------
// Monte Carlo simulator (research harness)
// ---------------------------------------------------------------------------

test("monteCarlo converges to the closed form within tolerance", () => {
  const params = { perPlayReceptionProb: 0.25, projectedRemainingPlays: 8, drivePlaySurvival: 0.75 };
  const closed = driveSurvivalAdjusted(params);
  const mc = monteCarloDriveReception(params, 50_000, 42);
  assert.ok(Math.abs(mc - closed) < 0.01, `mc=${mc} closed=${closed}`);
});

test("monteCarlo is deterministic for a fixed seed", () => {
  const params = { perPlayReceptionProb: 0.3, projectedRemainingPlays: 6, drivePlaySurvival: 0.7 };
  assert.equal(monteCarloDriveReception(params, 2000, 7), monteCarloDriveReception(params, 2000, 7));
});

// ---------------------------------------------------------------------------
// Calibration metrics — sample gating
// ---------------------------------------------------------------------------

test("computeCalibration refuses to report metrics below MIN_CALIBRATION_SAMPLES", () => {
  const report = computeCalibration([{ predicted: 0.5, observed: 1 }]);
  assert.equal(report.status, "insufficient_evidence");
  assert.equal(report.brierScore, undefined);
  assert.equal(report.logLoss, undefined);
  assert.equal(report.calibrationError, undefined);
});

test("computeCalibration computes exact Brier/log-loss on a perfect predictor", () => {
  const samples = Array.from({ length: MIN_CALIBRATION_SAMPLES }, (_, i) => ({
    predicted: i % 2 === 0 ? 0.9 : 0.1,
    observed: (i % 2 === 0 ? 1 : 0) as 0 | 1,
  }));
  const r = computeCalibration(samples);
  assert.equal(r.status, "ok");
  // Perfect predictions: Brier = 0.01 avg ((1-0.9)^2), logloss = -ln(0.9) avg, ECE = 0.1
  assert.ok(Math.abs((r.brierScore ?? 1) - 0.01) < 1e-9);
  assert.ok(Math.abs((r.logLoss ?? 1) - (-Math.log(0.9))) < 1e-9);
  assert.ok(Math.abs((r.calibrationError ?? 1) - 0.1) < 1e-9);
  assert.equal(r.reliabilityCurve?.length, 2);
});

test("computeCalibration reliability buckets partition correctly", () => {
  const samples: Array<{ predicted: number; observed: 0 | 1 }> = [];
  for (let i = 0; i < MIN_CALIBRATION_SAMPLES / 2; i += 1) {
    samples.push({ predicted: 0.25, observed: 0 });      // bucket 0.3
    samples.push({ predicted: 0.65, observed: 1 });      // bucket 0.7
  }
  const r = computeCalibration(samples);
  const buckets = r.reliabilityCurve ?? [];
  assert.equal(buckets.length, 2);
  assert.ok(buckets[0]!.bucket === 0.3 && buckets[1]!.bucket === 0.7);
  assert.equal(buckets[0]!.n, MIN_CALIBRATION_SAMPLES / 2);
});
