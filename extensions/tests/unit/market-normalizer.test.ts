/**
 * Unit tests — market normalization (spec §5).
 * The critical anti-false-match suite:
 *   "reception this drive" ≠ "reception next play" ≠ full-game reception.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifyMarketLabel,
  normalizeObservedMarket,
  playerNameKey,
  isInitialsForm,
  canonicalTeam,
  normalizeSelection,
  driveKey,
  type ObservedMarket,
} from "@propstein/core";

function baseMarket(overrides: Partial<ObservedMarket> = {}): ObservedMarket {
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
    observedAt: new Date("2026-10-30T18:44:00.000Z").toISOString(),
    adapterVersion: "demobook-selectors-v1",
    detectionConfidence: 0.98,
    provenance: "synthetic-fixture",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Scope disambiguation — the defining correctness property
// ---------------------------------------------------------------------------

test("drive-scoped reception label classifies as drive_reception_1plus", () => {
  for (const label of [
    "Player to record a reception this drive",
    "Player to Record a Reception — Current Drive",
    "Any reception during the drive",
  ]) {
    assert.equal(classifyMarketLabel(label).code, "drive_reception_1plus", label);
  }
});

test("next-play reception label classifies as next_play_reception_1plus", () => {
  assert.equal(classifyMarketLabel("Reception on the next play").code, "next_play_reception_1plus");
  assert.equal(classifyMarketLabel("Will he catch a pass this play?").code, "next_play_reception_1plus");
});

test("full-game reception label classifies as game_reception_over", () => {
  assert.equal(classifyMarketLabel("Total receptions this game").code, "game_reception_over");
});

test("CRITICAL: this drive and next play in one label → unknown (fail closed)", () => {
  const c = classifyMarketLabel("Reception this drive or on the next play");
  assert.equal(c.code, "unknown");
});

test("reception with NO scope marker → unknown (fail closed)", () => {
  // Live boards show "Player to record a reception" bare — ambiguous across
  // drive/next-play/game scopes. Never guess.
  assert.equal(classifyMarketLabel("Player to record a reception").code, "unknown");
});

test("receiving yards and anytime TD classify to their own codes", () => {
  assert.equal(classifyMarketLabel("Receiving yards").code, "game_receiving_yards_over");
  assert.equal(classifyMarketLabel("Anytime touchdown scorer").code, "game_anytime_td");
});

test("garbage labels classify as unknown with reasons", () => {
  const c = classifyMarketLabel("Special teams touchdowns");
  assert.equal(c.code, "unknown");
  assert.ok(c.reasons.length > 0);
});

// ---------------------------------------------------------------------------
// Player name canonicalization
// ---------------------------------------------------------------------------

test("playerNameKey strips suffixes, punctuation, accents, case", () => {
  assert.equal(playerNameKey("Ja'Marr Chase Jr."), "jamarr chase");
  assert.equal(playerNameKey("JAMARR CHASE"), "jamarr chase");
  assert.equal(playerNameKey("Amon-Ra St. Brown"), "amon ra st brown");
  assert.equal(playerNameKey("De'Von Achane"), "devon achane");
  assert.equal(playerNameKey("Amari Cooper Sr"), "amari cooper");
});

test("isInitialsForm detects ambiguous display names", () => {
  assert.equal(isInitialsForm("J. Allen"), true);
  assert.equal(isInitialsForm("J.Allen"), true);
  assert.equal(isInitialsForm("Josh Allen"), false);
});

// ---------------------------------------------------------------------------
// Team canonicalization
// ---------------------------------------------------------------------------

test("canonicalTeam maps full names, abbreviations, and informal forms", () => {
  assert.equal(canonicalTeam("Kansas City"), "KC");
  assert.equal(canonicalTeam("KC"), "KC");
  assert.equal(canonicalTeam("Chiefs"), "KC");
  assert.equal(canonicalTeam("Washington"), "WAS");
  assert.equal(canonicalTeam("WSH"), "WAS");
  assert.equal(canonicalTeam("49ers"), "SF");
  assert.equal(canonicalTeam("Tampa Bay"), "TB");
});

test("canonicalTeam returns undefined for unknown teams", () => {
  assert.equal(canonicalTeam("Birmingham"), undefined);
  assert.equal(canonicalTeam(undefined), undefined);
});

// ---------------------------------------------------------------------------
// Selection + drive keys
// ---------------------------------------------------------------------------

test("normalizeSelection canonicalizes display variants", () => {
  assert.equal(normalizeSelection("Yes"), "YES");
  assert.equal(normalizeSelection("YES"), "YES");
  assert.equal(normalizeSelection("Over"), "OVER");
  assert.equal(normalizeSelection("under"), "UNDER");
  assert.equal(normalizeSelection("Headside"), "OTHER");
});

test("driveKey binds event and drive with :: separator", () => {
  assert.equal(driveKey("2026_09_NE_KC", " d4 "), "2026_09_NE_KC::d4");
  assert.equal(driveKey(undefined, "d4"), undefined);
  assert.equal(driveKey("evt", ""), undefined);
});

// ---------------------------------------------------------------------------
// Full normalization
// ---------------------------------------------------------------------------

test("normalizeObservedMarket produces canonical form for a clean drive market", () => {
  const n = normalizeObservedMarket(baseMarket());
  assert.equal(n.marketTypeCode, "drive_reception_1plus");
  assert.equal(n.playerNameKey, "travis kelce");
  assert.equal(n.teamKey, "NE");
  assert.equal(n.selectionKey, "YES");
  assert.ok(n.decimalOdds !== undefined && Math.abs(n.decimalOdds - 2.6) < 1e-12);
  assert.equal(n.driveKey, "2026_09_NE_KC::d4");
  assert.deepEqual(n.ambiguityReasons, []);
});

test("drive-scoped market WITHOUT driveId flags ambiguity (cannot bind possession)", () => {
  const n = normalizeObservedMarket(baseMarket({ driveId: undefined }));
  assert.ok(n.ambiguityReasons.some((r) => r.includes("without a drive identifier")));
});

test("initials-form player name flags ambiguity", () => {
  const n = normalizeObservedMarket(baseMarket({ playerName: "T. Kelce", playerId: undefined }));
  assert.ok(n.ambiguityReasons.some((r) => r.includes("initials form")));
});

test("invalid American odds are rejected, not silently coerced", () => {
  const n = normalizeObservedMarket(baseMarket({ americanOdds: -42 }));
  assert.equal(n.americanOdds, undefined);
  assert.equal(n.decimalOdds, undefined);
  assert.ok(n.ambiguityReasons.some((r) => r.includes("invalid American odds")));
});

test("unknown teams flag ambiguity but do not crash", () => {
  const n = normalizeObservedMarket(baseMarket({ homeTeam: "Birmingham", awayTeam: "London" }));
  assert.ok(n.ambiguityReasons.some((r) => r.includes("unrecognized")));
});

test("no event binding with incomplete teams flags ambiguity", () => {
  const n = normalizeObservedMarket(baseMarket({ eventId: undefined, awayTeam: undefined }));
  assert.ok(n.ambiguityReasons.some((r) => r.includes("cannot bind to a single game")));
});

test("normalization never throws on hostile input", () => {
  const hostile = baseMarket({
    playerName: "",
    marketLabel: "",
    selection: "",
    homeTeam: "",
    americanOdds: Number.NaN,
  });
  const n = normalizeObservedMarket(hostile);
  assert.equal(n.playerNameKey, "");
  assert.ok(n.ambiguityReasons.length >= 3);
});
