import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { buildSandbox, loadApp, attachSyntheticQuote, authorizeSyntheticExecution, VIEWER, FROZEN_MS } from './helpers/sandbox.mjs';

/**
 * FEED HEALTH / FAILURE-MODE UI — Phase 2, commit 5.
 *
 * A feed outage must never masquerade as "the market is efficient". These
 * tests pin: fixture labeling, transport-failure banners (slate/odds),
 * staleness thresholds from the per-sport breaker config, and the ledger
 * data_provenance stamp (fixture entries stamped; NFL live entries carry
 * NO field — ledger schema stays byte-identical for NFL).
 *
 * The shared parity sandbox has no getElementById (by design — that is what
 * keeps Phase 2 chrome outside the golden snapshots). These tests attach a
 * LOCAL getElementById to their own sandbox instances to assert banner copy.
 */

function attachLocalDom(sandbox) {
  const els = new Map();
  sandbox.document.getElementById = (id) => {
    if (!els.has(id)) {
      els.set(id, {
        id, innerHTML: '', textContent: '', hidden: true, className: '',
        dataset: {}, style: { cssText: '' },
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        addEventListener() {}, removeEventListener() {},
      });
    }
    return els.get(id);
  };
  return els;
}

/** Local file-backed fetch mirroring the sandbox impl, with per-path overrides.
 * The odds feed is pinned to the committed w7 fixture for the same reason as
 * the shared sandbox: viewer/live_odds_feed.json now carries real Polymarket
 * quotes (v176) that refresh daily — staleness scenarios need fixed inputs. */
function localFetcher(overrides = {}) {
  const pinnedOdds = path.join(VIEWER, '..', 'test', 'fixtures', 'live_odds_feed_w7_pinned.json');
  return async (rawPath) => {
    const clean = String(rawPath).split('?')[0];
    const override = overrides[clean];
    if (override) return override();
    if (clean === '/live_odds_feed.json' || clean === 'live_odds_feed.json') {
      const text = fs.readFileSync(pinnedOdds, 'utf8');
      return { ok: true, status: 200, json: async () => JSON.parse(text) };
    }
    const file = path.join(VIEWER, clean.replace(/^\/+/, ''));
    if (!fs.existsSync(file)) return { ok: false, status: 404, json: async () => { throw new Error('not found'); } };
    const text = fs.readFileSync(file, 'utf8');
    return { ok: true, status: 200, json: async () => JSON.parse(text) };
  };
}

test('fixture dataset surfaces the RESEARCH FIXTURES banner (NBA)', async () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  await P.loadSlate(P.defaultBootSlate());
  P.updateFeedHealthUI?.();
  const banner = els.get('dataQualityBanner');
  assert.ok(banner, 'banner element resolved');
  assert.equal(banner.hidden, false, 'fixture banner visible');
  assert.ok(banner.className.includes('fixture'), 'fixture tone class');
  assert.match(banner.innerHTML, /RESEARCH FIXTURES/);
  // Banner must SAY what it means (audit M15): sample data, not actionable,
  // not a research record — never just a bare "FIXTURE" label.
  assert.match(banner.innerHTML, /not actionable/i);
  assert.match(banner.innerHTML, /not a research record/i);
  assert.match(banner.innerHTML, /not sportsbook quotes/i);
  assert.equal(P.state.feedHealth.dataKind, 'fixture');
  // Fixture timestamps sit in the future relative to the frozen test clock → fresh.
  assert.equal(P.feedHealthStates().oddsFreshness, 'ok');
});

test('odds feed outage shows ODDS FEED OFFLINE, never the anti-tout state', async () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  sandbox.fetch = localFetcher({
    'nba_odds_2026-10-22.json': () => ({ ok: false, status: 404, json: async () => { throw new Error('nf'); } }),
  });
  await P.loadSlate(P.defaultBootSlate());
  assert.equal(P.state.feedHealth.odds, 'error');
  const banner = els.get('dataQualityBanner');
  assert.match(banner.innerHTML, /ODDS FEED OFFLINE/);
  assert.match(banner.innerHTML, /no actionable classification is possible/i);
  assert.ok(banner.className.includes('error'));
});

test('slate feed outage shows SLATE FEED OFFLINE with an honest empty-board explanation', async () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  sandbox.fetch = localFetcher({
    'nba_slate_2026-10-22.json': () => ({ ok: false, status: 500, json: async () => { throw new Error('nf'); } }),
  });
  await P.loadSlate(P.defaultBootSlate());
  assert.equal(P.state.feedHealth.slate, 'error');
  assert.equal(P.state.slate.length, 0);
  const banner = els.get('dataQualityBanner');
  assert.match(banner.innerHTML, /SLATE FEED OFFLINE/);
  assert.match(banner.innerHTML, /empty because data is missing, not because the market is efficient/i);
});

