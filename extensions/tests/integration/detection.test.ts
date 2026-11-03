/**
 * Integration tests — DOM fixture detection (spec §15).
 * Uses linkedom to parse real HTML fixtures and drive the adapter +
 * differencing pipeline without a browser. Real-browser coverage runs in
 * tests/e2e (Playwright + Chromium).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "linkedom";
import {
  DemoBookAdapter,
  DraftKingsAdapter,
  FanDuelAdapter,
  PolymarketAdapter,
  AdapterRegistry,
  DEFAULT_FEATURE_FLAGS,
  safeDetect,
  computeChangeEvents,
  marketIdentityKey,
  decideVisibility,
  intersectionRatio,
  isStyleVisible,
} from "@propstein/detection";
import type { ObservedMarket } from "@propstein/core";

const FIXTURE_CLOCK = () => new Date("2026-10-30T18:44:00.000Z");

// ---------------------------------------------------------------------------
// Demo fixture HTML — mirrors demo/demo-sportsbook.html structure
// ---------------------------------------------------------------------------

const DEMO_HTML = `<!doctype html>
<html><body>
  <div id="app">
    <header><h1>DEMOBOOK — SYNTHETIC FEED (NOT A REAL SPORTSBOOK)</h1></header>
    <div data-propstein-demo="market-board" data-ps-event-id="2026_09_NE_KC"
         data-ps-home-team="Kansas City" data-ps-away-team="New England" data-ps-drive-id="d4">
      <div data-ps-market-card data-ps-player-id="nfl_travis_kelce" data-ps-player-name="Travis Kelce"
           data-ps-market-label="Player to record a reception this drive" data-ps-selection="YES"
           data-ps-american-odds="160" data-ps-market-status="OPEN">
        <span data-ps-odds-text>+160</span>
      </div>
      <div data-ps-market-card data-ps-player-id="nfl_rashee_rice" data-ps-player-name="Rashee Rice"
           data-ps-market-label="Player to record a reception this drive" data-ps-selection="YES"
           data-ps-american-odds="105" data-ps-market-status="OPEN">
        <span data-ps-odds-text>+105</span>
      </div>
      <div data-ps-market-card data-ps-player-id="nfl_hunter_henry" data-ps-player-name="Hunter Henry"
           data-ps-market-label="Player to record a reception on the next play" data-ps-selection="YES"
           data-ps-american-odds="220" data-ps-market-status="SUSPENDED">
        <span data-ps-odds-text>+220</span>
      </div>
    </div>
  </div>
</body></html>`;

function demoDocument(): Document {
  return parseHTML(DEMO_HTML).document;
}

// ---------------------------------------------------------------------------
// DemoBook adapter
// ---------------------------------------------------------------------------

test("DemoBook adapter parses all cards from the fixture with correct identity fields", async () => {
  const adapter = new DemoBookAdapter({ now: FIXTURE_CLOCK });
  const result = await adapter.detectVisibleMarkets(demoDocument());
  assert.equal(result.status, "OK");
  assert.equal(result.confidence, 0.98);
  assert.equal(result.markets.length, 3);
  const kelce = result.markets.find((m) => m.playerId === "nfl_travis_kelce")!;
  assert.equal(kelce.playerName, "Travis Kelce");
  assert.equal(kelce.americanOdds, 160);
  assert.equal(kelce.marketStatus, "OPEN");
  assert.equal(kelce.driveId, "d4");
  assert.equal(kelce.eventId, "2026_09_NE_KC");
  assert.equal(kelce.homeTeam, "Kansas City");
  assert.equal(kelce.awayTeam, "New England");
  assert.equal(kelce.provenance, "synthetic-fixture");
  assert.equal(kelce.observedAt, "2026-10-30T18:44:00.000Z");
});

test("DemoBook adapter distinguishes this-drive from next-play markets in the same fixture", async () => {
  const adapter = new DemoBookAdapter({ now: FIXTURE_CLOCK });
  const result = await adapter.detectVisibleMarkets(demoDocument());
  const drive = result.markets.find((m) => m.playerId === "nfl_travis_kelce")!;
  const nextPlay = result.markets.find((m) => m.playerId === "nfl_hunter_henry")!;
  assert.ok(drive.marketLabel.includes("this drive"));
  assert.ok(nextPlay.marketLabel.includes("next play"));
  assert.notEqual(drive.marketLabel, nextPlay.marketLabel);
});

test("DemoBook adapter reports suspension from the fixture", async () => {
  const adapter = new DemoBookAdapter({ now: FIXTURE_CLOCK });
  const result = await adapter.detectVisibleMarkets(demoDocument());
  const henry = result.markets.find((m) => m.playerId === "nfl_hunter_henry")!;
  assert.equal(henry.marketStatus, "SUSPENDED");
});

test("DemoBook adapter fails safe when the page marker is missing (layout changed)", async () => {
  const adapter = new DemoBookAdapter({ now: FIXTURE_CLOCK });
  const { document } = parseHTML("<html><body><div id='something-else'></div></body></html>");
  const result = await adapter.detectVisibleMarkets(document);
  assert.equal(result.status, "ADAPTER_DEGRADED");
  assert.equal(result.markets.length, 0);
  assert.equal(result.confidence, 0);
  assert.ok(result.notes.some((n) => n.includes("marker not found")));
});

test("DemoBook adapter isSupportedPage: localhost + demobook path only", () => {
  const adapter = new DemoBookAdapter();
  assert.equal(adapter.isSupportedPage(new URL("http://localhost:4173/demobook")), true);
  assert.equal(adapter.isSupportedPage(new URL("http://127.0.0.1:4173/demo-sportsbook.html")), true);
  assert.equal(adapter.isSupportedPage(new URL("http://localhost:4173/other")), false);
  assert.equal(adapter.isSupportedPage(new URL("https://sportsbook.draftkings.com/demobook")), false);
  assert.equal(adapter.isSupportedPage(new URL("https://evil.com/demobook")), false);
});

// ---------------------------------------------------------------------------
// Odds-change differencing (integration of the pure differ with fixtures)
// ---------------------------------------------------------------------------

function obs(overrides: Partial<ObservedMarket>): ObservedMarket {
  return {
    source: "demobook", sport: "football", league: "NFL",
    eventId: "2026_09_NE_KC", homeTeam: "Kansas City", awayTeam: "New England",
    playerId: "nfl_travis_kelce", playerName: "Travis Kelce",
    marketType: "Player to Record a Reception", marketLabel: "Player to record a reception this drive",
    selection: "YES", americanOdds: 160, driveId: "d4", marketStatus: "OPEN",
    observedAt: "2026-10-30T18:44:00.000Z", adapterVersion: "v1",
    detectionConfidence: 0.98, provenance: "synthetic-fixture",
    ...overrides,
  };
}

test("differ emits ODDS_CHANGED when the fixture's +160 becomes +115", () => {
  const prev = new Map([[marketIdentityKey(obs({})), obs({})]]);
  const curr = new Map([[marketIdentityKey(obs({})), obs({ americanOdds: 115 })]]);
  const events = computeChangeEvents(prev, curr, "2026-10-30T18:44:00.400Z");
  const oddsEvent = events.find((e) => e.kind === "ODDS_CHANGED" && e.detail === "160 → 115");
  assert.ok(oddsEvent, `expected ODDS_CHANGED 160 → 115, got ${JSON.stringify(events.map((e) => [e.kind, e.detail]))}`);
  assert.equal(oddsEvent!.market?.americanOdds, 115);
});

test("differ emits REMOVED for cards the page deleted and ADDED for new cards", () => {
  const prev = new Map([
    [marketIdentityKey(obs({})), obs({})],
    [marketIdentityKey(obs({ playerId: "nfl_rashee_rice", playerName: "Rashee Rice", americanOdds: 105 })), obs({ playerId: "nfl_rashee_rice", playerName: "Rashee Rice", americanOdds: 105 })],
  ]);
  const curr = new Map([
    [marketIdentityKey(obs({})), obs({})],
    [marketIdentityKey(obs({ playerId: "nfl_juwan_johnson", playerName: "Juwan Johnson", americanOdds: 180 })), obs({ playerId: "nfl_juwan_johnson", playerName: "Juwan Johnson", americanOdds: 180 })],
  ]);
  const events = computeChangeEvents(prev, curr, "t");
  assert.ok(events.some((e) => e.kind === "REMOVED" && e.signalKey?.includes("rashee_rice")));
  assert.ok(events.some((e) => e.kind === "ADDED" && e.signalKey?.includes("juwan_johnson")));
});

test("differ emits SUSPENDED when a mid-drive suspension flips the status", () => {
  const prev = new Map([[marketIdentityKey(obs({})), obs({})]]);
  const curr = new Map([[marketIdentityKey(obs({})), obs({ marketStatus: "SUSPENDED" })]]);
  const events = computeChangeEvents(prev, curr, "t");
  assert.ok(events.some((e) => e.kind === "SUSPENDED" && e.detail === "OPEN → SUSPENDED"));
});

test("differ emits LABEL_CHANGED for a same-scope cosmetic relabel", () => {
  const prev = new Map([[marketIdentityKey(obs({})), obs({})]]);
  const curr = new Map([[marketIdentityKey(obs({ marketLabel: "Player to Record a Reception (current drive)" })), obs({ marketLabel: "Player to Record a Reception (current drive)" })]]);
  const events = computeChangeEvents(prev, curr, "t");
  assert.ok(events.some((e) => e.kind === "LABEL_CHANGED"));
});

test("differ treats a scope change (this drive → next play) as a NEW market, not a relabel", () => {
  const prev = new Map([[marketIdentityKey(obs({})), obs({})]]);
  const next = obs({ marketLabel: "Player to record a reception on the next play" });
  const curr = new Map([[marketIdentityKey(next), next]]);
  const events = computeChangeEvents(prev, curr, "t");
  // Different scope code ⇒ different identity ⇒ REMOVED + ADDED. A drive
  // market NEVER silently morphs into a next-play market.
  assert.ok(events.some((e) => e.kind === "REMOVED"));
  assert.ok(events.some((e) => e.kind === "ADDED"));
  assert.equal(events.some((e) => e.kind === "LABEL_CHANGED"), false);
});

test("virtualized list: re-created card with identical identity does NOT emit ADDED", () => {
  // Virtualization destroys and recreates DOM nodes; identity comes from the
  // market content, so a re-created identical card is an update, not a new market.
  const key = marketIdentityKey(obs({}));
  const prev = new Map([[key, obs({})]]);
  const curr = new Map([[key, obs({})]]); // fresh parse of identical card
  const events = computeChangeEvents(prev, curr, "t");
  assert.equal(events.filter((e) => e.kind === "ADDED").length, 0);
  assert.ok(events.some((e) => e.kind === "ODDS_CHANGED" && e.detail === "re-observed"));
});

// ---------------------------------------------------------------------------
// Sportsbook adapter scaffolds — fail-safe behavior
// ---------------------------------------------------------------------------

test("DraftKings adapter degrades safely on a fixture it cannot parse", async () => {
  const adapter = new DraftKingsAdapter({ now: FIXTURE_CLOCK });
  const { document } = parseHTML("<html><body><div class='unknown-layout'></div></body></html>");
  const result = await adapter.detectVisibleMarkets(document);
  assert.equal(result.status, "ADAPTER_DEGRADED");
  assert.equal(result.markets.length, 0);
  assert.equal(result.confidence, 0);
});

test("FanDuel adapter degrades safely on an unsupported layout", async () => {
  const adapter = new FanDuelAdapter({ now: FIXTURE_CLOCK });
  const { document } = parseHTML("<html><body><div id='root'></div></body></html>");
  const result = await adapter.detectVisibleMarkets(document);
  assert.equal(result.status, "ADAPTER_DEGRADED");
  assert.equal(result.markets.length, 0);
});

test("Polymarket adapter parses cent prices into decimal odds", async () => {
  const adapter = new PolymarketAdapter({ now: FIXTURE_CLOCK });
  const html = `<html><body><main>
    <div data-testid='market-card'>
      <span class='title'>Travis Kelce</span>
      <p>Player to record a reception this drive</p>
      <button class='outcome'><span class='price'>62¢</span></button>
    </div>
  </main></body></html>`;
  const { document } = parseHTML(html);
  const result = await adapter.detectVisibleMarkets(document);
  assert.equal(result.status, "OK");
  assert.equal(result.markets.length, 1);
  assert.ok(Math.abs((result.markets[0]!.decimalOdds ?? 0) - 1 / 0.62) < 1e-9);
});

test("adapter registry: DK adapter disabled by default → MARKET UNSUPPORTED reasoning", () => {
  const registry = new AdapterRegistry();
  registry.register(new DraftKingsAdapter());
  registry.register(new DemoBookAdapter());
  const dk = registry.resolve(new URL("https://sportsbook.draftkings.com/in-game/nfl"));
  assert.equal(dk.adapter, undefined);
  assert.ok(dk.reason.includes("disabled by feature flag"));
  const demo = registry.resolve(new URL("http://localhost:4173/demobook"));
  assert.ok(demo.adapter instanceof DemoBookAdapter);
});

test("adapter registry: unsupported site has no adapter", () => {
  const registry = new AdapterRegistry();
  registry.register(new DemoBookAdapter());
  const r = registry.resolve(new URL("https://www.espn.com/nfl"));
  assert.equal(r.adapter, undefined);
  assert.ok(r.reason.includes("no adapter supports this page"));
});

test("feature flags can be flipped to enable a scaffold (documented operator action)", () => {
  const registry = new AdapterRegistry({ draftkings: true });
  registry.register(new DraftKingsAdapter());
  const r = registry.resolve(new URL("https://sportsbook.draftkings.com/in-game/nfl"));
  assert.ok(r.adapter instanceof DraftKingsAdapter);
  assert.equal(DEFAULT_FEATURE_FLAGS.draftkings, false);
});

test("safeDetect converts adapter throws into degraded results, never invented markets", async () => {
  const adapter = new DemoBookAdapter();
  // Force a throw by passing a host object that explodes on querySelector.
  const evil = { querySelector: () => { throw new Error("boom"); } } as unknown as Document;
  const result = await safeDetect(adapter, evil);
  assert.equal(result.status, "ADAPTER_DEGRADED");
  assert.equal(result.markets.length, 0);
  assert.ok(result.notes[0]!.includes("threw during detection"));
});

// ---------------------------------------------------------------------------
// Visibility filtering (pure geometry/CSS over fixture-like inputs)
// ---------------------------------------------------------------------------

const VIEWPORT = { width: 1280, height: 800 };

test("a fully on-screen card is visible", () => {
  const d = decideVisibility({ top: 100, bottom: 220, left: 20, right: 400 }, VIEWPORT, {});
  assert.equal(d.visible, true);
});

test("a card scrolled mostly off-screen (45% visible) fails the 50% threshold", () => {
  // 200px tall card straddling the bottom edge with only 90px visible.
  const d = decideVisibility({ top: 710, bottom: 910, left: 20, right: 400 }, VIEWPORT, {}, 0.5);
  assert.equal(d.visible, false);
  assert.ok(Math.abs(d.intersectionRatio - 90 / 200) < 1e-9);
});

test("display:none cards are never visible regardless of geometry", () => {
  const d = decideVisibility({ top: 0, bottom: 100, left: 0, right: 100 }, VIEWPORT, { display: "none" });
  assert.equal(d.visible, false);
});

test("collapsed (visibility:hidden) and transparent cards are not visible", () => {
  assert.equal(isStyleVisible({ visibility: "hidden" }), false);
  assert.equal(isStyleVisible({ visibility: "collapse" }), false);
  assert.equal(isStyleVisible({ opacity: 0 }), false);
  assert.equal(isStyleVisible({ opacity: 0.05 }), true);
});

test("occluded cards (behind a modal overlay) are not visible", () => {
  const d = decideVisibility({ top: 100, bottom: 200, left: 0, right: 100 }, VIEWPORT, { occluded: true });
  assert.equal(d.visible, false);
  assert.ok(d.reasons.some((r) => r.includes("occluded")));
});

test("intersectionRatio math is exact for partial overlaps", () => {
  // 400x200 card; viewport clips the right edge at 1280 → 280px visible → 70%.
  const r = intersectionRatio({ top: 0, bottom: 200, left: 1000, right: 1400 }, VIEWPORT);
  assert.ok(Math.abs(r - 280 / 400) < 1e-9);
});
