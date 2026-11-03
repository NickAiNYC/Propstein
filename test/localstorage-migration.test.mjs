import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSandbox, loadApp, attachSyntheticQuote, authorizeSyntheticExecution } from './helpers/sandbox.mjs';

/**
 * localStorage migration tests (spec item 6) — simulate pre-migration state
 * and assert zero data loss, additive-only writes, idempotency, and the
 * 30-day legacy-readability rule.
 */

const LEGACY_LEDGER = JSON.stringify([
  { id: 'bet_1', ticket_id: 'ABCD', player_id: '00-1', player_name: 'Legacy Receiver', team: 'NE', opponent: 'CHI', market: 'receiving_yards', book: 'DraftKings', line: 34.5, odds: -110, side: 'OVER', model_fair: 40, edge: 0.1, ev: 0.12, logged_at: '2026-10-01T00:00:00Z' },
  { id: 'bet_2', ticket_id: 'WXYZ', player_id: '00-2', player_name: 'Second Receiver', team: 'KC', opponent: 'LV', market: 'receptions', book: 'FanDuel', line: 4.5, odds: -120, side: 'UNDER', model_fair: 4, edge: 0.05, ev: 0.03, logged_at: '2026-10-02T00:00:00Z' },
]);
const LEGACY_WATCHLIST = JSON.stringify(['00-1', '00-2']);
const LEGACY_SNIPER = JSON.stringify({ enabled: true, minEdge: 0.15 });
const LEGACY_DISMISSED = JSON.stringify(['NE::receiving_yards']);

function seedLegacy() {
  return {
    propwire_portfolio_ledger: LEGACY_LEDGER,
    propwire_watchlist: LEGACY_WATCHLIST,
    propwire_sniper_config: LEGACY_SNIPER,
    propwire_dismissed_correlations: LEGACY_DISMISSED,
  };
}

test('migration: legacy NFL data is copied to namespaced keys with sport tags, zero data loss', async () => {
  const { sandbox, lsStore } = buildSandbox({ seedLocalStorage: seedLegacy() });
  const P = loadApp(sandbox);

  // Ledger entries tagged "nfl" and byte-preserved otherwise.
  const migrated = JSON.parse(lsStore.get('propwire_portfolio_ledger_v2'));
  assert.equal(migrated.length, 2);
  assert.equal(migrated[0].sport, 'nfl');
  assert.equal(migrated[1].sport, 'nfl');
  assert.equal(migrated[0].player_name, 'Legacy Receiver');
  assert.equal(migrated[0].line, 34.5);
  assert.equal(migrated[1].side, 'UNDER');

  // Watchlist, sniper config, dismissed correlations copied intact.
  assert.deepEqual(JSON.parse(lsStore.get('propwire_watchlist_nfl')), ['00-1', '00-2']);
  assert.deepEqual(JSON.parse(lsStore.get('propwire_sniper_config_nfl')), { enabled: true, minEdge: 0.15 });
  assert.deepEqual(JSON.parse(lsStore.get('propwire_dismissed_correlations_nfl')), ['NE::receiving_yards']);

  // The live app state uses the migrated data (JSON round-trip: state arrays
  // are vm-context intrinsics, not host Array instances).
  assert.equal(P.state.portfolio.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(P.state.watchlist)), ['00-1', '00-2']);
  assert.equal(P.storage.migrationResult.notice.migrated, true);
});

test('migration: legacy keys are never deleted or modified (30-day readability)', async () => {
  const { sandbox, lsStore } = buildSandbox({ seedLocalStorage: seedLegacy() });
  loadApp(sandbox);

  assert.equal(lsStore.get('propwire_portfolio_ledger'), LEGACY_LEDGER, 'legacy ledger must stay byte-identical');
  assert.equal(lsStore.get('propwire_watchlist'), LEGACY_WATCHLIST);
  assert.equal(lsStore.get('propwire_sniper_config'), LEGACY_SNIPER);
  assert.equal(lsStore.get('propwire_dismissed_correlations'), LEGACY_DISMISSED);
});

test('migration: idempotent — re-running does not duplicate or overwrite', async () => {
  const { sandbox, lsStore } = buildSandbox({ seedLocalStorage: seedLegacy() });
  const P = loadApp(sandbox);
  const afterFirst = JSON.parse(lsStore.get('propwire_portfolio_ledger_v2'));

  // Mutate the v2 ledger like a user would (log a bet), then re-run migration.
  P.storage.savePortfolio([...afterFirst, { id: 'bet_new', sport: 'nfl', player_id: '00-9', market: 'receiving_yards' }]);
  P.storage.migrateLegacyStorage();

  const afterSecond = JSON.parse(lsStore.get('propwire_portfolio_ledger_v2'));
  assert.equal(afterSecond.length, 3, 're-migration must not duplicate entries');
  assert.ok(afterSecond.find((e) => e.id === 'bet_new'), 'post-migration user data must survive re-migration');
});

test('migration: pre-tagged entries keep their original sport tag', async () => {
  const tagged = JSON.stringify([{ id: 'bet_1', sport: 'nba', player_id: 'x', market: 'points', line: 20.5, odds: -110, side: 'OVER' }]);
  const { sandbox, lsStore } = buildSandbox({ seedLocalStorage: { propwire_portfolio_ledger: tagged } });
  loadApp(sandbox);
  const migrated = JSON.parse(lsStore.get('propwire_portfolio_ledger_v2'));
  assert.equal(migrated[0].sport, 'nba', 'existing sport tags must be preserved, not clobbered');
});

test('migration: fresh browser (no legacy keys) creates no migrated data', async () => {
  const { sandbox, lsStore } = buildSandbox();
  const P = loadApp(sandbox);
  assert.equal(lsStore.get('propwire_portfolio_ledger_v2'), undefined);
  assert.equal(P.state.portfolio.length, 0);
  assert.equal(P.storage.migrationResult.notice.migrated, false);
});

test('migration: entries created post-migration are sport-tagged on write', async () => {
  const { sandbox, lsStore } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  // Shipped demo quotes intentionally fail slate matching (provenance hotfix);
  // the harness attaches its own synthetic quote so logBet has real input.
  const synthetic = attachSyntheticQuote(P);
  authorizeSyntheticExecution(P, synthetic);
  P.state.filters.market = 'receiving_yards';
  P.state.portfolio = [];
  P.logBet(P.state.odds.quotes.find((q) => q.market === 'receiving_yards' && q.player_id).player_id);
  P.confirmExecution(P.state.odds.quotes.find((q) => q.market === 'receiving_yards' && q.player_id).player_id);
  const stored = JSON.parse(lsStore.get('propwire_portfolio_ledger_v2'));
  assert.equal(stored[0].sport, 'nfl');
  // Legacy key untouched by new writes.
  assert.equal(lsStore.get('propwire_portfolio_ledger'), undefined);
});