test('stale odds and unverified model context keep the banner in error state (NFL live)', async () => {
  const { sandbox } = buildSandbox();
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  // Frozen clock = 2026-10-22T12:00Z; the W7 live feed was updated 03:32Z →
  // ~8.5h old vs the 6h per-sport limit. NFL is live data, so staleness
  // semantics apply (fixtures suppress staleness by design).
  await P.loadSlate('2026_w7');
  const states = P.feedHealthStates();
  assert.equal(states.dataKind, 'live');
  assert.equal(states.oddsFreshness, 'stale');
  assert.equal(states.thresholds.oddsStaleSeconds, 21600);
  const banner = els.get('dataQualityBanner');
  assert.match(banner.innerHTML, /ODDS STALE/);
  assert.match(banner.innerHTML, /MODEL CONTEXT BLOCKED/);
  assert.match(banner.innerHTML, /treat prices as historical/i);
  assert.ok(banner.className.includes('error'));
  const snapshot = els.get('snapshotAgePill');
  assert.equal(snapshot.hidden, false);
  assert.match(snapshot.textContent, /Snapshot Mode · Captured Oct 21, 11:32 PM EDT/);
});

test('snapshot pill appears after 30 minutes without changing the execution staleness threshold', async () => {
  const { sandbox } = buildSandbox();
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  P.state.feedHealth.oddsUpdatedAt = new Date(FROZEN_MS - 20 * 60_000).toISOString();
  P.updateFeedHealthUI();
  assert.equal(els.get('snapshotAgePill').hidden, true);
  P.state.feedHealth.oddsUpdatedAt = new Date(FROZEN_MS - 31 * 60_000).toISOString();
  P.updateFeedHealthUI();
  assert.equal(els.get('snapshotAgePill').hidden, false);
  assert.match(els.get('snapshotAgePill').textContent, /Snapshot Mode · Captured/);
  assert.equal(P.feedHealthStates().oddsFreshness, 'ok');
});

test('unverified NFL feed never renders a LIVE or VERIFIED status label', async () => {
  const { sandbox } = buildSandbox();
  attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  assert.equal(P.state.odds.feed_status, 'UNVERIFIED_MANUAL_ONLY');
  assert.equal(P.feedVerificationLabel(), 'UNVERIFIED');
});

test('abandoned news feed (>24h) fires the banner; dead-man latch stays independent (NFL live)', async () => {
  const { sandbox } = buildSandbox();
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  // 72h-old heartbeat: the feed is genuinely abandoned. BOTH layers must
  // fire — the wide display window (banner) and the 300s dispatch dead-man.
  sandbox.fetch = localFetcher({
    'news_watcher_state.json': () => ({
      ok: true, status: 200,
      json: async () => ({ version: '1.1.0', last_polled_at: '2026-10-19T12:00:00Z', poll_count: 1, is_alive: false, teams_locked: {}, players_pending: {} }),
    }),
  });
  await P.loadSlate('2026_w7');
  const states = P.feedHealthStates();
  assert.equal(states.newsFeedFreshness, 'stale');
  assert.equal(states.newsFreshness, 'stale');
  assert.equal(states.thresholds.newsStaleSeconds, 300);
  assert.equal(states.thresholds.newsFeedStaleSeconds, 86400);
  const banner = els.get('dataQualityBanner');
  assert.match(banner.innerHTML, /NEWS FEED STALE/);
  assert.match(banner.innerHTML, /sniper dispatch is suppressed/i);
});

test('recent heartbeat (<24h, > dead-man) clears the banner without un-suppressing dispatch (NFL live)', async () => {
  const { sandbox } = buildSandbox();
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  // 30-minute-old heartbeat: this is the steady state of the scheduled
  // commit-based poller (news_watcher.yml). The feed is alive, so the
  // human-facing banner must NOT fire — while the 300s autonomous-dispatch
  // dead-man stays tripped (no persistent sub-5-min watcher exists).
  sandbox.fetch = localFetcher({
    'news_watcher_state.json': () => ({
      ok: true, status: 200,
      json: async () => ({ version: '1.1.0', last_polled_at: '2026-10-22T11:30:00Z', poll_count: 42, is_alive: true, teams_locked: {}, players_pending: {} }),
    }),
  });
  await P.loadSlate('2026_w7');
  const states = P.feedHealthStates();
  assert.equal(states.newsFeedFreshness, 'ok');
  assert.equal(states.newsFreshness, 'stale', 'dead-man dispatch latch must stay tripped by the 300s window');
  const banner = els.get('dataQualityBanner');
  assert.doesNotMatch(banner.innerHTML, /NEWS FEED STALE/);
});

test('fixture datasets suppress staleness signals (static by design)', async () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  // Fixture updated_at is fixed in the past relative to any real clock —
  // staleness must stay 'ok' for fixture data while transport errors would
  // still surface.
  await P.loadSlate(P.defaultBootSlate());
  const states = P.feedHealthStates();
  assert.equal(states.dataKind, 'fixture');
  assert.equal(states.oddsFreshness, 'ok');
  assert.match(els.get('snapshotAgePill').textContent, /Demo fixture · Synthetic sample data/);
});

