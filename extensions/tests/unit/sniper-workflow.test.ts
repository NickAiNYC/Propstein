/**
 * PropStein Live Sniper — 5-State Workflow & Tactical Plays Unit Tests
 * ===================================================================
 * Verifies:
 *  1. State 1: Fuzzy entity resolution & fail-closed collision handling
 *  2. State 2: Freshness kill-switches (20s odds / 90s injury) & verification hierarchy
 *  3. State 3 & 4: Closed Shadow DOM isolation, panic kill switch (Ctrl+Shift+K), and handoff
 *  4. State 5: Stale detector / book repricing delay
 *  5. Multi-book race tracking & strict alert routing
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "linkedom";
import {
  extractLastName,
  normalizeMarketScope,
  buildNormalizedEntityKey,
  matchExtractedNodeToSignal,
  evaluateSignalVerification,
  routeSignalAlert,
  type BackendLiveSignal,
  type ExtractedMarketNode,
  type PlacedAuditRecord,
} from "@propstein/core";
import {
  detectBookFromHost,
  extractMarketNodeFromElement,
} from "@propstein/detection";
import { OverlayManager } from "@propstein/ui/overlay";
import { WebSocketRelay } from "../../apps/chrome/src/ws-relay.ts";

// ---------------------------------------------------------------------------
// 1. Entity Extraction & Matching
// ---------------------------------------------------------------------------

test("extractLastName normalizes suffixes and punctuation", () => {
  assert.equal(extractLastName("Tyrese Maxey"), "maxey");
  assert.equal(extractLastName("Patrick Mahomes II"), "mahomes");
  assert.equal(extractLastName("Kenneth Walker III"), "walker");
  assert.equal(extractLastName("A.J. Brown"), "brown");
  assert.equal(extractLastName("Hunter Henry"), "henry");
  assert.equal(extractLastName(""), "");
});

test("normalizeMarketScope maps prop markets to canonical tokens", () => {
  assert.equal(normalizeMarketScope("Player Points"), "pts");
  assert.equal(normalizeMarketScope("Points Over/Under"), "pts");
  assert.equal(normalizeMarketScope("Receiving Yards"), "rec_yds");
  assert.equal(normalizeMarketScope("Player Receptions"), "receptions");
  assert.equal(normalizeMarketScope("Assists"), "ast");
  assert.equal(normalizeMarketScope("Rebounds"), "reb");
});

test("buildNormalizedEntityKey generates canonical matching string", () => {
  const key = buildNormalizedEntityKey("Tyrese Maxey", "Points", 26.5);
  assert.equal(key.lastName, "maxey");
  assert.equal(key.marketScope, "pts");
  assert.equal(key.lineBucket, 26);
  assert.equal(key.canonicalKey, "maxey:pts:26");
});

test("matchExtractedNodeToSignal matches within line tolerance", () => {
  const candidate: BackendLiveSignal = {
    signalId: "sig-maxey-pts",
    playerId: "00-maxey",
    playerName: "Tyrese Maxey",
    marketType: "points",
    selection: "OVER",
    line: 26.5,
    price: -110,
    modelFairLine: 36.5,
    pOver: 0.936,
    gapPts: 10.0,
    edgePct: 27.1,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  const node: ExtractedMarketNode = {
    rawPlayer: "Tyrese Maxey",
    rawMarket: "Points",
    line: 26.5,
    price: -110,
    selection: "OVER",
    book: "draftkings",
  };

  const matched = matchExtractedNodeToSignal(node, [candidate], 1.5);
  assert.ok(matched !== null);
  assert.equal(matched?.signalId, "sig-maxey-pts");
});

test("matchExtractedNodeToSignal fails closed when line difference exceeds tolerance", () => {
  const candidate: BackendLiveSignal = {
    signalId: "sig-henry",
    playerId: "00-henry",
    playerName: "Hunter Henry",
    marketType: "receiving_yards",
    selection: "OVER",
    line: 33.5,
    price: -115,
    modelFairLine: 31.5,
    pOver: 0.52,
    gapPts: -2.0,
    edgePct: 1.5,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  const node: ExtractedMarketNode = {
    rawPlayer: "Hunter Henry",
    rawMarket: "Receiving Yards",
    line: 45.5, // 12 yards difference
    price: -115,
    selection: "OVER",
    book: "fanduel",
  };

  const matched = matchExtractedNodeToSignal(node, [candidate], 1.5);
  assert.equal(matched, null);
});

test("matchExtractedNodeToSignal fails closed on ambiguous collision across distinct players", () => {
  const candidate1: BackendLiveSignal = {
    signalId: "sig-b1",
    playerId: "player-1",
    playerName: "Zach Brown",
    marketType: "points",
    selection: "OVER",
    line: 12.5,
    price: -110,
    modelFairLine: 15.5,
    pOver: 0.60,
    gapPts: 3.0,
    edgePct: 6.5,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  const candidate2: BackendLiveSignal = {
    signalId: "sig-b2",
    playerId: "player-2", // different player ID
    playerName: "Bruce Brown",
    marketType: "points",
    selection: "OVER",
    line: 12.5,
    price: -110,
    modelFairLine: 14.5,
    pOver: 0.58,
    gapPts: 2.0,
    edgePct: 4.5,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  // Node only has "Brown"
  const node: ExtractedMarketNode = {
    rawPlayer: "Brown",
    rawMarket: "Points",
    line: 12.5,
    price: -110,
    book: "draftkings",
  };

  const matched = matchExtractedNodeToSignal(node, [candidate1, candidate2], 1.5);
  assert.equal(matched, null, "Colliding ambiguous candidates must fail closed");
});

// ---------------------------------------------------------------------------
// 2. Verification Lock Hierarchy & Freshness Kill-Switches
// ---------------------------------------------------------------------------

test("evaluateSignalVerification: unverified quote locks immediately", () => {
  const signal: BackendLiveSignal = {
    signalId: "sig-1",
    playerId: "p1",
    playerName: "Test Player",
    marketType: "pts",
    selection: "OVER",
    line: 20.5,
    price: -110,
    modelFairLine: 25.5,
    pOver: 0.70,
    gapPts: 5.0,
    edgePct: 15.0,
    verificationStatus: "OBSERVED", // not verified
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  const result = evaluateSignalVerification(signal);
  assert.equal(result.state, "LOCKED");
  assert.equal(result.reasonCode, "UNVERIFIED");
});

test("evaluateSignalVerification: odds older than 20s triggers kill switch lock", () => {
  const now = Date.now();
  const oldTime = new Date(now - 25000).toISOString(); // 25s old > 20s

  const signal: BackendLiveSignal = {
    signalId: "sig-2",
    playerId: "p2",
    playerName: "Test Player",
    marketType: "pts",
    selection: "OVER",
    line: 20.5,
    price: -110,
    modelFairLine: 25.5,
    pOver: 0.70,
    gapPts: 5.0,
    edgePct: 15.0,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: oldTime,
  };

  const result = evaluateSignalVerification(signal, now);
  assert.equal(result.state, "LOCKED");
  assert.equal(result.reasonCode, "QUOTE_EXPIRED");
});

test("evaluateSignalVerification: injury context older than 90s triggers kill switch lock", () => {
  const now = Date.now();
  const freshTime = new Date(now - 5000).toISOString(); // 5s old

  const signal: BackendLiveSignal = {
    signalId: "sig-3",
    playerId: "p3",
    playerName: "Test Player",
    marketType: "pts",
    selection: "OVER",
    line: 20.5,
    price: -110,
    modelFairLine: 25.5,
    pOver: 0.70,
    gapPts: 5.0,
    edgePct: 15.0,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: freshTime,
    injuryContextAgeSec: 105, // > 90s
  };

  const result = evaluateSignalVerification(signal, now);
  assert.equal(result.state, "LOCKED");
  assert.equal(result.reasonCode, "INJURY_STALE");
});

test("evaluateSignalVerification: verified, fresh, gate-passed signal evaluates to QUALIFIED", () => {
  const now = Date.now();
  const freshTime = new Date(now - 4000).toISOString(); // 4s old

  const signal: BackendLiveSignal = {
    signalId: "sig-4",
    playerId: "p4",
    playerName: "Tyrese Maxey",
    marketType: "pts",
    selection: "OVER",
    line: 26.5,
    price: -110,
    modelFairLine: 36.5,
    pOver: 0.936,
    gapPts: 10.0,
    edgePct: 27.1,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: freshTime,
    injuryContextAgeSec: 30,
  };

  const result = evaluateSignalVerification(signal, now);
  assert.equal(result.state, "QUALIFIED");
  assert.equal(result.ageSec, 4);
});

// ---------------------------------------------------------------------------
// 3. Alert Routing Policy
// ---------------------------------------------------------------------------

test("routeSignalAlert: push priority only for verified + gate-passed signals", () => {
  const verifiedSignal: BackendLiveSignal = {
    signalId: "sig-v",
    playerId: "p-v",
    playerName: "Maxey",
    marketType: "pts",
    selection: "OVER",
    line: 26.5,
    price: -110,
    modelFairLine: 36.5,
    pOver: 0.936,
    gapPts: 10.0,
    edgePct: 27.1,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  const unverifiedSignal: BackendLiveSignal = {
    ...verifiedSignal,
    verificationStatus: "OBSERVED",
  };

  assert.equal(routeSignalAlert(verifiedSignal, 4.0), "push_priority");
  assert.equal(routeSignalAlert(unverifiedSignal, 4.0), "side_panel_only");
  assert.equal(routeSignalAlert(verifiedSignal, 4.0, true), "suppress_all");
});

// ---------------------------------------------------------------------------
// 4. Closed Shadow DOM & Panic Kill Switch
// ---------------------------------------------------------------------------

test("OverlayManager: initializes closed shadow root with isolated styling", () => {
  const { document } = parseHTML("<!DOCTYPE html><html><body><div id='target'></div></body></html>");

  let killState = false;
  let loggedRecord: PlacedAuditRecord | null = null;

  const manager = new OverlayManager({
    doc: document as any,
    onPanicKillChange: (active) => {
      killState = active;
    },
    onAuditPlaced: (record) => {
      loggedRecord = record;
    },
  });

  manager.init();

  const host = document.getElementById("__propstein_host");
  assert.ok(host !== null);
  // In closed mode, host.shadowRoot is null to external callers
  assert.equal((host as any).shadowRoot, null);

  const target = document.getElementById("target")!;
  const signal: BackendLiveSignal = {
    signalId: "sig-test",
    playerId: "p-test",
    playerName: "Tyrese Maxey",
    marketType: "pts",
    selection: "OVER",
    line: 26.5,
    price: -110,
    modelFairLine: 36.5,
    pOver: 0.936,
    gapPts: 10.0,
    edgePct: 27.1,
    verificationStatus: "VERIFIED",
    gatePassed: true,
    capturedAt: new Date().toISOString(),
  };

  let staged = false;
  const overlay = manager.renderOverlay(target as any, signal, {
    onSendToSlip: () => {
      staged = true;
    },
  });
  assert.ok(overlay !== null);
  assert.ok(overlay?.innerHTML.includes("QUALIFIED"));
  assert.ok(overlay?.innerHTML.includes("Model Fair"));
  assert.ok(overlay?.innerHTML.includes("36.5"));

  // Trigger Send to slip button
  const stageBtn = overlay?.querySelector('[data-action="stage"]') as any;
  stageBtn?.click();
  assert.equal(staged, true);

  // Trigger I placed it button
  const placedBtn = overlay?.querySelector('[data-action="placed"]') as any;
  placedBtn?.click();
  assert.ok(loggedRecord !== null);
  assert.equal((loggedRecord as any)?.playerName, "Tyrese Maxey");
  assert.equal((loggedRecord as any)?.displayedLine, 26.5);

  // Trigger panic kill switch
  manager.togglePanicKill();
  assert.equal(killState, true);
  assert.equal((host as any).style.display, "none");

  manager.destroy();
});

test("OverlayManager: locked / unvalidated slate renders RESEARCH ONLY without confident probabilities", () => {
  const { document } = parseHTML(
    '<!DOCTYPE html><html><body><div id="target">Target</div></body></html>'
  );
  const manager = new OverlayManager({ doc: document as any });
  manager.init();

  const target = document.getElementById("target")!;
  const unvalidatedSignal: BackendLiveSignal = {
    signalId: "sig-unval",
    playerId: "p-test-2",
    playerName: "Joel Embiid",
    marketType: "pts",
    selection: "OVER",
    line: 32.5,
    price: -115,
    modelFairLine: 41.5,
    pOver: 0.942,
    gapPts: 9.0,
    edgePct: 24.3,
    verificationStatus: "VERIFIED",
    gatePassed: false, // Model validation gate locked
    capturedAt: new Date().toISOString(),
  };

  const overlay = manager.renderOverlay(target as any, unvalidatedSignal);
  assert.ok(overlay !== null);
  assert.ok(overlay?.innerHTML.includes("RESEARCH ONLY — LOCKED"));
  assert.ok(!overlay?.innerHTML.includes("EDGE "));
  assert.ok(overlay?.innerHTML.includes("RESEARCH ONLY"));
  assert.ok(overlay?.innerHTML.includes("PENDING VALIDATION"));
  assert.ok(!overlay?.innerHTML.includes("94.2%"));

  manager.destroy();
});

// ---------------------------------------------------------------------------
// 5. Multi-Book Repricing Lag Tracker
// ---------------------------------------------------------------------------

test("WebSocketRelay tracks book lag and identifies slowest book", () => {
  const relay = new WebSocketRelay({ wsUrl: "ws://localhost:9999" });

  relay.recordBookLag("draftkings", "pts", 4500); // 4.5s
  relay.recordBookLag("draftkings", "pts", 3500); // 3.5s -> avg 4.0s

  relay.recordBookLag("fanduel", "pts", 1200);   // 1.2s -> avg 1.2s

  const slowest = relay.getLatestArrivalBookTelemetry("pts");
  assert.ok(slowest !== null);
  assert.equal(slowest?.book, "draftkings");
  assert.equal(slowest?.avgClientObservedArrivalLagMs, 4000);
  assert.equal(slowest?.isLatestArrival, true);
  assert.equal(slowest?.clientObserved, true);

  relay.destroy();
});
