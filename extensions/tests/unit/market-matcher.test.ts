/**
 * Unit tests — market matching (spec §5, §15 critical tests).
 * Player matching, drive identifier matching, cross-event name collisions.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MarketMatcher,
  signalKeyFor,
  normalizeObservedMarket,
  type ObservedMarket,
  type RosterEntry,
  type CoverageEntry,
} from "@propstein/core";

const EVENT_A = "2026_09_NE_KC";
const EVENT_B = "2026_09_BUF_MIA";

const roster: RosterEntry[] = [
  { playerId: "nfl_travis_kelce", playerName: "Travis Kelce", team: "KC", eventId: EVENT_A, league: "NFL" },
  { playerId: "nfl_rashee_rice", playerName: "Rashee Rice", team: "KC", eventId: EVENT_A, league: "NFL" },
  { playerId: "nfl_hunter_henry", playerName: "Hunter Henry", team: "NE", eventId: EVENT_A, league: "NFL" },
  { playerId: "nfl_stefon_diggs", playerName: "Stefon Diggs", team: "BUF", eventId: EVENT_B, league: "NFL" },
  // Same display name, DIFFERENT events — the collision case.
  { playerId: "nfl_mike_williams_lac", playerName: "Mike Williams", team: "LAC", eventId: EVENT_A, league: "NFL" },
  { playerId: "nfl_mike_williams_nyj", playerName: "Mike Williams", team: "NYJ", eventId: EVENT_B, league: "NFL" },
];

function coverageFor(keys: Array<[string, string, string, string]>): CoverageEntry[] {
  return keys.map(([league, eventId, playerId, marketType]) => ({
    key: { league, eventId, playerId, marketType: marketType as never },
    available: true,
  }));
}

const baseCoverage = coverageFor([
  ["NFL", EVENT_A, "nfl_travis_kelce", "drive_reception_1plus"],
  ["NFL", EVENT_A, "nfl_rashee_rice", "drive_reception_1plus"],
  ["NFL", EVENT_A, "nfl_hunter_henry", "drive_reception_1plus"],
  ["NFL", EVENT_A, "nfl_mike_williams_lac", "drive_reception_1plus"],
  // NOTE: Stefon Diggs deliberately has NO drive coverage (NO_COVERAGE path).
]);

function observedMarket(overrides: Partial<ObservedMarket> = {}): ObservedMarket {
  return {
    source: "demobook",
    sport: "football",
    league: "NFL",
    eventId: EVENT_A,
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
    observedAt: "2026-10-30T18:44:00.000Z",
    adapterVersion: "demobook-selectors-v1",
    detectionConfidence: 0.98,
    provenance: "synthetic-fixture",
    ...overrides,
  };
}

function matcherWith(extraRoster: RosterEntry[] = [], extraCoverage: CoverageEntry[] = []) {
  return new MarketMatcher({ roster: [...roster, ...extraRoster], coverage: [...baseCoverage, ...extraCoverage] });
}

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

test("playerId + eventId + marketType with coverage → MATCHED", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket());
  const r = m.match(n);
  assert.equal(r.status, "MATCHED");
  assert.deepEqual(r.key, {
    league: "NFL",
    eventId: EVENT_A,
    playerId: "nfl_travis_kelce",
    marketType: "drive_reception_1plus",
  });
});

test("name-only fallback works inside a resolved event", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({ playerId: undefined, playerName: "Travis Kelce" }));
  const r = m.match(n);
  assert.equal(r.status, "MATCHED");
  assert.equal(r.key?.playerId, "nfl_travis_kelce");
});

test("alias roster entries resolve via canonical name key", () => {
  const m = matcherWith(
    [{ playerId: "nfl_ja_marr_chase", playerName: "Ja'Marr Chase", team: "CIN", eventId: EVENT_A, league: "NFL", aliases: ["Jamar Chase"] }],
    [{ key: { league: "NFL", eventId: EVENT_A, playerId: "nfl_ja_marr_chase", marketType: "drive_reception_1plus" as never }, available: true }],
  );
  const n = normalizeObservedMarket(observedMarket({ playerId: undefined, playerName: "Ja'Marr Chase Jr." }));
  assert.equal(m.match(n).status, "MATCHED");
});

// ---------------------------------------------------------------------------
// Fail-closed paths
// ---------------------------------------------------------------------------

test("CRITICAL: same player name in two simultaneous events, no event binding → UNVERIFIED (never guessed)", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({
    playerId: undefined,
    playerName: "Mike Williams",
    eventId: undefined, // no event binding visible on the page
  }));
  const r = m.match(n);
  assert.equal(r.status, "UNVERIFIED");
  assert.ok(r.reasons.some((x) => x.includes("multiple simultaneous events") || x.includes("name alone never identifies an event")));
});

test("same player name WITH an event binding resolves to the in-event player (event disambiguates)", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({
    playerId: undefined,
    playerName: "Mike Williams",
    eventId: EVENT_A, // event binding disambiguates the collision
  }));
  const r = m.match(n);
  assert.equal(r.status, "MATCHED");
  assert.equal(r.key?.playerId, "nfl_mike_williams_lac");
});

test("name-only match without any event binding → UNVERIFIED", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({ playerId: undefined, eventId: undefined }));
  const r = m.match(n);
  assert.equal(r.status, "UNVERIFIED");
  assert.ok(r.reasons.some((x) => x.includes("name alone never identifies an event")));
});

test("initials-form name → UNVERIFIED", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({ playerId: undefined, playerName: "T. Kelce" }));
  assert.equal(m.match(n).status, "UNVERIFIED");
});

test("player not on roster → UNVERIFIED with reasons (not silently dropped)", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({ playerId: undefined, playerName: "Unknown Player" }));
  const r = m.match(n);
  assert.equal(r.status, "UNVERIFIED");
});

test("player with roster entry but no model coverage → NO_COVERAGE", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({ playerId: "nfl_stefon_diggs", playerName: "Stefon Diggs", eventId: EVENT_B }));
  const r = m.match(n);
  // Diggs has roster presence in EVENT_B but no drive coverage there.
  assert.equal(r.status, "NO_COVERAGE");
  assert.ok(r.reasons[0]?.includes("no model coverage"));
});

test("next_play market on a covered drive player → NO_COVERAGE (different marketType key)", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({
    marketLabel: "Player to record a reception on the next play",
  }));
  const r = m.match(n);
  assert.equal(r.status, "NO_COVERAGE");
  assert.ok(r.key?.marketType === "next_play_reception_1plus");
});

test("unclassifiable label → UNVERIFIED even with full identity data", () => {
  const m = matcherWith();
  const n = normalizeObservedMarket(observedMarket({
    marketLabel: "Player to record a reception", // no scope → unknown
  }));
  assert.equal(m.match(n).status, "UNVERIFIED");
});

// ---------------------------------------------------------------------------
// Key construction
// ---------------------------------------------------------------------------

test("coverage keys distinguish market types and lines", () => {
  const m = matcherWith();
  const over = normalizeObservedMarket(observedMarket({
    marketLabel: "Total receptions this game", selection: "OVER", line: 5.5,
  }));
  // Kelce has no game_reception_over coverage → NO_COVERAGE proves key differs.
  assert.equal(m.match(over).status, "NO_COVERAGE");
});

test("signalKeyFor is stable and includes all identity dimensions", () => {
  const k1 = signalKeyFor("demobook", EVENT_A, "nfl_travis_kelce", "drive_reception_1plus", "YES");
  const k2 = signalKeyFor("demobook", EVENT_A, "nfl_travis_kelce", "next_play_reception_1plus", "YES");
  const k3 = signalKeyFor("demobook", EVENT_B, "nfl_travis_kelce", "drive_reception_1plus", "YES");
  assert.notEqual(k1, k2);
  assert.notEqual(k1, k3);
  assert.equal(k1, signalKeyFor("demobook", EVENT_A, "nfl_travis_kelce", "drive_reception_1plus", "YES"));
});
