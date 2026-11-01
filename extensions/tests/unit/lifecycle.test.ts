/**
 * Unit tests — signal lifecycle: dedup, drive-end invalidation,
 * odds-change re-evaluation (+160 → +115 critical test), oscillation guard.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SignalRegistry,
  reevaluateAll,
  normalizeObservedMarket,
  type ObservedMarket,
  type ModelEvaluation,
  type LifecycleEvent,
} from "@propstein/core";

const T0 = Date.parse("2026-10-30T18:44:00.000Z");

let clock = T0;
const tick = (ms: number) => { clock += ms; };

function observed(overrides: Partial<ObservedMarket> = {}): ObservedMarket {
  return {
    source: "demobook",
    sport: "football",
    league: "NFL",
    eventId: "2026_09_NE_KC",
    homeTeam: "Kansas City",
    awayTeam: "New England",
    playerId: "nfl_travis_kelce",
    playerName: "Travis Kelce",
    marketType: "Player to Record a Reception",
    marketLabel: "Player to record a reception this drive",
    selection: "YES",
    americanOdds: 160,
    driveId: "d4",
    marketStatus: "OPEN",
    observedAt: new Date(clock).toISOString(),
    sourceTimestamp: new Date(clock).toISOString(), // synthetic source receipt for lifecycle tests
    adapterVersion: "demobook-selectors-v1",
    detectionConfidence: 0.98,
    provenance: "synthetic-fixture",
    ...overrides,
  };
}

const MODEL: ModelEvaluation = { probability: 0.44, modelVersion: "DRIVE-REC-V1", confidence: "uncalibrated" };
const MATCH = { status: "MATCHED" as const, key: { league: "NFL", eventId: "2026_09_NE_KC", playerId: "nfl_travis_kelce", marketType: "drive_reception_1plus" as const }, reasons: [] };
const DRIVE = {
  driveId: "d4", eventId: "2026_09_NE_KC", isActive: true,
  provenance: "synthetic-fixture" as const,
  sourceTimestamp: new Date(T0).toISOString(), maxDataAgeMs: 120_000,
};

function makeRegistry() {
  clock = T0;
  return new SignalRegistry({ now: () => clock, alertCooldownMs: 30_000, maxSignalIdleMs: 120_000 });
}

const KEY = "demobook|2026_09_NE_KC|nfl_travis_kelce|drive_reception_1plus|YES|";

// ---------------------------------------------------------------------------
// Odds-change re-evaluation — CRITICAL TEST (spec §15)
// ---------------------------------------------------------------------------

test("CRITICAL: odds change +160 → +115 forces immediate re-evaluation on the NEW price", () => {
  const reg = makeRegistry();
  const s1 = reg.observe(KEY, observed({ americanOdds: 160 }), { model: MODEL, match: MATCH, driveContext: DRIVE });
  assert.equal(s1.state, "ALERTABLE");
  assert.ok(Math.abs((s1.evaluation?.evPerUnit ?? 0) - 0.144) < 1e-6);

  tick(400); // 400ms later the book moves +160 → +115
  const s2 = reg.observe(KEY, observed({ americanOdds: 115 }), { model: MODEL, match: MATCH, driveContext: DRIVE });
  // +115 → decimal 2.15, break-even 46.51%, raw EV = .44*1.15-.56 = -0.054
  assert.ok(Math.abs((s2.evaluation?.impliedProbability ?? 0) - 1 / 2.15) < 1e-9, "break-even recomputed on +115");
  assert.ok((s2.evaluation?.evPerUnit ?? 0) < 0, "EV recomputed negative on +115");
  assert.equal(s2.state, "BELOW_THRESHOLD");
  // The registry holds the latest snapshot only.
  assert.equal(reg.get(KEY)?.evaluation?.decimalOdds, 2.15);
});

// ---------------------------------------------------------------------------
// Drive-end invalidation — CRITICAL TEST (spec §15)
// ---------------------------------------------------------------------------

test("CRITICAL: when the drive ends, EVERY signal on that drive becomes invalid even if the price stays visible", () => {
  const reg = makeRegistry();
  reg.observe(KEY, observed({ playerName: "Travis Kelce" }), { model: MODEL, match: MATCH, driveContext: DRIVE });
  reg.observe("demobook|2026_09_NE_KC|nfl_rashee_rice|drive_reception_1plus|YES|", observed({ playerName: "Rashee Rice", playerId: "nfl_rashee_rice" }), { model: { ...MODEL, probability: 0.5 }, match: { ...MATCH, key: { ...MATCH.key, playerId: "nfl_rashee_rice" } }, driveContext: DRIVE });
  // A signal on ANOTHER drive must survive.
  reg.observe("demobook|2026_09_NE_KC|nfl_hunter_henry|drive_reception_1plus|YES|", observed({ playerName: "Hunter Henry", playerId: "nfl_hunter_henry", driveId: "d3" }), { model: { ...MODEL, probability: 0.5 }, match: { ...MATCH, key: { ...MATCH.key, playerId: "nfl_hunter_henry" } }, driveContext: { ...DRIVE, driveId: "d3" } });

  const invalidated = reg.driveEnded("d4");
  assert.equal(invalidated.length, 2);
  for (const s of invalidated) {
    assert.equal(s.withdrawn, true);
    assert.equal(s.withdrawalReason, "DRIVE_ENDED");
  }
  const survivor = reg.get("demobook|2026_09_NE_KC|nfl_hunter_henry|drive_reception_1plus|YES|");
  assert.equal(survivor?.withdrawn, false, "signal on a different drive survives");
});

// ---------------------------------------------------------------------------
// Alert deduplication + oscillation guard
// ---------------------------------------------------------------------------

test("alert-raised fires once on transition and respects the cooldown window", () => {
  const reg = makeRegistry();
  const events: LifecycleEvent[] = [];
  reg.onEvent((e) => { if (e.type === "alert-raised") events.push(e); });

  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  tick(1000);
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE }); // same state, no re-alert
  assert.equal(events.length, 1);

  // Oscillation: drop below threshold and recover within cooldown — the alert
  // is suppressed (dedup), preventing flapping around the threshold.
  tick(1000);
  reg.observe(KEY, observed({ americanOdds: -400 }), { model: MODEL, match: MATCH, driveContext: DRIVE }); // drops out
  tick(1000);
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE }); // recovers within 30s cooldown
  assert.equal(events.length, 1, "alert re-raise suppressed within cooldown");

  // After the cooldown window, a fresh transition alerts again.
  tick(31_000);
  reg.observe(KEY, observed({ americanOdds: -400 }), { model: MODEL, match: MATCH, driveContext: DRIVE });
  tick(1000);
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  assert.equal(events.length, 2);
});

test("alert-withdrawn fires when an active alert degrades", () => {
  const reg = makeRegistry();
  const withdrawals: LifecycleEvent[] = [];
  reg.onEvent((e) => { if (e.type === "alert-withdrawn") withdrawals.push(e); });
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  tick(500);
  reg.observe(KEY, observed({ marketStatus: "SUSPENDED" }), { model: MODEL, match: MATCH, driveContext: DRIVE });
  assert.equal(withdrawals.length, 1);
  assert.equal(withdrawals[0]!.snapshot.withdrawalReason, "SUSPENDED");
});

// ---------------------------------------------------------------------------
// Removal and pruning
// ---------------------------------------------------------------------------

test("remove() withdraws and deletes a signal whose market element disappeared", () => {
  const reg = makeRegistry();
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  reg.remove(KEY);
  assert.equal(reg.get(KEY), undefined);
});

test("pruneIdle drops signals not re-observed within maxSignalIdleMs", () => {
  const reg = makeRegistry();
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  tick(130_000);
  const pruned = reg.pruneIdle();
  assert.equal(pruned, 1);
  assert.equal(reg.get(KEY), undefined);
});

// ---------------------------------------------------------------------------
// Freshness ticker re-evaluation
// ---------------------------------------------------------------------------

test("reevaluateAll withdraws signals whose quotes expired with the clock", () => {
  const reg = makeRegistry();
  const lastObservedAt = new Date(clock).toISOString();
  reg.observe(KEY, observed(), { model: MODEL, match: MATCH, driveContext: DRIVE });
  tick(3_500); // beyond the 3s drive-market quote lifetime — no new observation arrives
  const refreshed = reevaluateAll(reg, { modelLookup: () => MODEL, matchLookup: () => MATCH, driveContext: DRIVE });
  assert.equal(refreshed.length, 1);
  assert.equal(refreshed[0]!.state, "STALE");
  assert.equal(refreshed[0]!.withdrawalReason, "QUOTE_EXPIRED");
  assert.equal(refreshed[0]!.observed.observedAt, lastObservedAt, "the stale withdrawal preserves the original observation");
});

test("normalization happens automatically when omitted", () => {
  const reg = makeRegistry();
  const s = reg.observe(KEY, observed());
  assert.equal(s.state, "NORMALIZED"); // no model/match yet
  assert.ok(s.normalized?.marketTypeCode === "drive_reception_1plus");
  assert.ok(normalizeObservedMarket(observed()).playerNameKey === "travis kelce");
});
