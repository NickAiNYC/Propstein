import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

function nonQualifyingVerifiedQuote(P) {
  return {
    player_id: P.state.slate[0].player_id, market: 'receiving_yards',
    line: 1.5, over_odds: -110, under_odds: -110,
    book: 'SyntheticBook', observed_at: new Date().toISOString(),
    receipt_id: 'synthetic-test-receipt', verified: true,
    evaluation: { best_side: 'OVER', prob_edge: 0, expected_return: 0 },
  };
}

/**
 * RENDER ROBUSTNESS — Phase 2, commit 3.
 *
 * Regression test for the latent bug documented in the Phase 1 report:
 * renderBoard's anti-tout branch referenced state.riskPolicy.edgeGate,
 * which was never initialized — a TypeError crashed the board whenever the
 * actionable view hit zero rows on a non-historical slate (e.g. a feed
 * outage, or every quote failing the breaker). The fix derives the gate
 * from the active policy (with a 0.10 default) instead of the phantom
 * object. This test proves the crash path renders the honest empty state.
 */

test('anti-tout empty state renders with the active gate (no riskPolicy crash)', async () => {
  const { sandbox, registry } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');

  // 2026-10-27 messaging contract: a stale live feed now renders the
  // "Live qualification paused" state (pinned in feed-health.test.mjs).
  // This test exercises the ANTI-TOUT branch — the riskPolicy crash path
  // lives in its gate interpolation — so the feed must be fresh/verified.
  P.state.feedHealth = {
    dataKind: 'live', odds: 'ok', news: 'ok',
    oddsUpdatedAt: new Date().toISOString(),
    newsLastPolledAt: new Date().toISOString(),
  };

  // A verified but non-qualifying quote reaches the anti-tout branch.
  P.state.odds.quotes = [nonQualifyingVerifiedQuote(P)];
  P.state.slate = []; // Isolate the zero-row anti-tout branch.
  P.state.filters.playMode = 'actionable';
  P.state.filters.market = 'receiving_yards';
  P.setView('table');

  // Must not throw (pre-fix: TypeError reading edgeGate of undefined).
  P.renderBoard();

  const empty = registry.get('#emptyState');
  assert.ok(empty.innerHTML.includes('0 Qualified Plays Today'), 'anti-tout empty state rendered');
  const gateMatch = empty.innerHTML.match(/statistical edge \(>(\d+)%\)/);
  assert.ok(gateMatch, 'gate percentage present in the copy');
  const expectedGate = Math.round((P.state.picks && Number.isFinite(Number(P.state.picks.gate_edge))
    ? Number(P.state.picks.gate_edge) : 0.10) * 100);
  assert.equal(Number(gateMatch[1]), expectedGate, 'copy shows the ACTIVE gate, not a hardcoded constant');

  // The phantom object must stay absent — no code path may recreate it.
  assert.equal(P.state.riskPolicy, undefined, 'state.riskPolicy must not exist (fix removes the reference)');
});

test('anti-tout gate falls back to 10% when no picks policy exists', async () => {
  const { sandbox, registry } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  // Fresh/verified feed required to reach the anti-tout branch (see above).
  P.state.feedHealth = {
    dataKind: 'live', odds: 'ok', news: 'ok',
    oddsUpdatedAt: new Date().toISOString(),
    newsLastPolledAt: new Date().toISOString(),
  };
  P.state.picks = {};           // e.g. picks feed unavailable
  P.state.odds.quotes = [nonQualifyingVerifiedQuote(P)];
  P.state.slate = [];
  P.state.filters.playMode = 'actionable';
  P.renderBoard();
  const empty = registry.get('#emptyState');
  assert.ok(empty.innerHTML.includes('statistical edge (>10%)'), 'default 10% gate shown without a picks policy');
});