test('ledger trust boundary: fixture entries are blocked; trusted NFL entries preserve schema', async () => {
  // NBA fixtures are research-only and must never create wager records.
  const nba = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const NP = loadApp(nba.sandbox);
  await NP.loadSlate(NP.defaultBootSlate());
  const fixtureQuote = NP.state.odds.quotes.find((q) => q.market === 'points');
  NP.state.filters.market = 'points';
  NP.state.portfolio = [];
  NP.logBet(fixtureQuote.player_id);
  assert.equal(NP.state.portfolio.length, 0);
  assert.equal(NP.executionDecision(NP.state.slate.find((row) => row.player_id === fixtureQuote.player_id)).code, 'historical');

  // NFL: the ledger schema must remain byte-identical — no provenance key.
  const nfl = buildSandbox();
  const FP = loadApp(nfl.sandbox);
  await FP.loadSlate('2026_w7');
  // Shipped demo quotes intentionally fail slate matching (provenance hotfix);
  // harness-only synthetic quote provides the attachable input.
  const synthetic = attachSyntheticQuote(FP);
  authorizeSyntheticExecution(FP, synthetic);
  const liveQuote = FP.state.odds.quotes.find((q) => q.quote_id === 'harness_synthetic_open');
  FP.state.filters.market = 'receiving_yards';
  FP.state.portfolio = [];
  FP.logBet(liveQuote.player_id);
  FP.confirmExecution(liveQuote.player_id);
  assert.equal(FP.state.portfolio.length, 1);
  assert.equal('data_provenance' in FP.state.portfolio[0], false, 'NFL live entries must NOT gain the field (parity)');
  assert.equal(FP.state.portfolio[0].sport, 'nfl');
});

// ─── Messaging-consistency contract (2026-10-27 owner review) ──────────────
// A fail-closed board must NOT claim "the market is efficient" while prices
// are stale or unverifiable — the empty state has to say qualification is
// PAUSED. The efficiency claim is reserved for a fresh, verified feed with
// genuinely zero qualified rows.

const STALE_LIVE_HEALTH = () => ({
  dataKind: 'live', odds: 'ok', news: 'ok',
  // Anchor to the SANDBOX's frozen clock, not the real one. With real
  // Date.now() this fixture aged itself into the future (frozen now =
  // 2026-10-22): age clamped to 0, freshness read "ok", and the paused
  // panel never rendered — a time bomb that detonated on 2026-10-29.
  oddsUpdatedAt: new Date(FROZEN_MS - 6 * 864e5).toISOString(),
  newsLastPolledAt: new Date(FROZEN_MS).toISOString(),
});
const FRESH_LIVE_HEALTH = () => ({
  dataKind: 'live', odds: 'ok', news: 'ok',
  oddsUpdatedAt: new Date(FROZEN_MS).toISOString(),
  newsLastPolledAt: new Date(FROZEN_MS).toISOString(),
});

function renderActionableEmpty(P, verifiedQuote = null) {
  P.state.odds.quotes = verifiedQuote ? [verifiedQuote] : [];
  if (verifiedQuote) P.state.slate = []; // Isolate the zero-row rendering branch.
  P.state.filters.playMode = 'actionable';
  P.state.filters.market = 'receiving_yards';
  P.renderBoard();
}

test('stale live feed renders LIVE QUALIFICATION PAUSED, never the efficiency claim', async () => {
  const { sandbox, registry } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  P.state.feedHealth = STALE_LIVE_HEALTH();
  renderActionableEmpty(P);
  const empty = registry.get('#emptyState');
  assert.ok(empty.innerHTML.includes('Live qualification paused'), 'paused title rendered');
  assert.ok(empty.innerHTML.includes('cannot be verified'), 'honest body copy present');
  assert.ok(empty.innerHTML.includes('historical research'), 'research framing present');
  assert.ok(empty.innerHTML.includes('Last trusted quote'), 'last trusted quote time surfaced in the panel');
  assert.ok(!/market is efficient/i.test(empty.innerHTML), 'no efficiency claim under staleness');
});

test('fresh verified feed with zero qualified rows keeps the anti-tout efficiency message', async () => {
  const { sandbox, registry } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  P.state.feedHealth = FRESH_LIVE_HEALTH();
  renderActionableEmpty(P, {
    player_id: P.state.slate[0].player_id, market: 'receiving_yards',
    line: 1.5, over_odds: -110, under_odds: -110,
    book: 'SyntheticBook', observed_at: new Date().toISOString(),
    receipt_id: 'synthetic-test-receipt', verified: true,
    evaluation: { best_side: 'OVER', prob_edge: 0, expected_return: 0 },
  });
  const empty = registry.get('#emptyState');
  assert.ok(empty.innerHTML.includes('0 Qualified Plays Today'), 'anti-tout state intact when feeds verified');
  assert.ok(/market is efficient/i.test(empty.innerHTML), 'efficiency claim only when prices are verifiable');
  assert.ok(!empty.innerHTML.includes('Live qualification paused'), 'paused copy not shown on a fresh feed');
});

test('fresh transport with zero verified quotes remains paused', async () => {
  const { sandbox, registry } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  P.state.feedHealth = FRESH_LIVE_HEALTH();
  renderActionableEmpty(P);
  const empty = registry.get('#emptyState');
  assert.ok(empty.innerHTML.includes('Live qualification paused'));
  assert.ok(!/market is efficient/i.test(empty.innerHTML));
});
