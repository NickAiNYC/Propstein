/**
 * Unit tests — freshness engine and signal state machine (spec §8, §15).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  assessFreshness,
  quoteAgeMs,
  formatQuoteAge,
  evaluateSignal,
  signalStatusLabel,
  DEFAULT_SIGNAL_ENGINE_CONFIG,
  normalizeObservedMarket,
  type ObservedMarket,
  type DriveContext,
  type ModelEvaluation,
  type MatchResult,
  type NormalizedMarket,
} from "@propstein/core";

const NOW = Date.parse("2026-10-30T18:44:01.000Z");

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
    observedAt: "2026-10-30T18:44:00.000Z", // exactly 1000ms before NOW
    sourceTimestamp: "2026-10-30T18:44:00.000Z", // synthetic source receipt, distinct from observation
    adapterVersion: "demobook-selectors-v1",
    detectionConfidence: 0.98,
    provenance: "synthetic-fixture",
    ...overrides,
  };
}

const MATCHED: MatchResult = {
  status: "MATCHED",
  key: { league: "NFL", eventId: "2026_09_NE_KC", playerId: "nfl_travis_kelce", marketType: "drive_reception_1plus" },
  reasons: [],
};

const MODEL: ModelEvaluation = {
  probability: 0.44,
  modelVersion: "DRIVE-REC-V1",
  confidence: "uncalibrated",
};

const DRIVE: DriveContext = {
  driveId: "d4", eventId: "2026_09_NE_KC", isActive: true,
  provenance: "synthetic-fixture", sourceTimestamp: "2026-10-30T18:44:00.000Z", maxDataAgeMs: 15_000,
};

function norm(m: ObservedMarket): NormalizedMarket {
  return normalizeObservedMarket(m);
}

// ---------------------------------------------------------------------------
// Freshness
// ---------------------------------------------------------------------------

test("quoteAgeMs measures observation age exactly", () => {
  assert.equal(quoteAgeMs("2026-10-30T18:44:00.000Z", NOW), 1000);
});

test("quoteAgeMs is infinite for unparseable timestamps", () => {
  assert.equal(quoteAgeMs("not-a-date", NOW), Number.POSITIVE_INFINITY);
  assert.equal(quoteAgeMs(undefined, NOW), Number.POSITIVE_INFINITY);
  assert.equal(quoteAgeMs("2026-10-30T18:44:02.000Z", NOW), Number.POSITIVE_INFINITY);
});

test("sportsbook drive ID alone cannot validate a live possession", () => {
  const m = observed({ source: "fanduel", provenance: "visible-page" });
  const s = evaluateSignal({ signalKey: "real", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, confidence: "calibrated" },
    driveContext: { ...DRIVE, provenance: "synthetic-fixture" }, visible: true, nowMs: NOW });
  assert.equal(s.withdrawalReason, "DRIVE_SOURCE_UNVERIFIED");
});

test("independent feed must match event and carry a fresh source timestamp", () => {
  const m = observed({ source: "fanduel", provenance: "visible-page" });
  const base = { signalKey: "real", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, confidence: "calibrated" as const }, visible: true, nowMs: NOW };
  assert.equal(evaluateSignal({ ...base, driveContext: { ...DRIVE, provenance: "independent-feed", sourceTimestamp: undefined } }).withdrawalReason, "UPSTREAM_DATA_STALE");
  assert.equal(evaluateSignal({ ...base, driveContext: { ...DRIVE, provenance: "independent-feed", eventId: "other" } }).withdrawalReason, "DRIVE_EVENT_MISMATCH");
});

test("real-book uncalibrated model cannot produce an alert", () => {
  const m = observed({ source: "fanduel", provenance: "visible-page" });
  const s = evaluateSignal({ signalKey: "real", observed: m, normalized: norm(m), match: MATCHED,
    model: MODEL, driveContext: { ...DRIVE, provenance: "independent-feed" }, visible: true, nowMs: NOW });
  assert.equal(s.withdrawalReason, "MODEL_UNCALIBRATED");
  assert.equal(s.state, "MODEL_UNAVAILABLE");
});

test("drive markets expire at the tight 3s engineering default", () => {
  const m = observed(); // age 1000ms — fresh
  const fresh = assessFreshness(m, "drive_reception_1plus", DEFAULT_SIGNAL_ENGINE_CONFIG, NOW);
  assert.equal(fresh.isStale, false);
  assert.equal(fresh.quoteLimitMs, 3000);

  const staleM = observed({ observedAt: "2026-10-30T18:43:55.000Z" }); // age 6s
  const stale = assessFreshness(staleM, "drive_reception_1plus", DEFAULT_SIGNAL_ENGINE_CONFIG, NOW);
  assert.equal(stale.isStale, true);
});

test("game markets use the looser 20s live default", () => {
  const m = observed({ observedAt: "2026-10-30T18:43:45.000Z" }); // age 16s
  const a = assessFreshness(m, "game_reception_over", DEFAULT_SIGNAL_ENGINE_CONFIG, NOW);
  assert.equal(a.isStale, false);
  assert.equal(a.quoteLimitMs, 20000);
});

test("sourceTimestamp is evaluated separately from observedAt", () => {
  // Quote SEEN now, but the book generated it 30s ago: source stale, quote fresh.
  const m = observed({ observedAt: "2026-10-30T18:44:00.500Z", sourceTimestamp: "2026-10-30T18:43:30.000Z" });
  const a = assessFreshness(m, "drive_reception_1plus", DEFAULT_SIGNAL_ENGINE_CONFIG, NOW);
  assert.equal(a.isStale, false);
  assert.equal(a.sourceDataStale, true);
  assert.ok(a.reasons.some((r) => r.includes("source data age")));
});

test("missing, invalid, or future source timestamps fail closed", () => {
  for (const sourceTimestamp of [undefined, "not-a-date", "2026-10-30T18:45:00.000Z"]) {
    const m = observed({ sourceTimestamp });
    const freshness = assessFreshness(m, "drive_reception_1plus", DEFAULT_SIGNAL_ENGINE_CONFIG, NOW);
    assert.equal(freshness.sourceDataStale, true);
    const signal = evaluateSignal({
      signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
      driveContext: DRIVE, visible: true, nowMs: NOW,
    });
    assert.equal(signal.state, "STALE");
    assert.equal(signal.withdrawn, true);
    assert.equal(signal.withdrawalReason, "SOURCE_TIMESTAMP_UNVERIFIED");
    assert.ok(signal.reasons.some((reason) => reason.includes("source timestamp")));
  }
});

test("missing source timestamp is STALE even before model matching", () => {
  const m = observed({ sourceTimestamp: undefined });
  const signal = evaluateSignal({ signalKey: "k", observed: m, normalized: norm(m), nowMs: NOW });
  assert.equal(signal.state, "STALE");
  assert.equal(signal.withdrawalReason, "SOURCE_TIMESTAMP_UNVERIFIED");
});

test("formatQuoteAge renders human units", () => {
  assert.equal(formatQuoteAge(350), "350ms");
  assert.equal(formatQuoteAge(1250), "1.3s");
  assert.equal(formatQuoteAge(92000), "1m 32s");
  assert.equal(formatQuoteAge(Number.POSITIVE_INFINITY), "UNKNOWN");
});

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

test("raw observation without normalization → DETECTED", () => {
  const s = evaluateSignal({ signalKey: "k", observed: observed(), nowMs: NOW });
  assert.equal(s.state, "DETECTED");
});

test("normalized without a match result yet → NORMALIZED", () => {
  const s = evaluateSignal({ signalKey: "k", observed: observed(), normalized: norm(observed()), nowMs: NOW });
  assert.equal(s.state, "NORMALIZED");
});

test("full happy path: matched + covered + fresh + EV over threshold → ALERTABLE with spec numbers", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k",
    observed: m,
    normalized: norm(m),
    match: MATCHED,
    model: MODEL,
    driveContext: DRIVE,
    visible: true,
    nowMs: NOW,
  });
  assert.equal(s.state, "ALERTABLE");
  assert.equal(s.withdrawn, false);
  // Spec example: +160, p=44% → break-even 38.46%, EV +14.4%
  assert.ok(Math.abs((s.evaluation?.impliedProbability ?? 0) - 0.384615) < 1e-4);
  assert.ok(Math.abs((s.evaluation?.evPerUnit ?? 0) - 0.144) < 1e-6);
  assert.ok(Math.abs((s.evaluation?.alertableEvPerUnit ?? 0) - 0.144) < 0.02);
});

test("suspended market → SUSPENDED and withdrawn", () => {
  const m = observed({ marketStatus: "SUSPENDED" });
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "SUSPENDED");
  assert.equal(s.withdrawn, true);
  assert.equal(s.withdrawalReason, "SUSPENDED");
});

test("closed market → withdrawn", () => {
  const m = observed({ marketStatus: "CLOSED" });
  const s = evaluateSignal({ signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL, driveContext: DRIVE, visible: true, nowMs: NOW });
  assert.equal(s.state, "SUSPENDED");
  assert.equal(s.withdrawalReason, "CLOSED");
});

test("unknown market status cannot produce a value alert", () => {
  const m = observed({ marketStatus: "UNKNOWN" });
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "UNVERIFIED");
  assert.equal(s.withdrawalReason, "MARKET_STATUS_UNVERIFIED");
});

test("UNVERIFIED match → never alertable", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m),
    match: { status: "UNVERIFIED", reasons: ["name collision"] },
    model: MODEL, driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "UNVERIFIED");
  assert.equal(s.withdrawn, false);
});

test("NO_COVERAGE → MODEL_UNAVAILABLE (NO MODEL COVERAGE)", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m),
    match: { status: "NO_COVERAGE", reasons: ["no model coverage"] },
    model: undefined, driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "MODEL_UNAVAILABLE");
  assert.equal(signalStatusLabel(s), "NO MODEL COVERAGE");
});

test("stale quote → STALE / QUOTE EXPIRED", () => {
  const m = observed({ observedAt: "2026-10-30T18:43:50.000Z" }); // 11s old
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "STALE");
  assert.equal(s.withdrawalReason, "QUOTE_EXPIRED");
  assert.equal(signalStatusLabel(s), "QUOTE EXPIRED");
});

test("stale source data (book generated the quote long ago) → STALE", () => {
  const m = observed({ sourceTimestamp: "2026-10-30T18:43:30.000Z" }); // 31s old source
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "STALE");
});

test("CRITICAL: drive ended → signal invalid even though price remains visible", () => {
  const m = observed(); // price still on screen, still fresh
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: { ...DRIVE, isActive: false },
    visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "STALE");
  assert.equal(s.withdrawn, true);
  assert.equal(s.withdrawalReason, "DRIVE_ENDED");
  assert.equal(signalStatusLabel(s), "DRIVE ENDED");
});

test("drive mismatch between observation and live context → withdrawn", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: { ...DRIVE, driveId: "d5" },
    visible: true, nowMs: NOW,
  });
  assert.equal(s.withdrawalReason, "DRIVE_MISMATCH");
});

test("upstream possession data too old → withdrawn (condition 8)", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: { ...DRIVE, dataAgeMs: 30_000, maxDataAgeMs: 15_000 },
    visible: true, nowMs: NOW,
  });
  assert.equal(s.withdrawalReason, "UPSTREAM_DATA_STALE");
});

test("market no longer visible → withdrawn NOT_VISIBLE", () => {
  const m = observed();
  const s = evaluateSignal({ signalKey: "k", observed: m, normalized: norm(m), visible: false, nowMs: NOW });
  assert.equal(s.withdrawn, true);
  assert.equal(s.withdrawalReason, "NOT_VISIBLE");
});

test("low adapter confidence → UNVERIFIED (adapter lost identity — no alerts)", () => {
  const m = observed({ detectionConfidence: 0.3 });
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "UNVERIFIED");
  assert.ok(s.reasons.some((r) => r.includes("adapter detection confidence")));
});

test("negative EV → BELOW_THRESHOLD, not alertable", () => {
  const m = observed({ americanOdds: -250 }); // decimal 1.4, break-even 71.4%
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, probability: 0.6 },
    driveContext: DRIVE, visible: true, nowMs: NOW,
  });
  assert.equal(s.state, "BELOW_THRESHOLD");
  assert.ok((s.evaluation?.evPerUnit ?? 1) < 0);
});

test("haircut margin gates borderline EV: p clears raw EV but fails haircut EV", () => {
  // p=0.4154 at +160: raw EV = +8.0% (above the 5% enter threshold as displayed)
  // but with a 50% haircut on the probability edge the alert-basis EV is +4.0%
  // (below enter, above exit). The engine must withhold the alert while the
  // UI still shows the raw +8.0% figure.
  const config = { ...DEFAULT_SIGNAL_ENGINE_CONFIG, probabilityHaircut: 0.5 };
  const m = observed({ americanOdds: 160 });
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, probability: 0.4154 },
    driveContext: DRIVE, visible: true, nowMs: NOW, config,
  });
  assert.equal(s.state, "BELOW_THRESHOLD");
  assert.ok(Math.abs((s.evaluation?.evPerUnit ?? 0) - 0.08004) < 1e-6); // raw EV displayed above threshold
  assert.ok(Math.abs((s.evaluation?.alertableEvPerUnit ?? 1) - 0.04) < 1e-4); // alert basis below
});

test("hysteresis: an active ALERTABLE persists at EV between exit and enter thresholds", () => {
  const config = DEFAULT_SIGNAL_ENGINE_CONFIG; // enter 5%, exit 3%, haircut 2%
  const m = observed({ americanOdds: 160 });
  // p=0.39 at +160 → raw EV = 0.39*2.6-1 = +1.4% → below enter → BELOW_THRESHOLD.
  const p = 0.39;
  const sNew = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, probability: p }, driveContext: DRIVE, visible: true, nowMs: NOW,
    previousState: undefined, config,
  });
  assert.equal(sNew.state, "BELOW_THRESHOLD");

  // An ALERTING signal whose EV decayed to +4.0% (post-haircut) — above the
  // 3% exit threshold but below the 5% enter threshold — must stay alertable.
  // -160 → decimal 1.625, break-even 61.54%; p=0.6405.
  const m2 = observed({ americanOdds: -160 });
  const sActive = evaluateSignal({
    signalKey: "k", observed: m2, normalized: norm(m2), match: MATCHED,
    model: { ...MODEL, probability: 0.6405 }, driveContext: DRIVE, visible: true, nowMs: NOW,
    previousState: "ALERTABLE", config,
  });
  assert.equal(sActive.state, "ALERTABLE", "hysteresis should keep the alert alive above the exit threshold");
  assert.ok(Math.abs((sActive.evaluation?.alertableEvPerUnit ?? 1) - 0.04) < 1e-4);
});

test("hysteresis: active alert is withdrawn below the exit threshold", () => {
  const config = DEFAULT_SIGNAL_ENGINE_CONFIG;
  const m = observed({ americanOdds: -160 }); // break-even .6154
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED,
    model: { ...MODEL, probability: 0.60 }, // haircut EV ≈ .6069*.625-.3931=-.0137 → below exit
    driveContext: DRIVE, visible: true, nowMs: NOW,
    previousState: "ALERTABLE", config,
  });
  assert.equal(s.state, "BELOW_THRESHOLD");
});

test("drive-scoped market without drive context → withdrawn (no live possession validation)", () => {
  const m = observed();
  const s = evaluateSignal({
    signalKey: "k", observed: m, normalized: norm(m), match: MATCHED, model: MODEL,
    visible: true, nowMs: NOW,
  });
  assert.equal(s.withdrawalReason, "NO_DRIVE_CONTEXT");
});
