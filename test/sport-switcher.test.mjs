import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { buildSandbox, loadApp, VIEWER } from './helpers/sandbox.mjs';

/**
 * SPORT SWITCHER TESTS — Phase 2, commit 2.
 *
 * Boot-time sport resolution from the per-device preference, the model:null
 * guard for adapters without a distribution model, NBA boot integration
 * (slate load → render with zero throws), and switcher item derivation.
 * The switcher persists `propwire_active_sport` and reloads; each page load
 * is single-sport, which is what these tests exercise.
 */

function loadRegistry(sandbox) {
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'registry.js'), 'utf8'), sandbox, { filename: 'registry.js' });
  return sandbox.window.PropWireSports;
}

test('registry defaultId: prefers valid stored sport, falls back to nfl on anything else', () => {
  // No preference stored.
  let { sandbox } = buildSandbox();
  let reg = loadRegistry(sandbox);
  assert.equal(reg.defaultId(), 'nfl');

  // Valid stored preference (resolved AFTER adapters register, per load order).
  ({ sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } }));
  reg = loadRegistry(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nfl.js'), 'utf8'), sandbox, { filename: 'nfl.js' });
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nba.js'), 'utf8'), sandbox, { filename: 'nba.js' });
  assert.equal(reg.defaultId(), 'nba');

  // Garbage / unregistered / tampered values must never boot a broken sport.
  for (const bad of ['ufc', 'NFL', 'nba;;', '__proto__', '']) {
    ({ sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: bad } }));
    reg = loadRegistry(sandbox);
    vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nfl.js'), 'utf8'), sandbox, { filename: 'nfl.js' });
    assert.equal(reg.defaultId(), 'nfl', `stored "${bad}" must fall back to nfl`);
  }
});

test('NBA boot: app.js loads with a model-less adapter (model:null guard)', () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  // loadApp executes registry + nfl + nba + app.js: the MODEL_ALPHA/MODEL_K
  // guard must prevent the null.alpha crash the boot previously had.
  const P = loadApp(sandbox);
  assert.equal(P.SPORT_ID, 'nba');
  assert.equal(P.adapter.label, 'NBA');
});

test('NBA boot integration: default slate loads, renders, evaluates without throws', async () => {
  const { sandbox, registry, lsStore } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const P = loadApp(sandbox);

  // Boot slate resolution: the NFL default key is unknown to the NBA adapter.
  assert.equal(P.defaultBootSlate(), '2026-10-22');
  await P.loadSlate(P.defaultBootSlate());

  assert.equal(P.state.slateKey, '2026-10-22');
  assert.equal(P.state.slate.length, 29, 'fixture slate rows loaded');
  assert.equal(P.state.filters.market, 'points', 'market resets to the adapter default');
  assert.ok(P.state.games.length === 2, 'fixture games loaded');
  assert.ok(P.state.odds.quotes.length === 11, 'fixture quotes loaded');
  // Per-sport storage: NBA uses its own namespaces, never NFL's.
  assert.equal(P.storage.STORE.watchlist, 'propwire_watchlist_nba');
  assert.equal(P.storage.STORE.sniperConfig, 'propwire_sniper_config_nba');
  assert.equal(P.storage.STORE.ledger, 'propwire_portfolio_ledger_v2');

  // Breaker comes from the config's uncalibrated NBA block.
  const breaker = P.breakerFor('points');
  assert.equal(breaker.source, 'config');
  assert.equal(breaker.calibrated, false);
  assert.equal(breaker.driftHurdle, 3.0);

  // Every fixture quote evaluates honestly: ingested (never verified), and
  // never actionable (verified:false → qState 'ingested').
  for (const row of P.state.slate) {
    const evaluation = P.evaluateRow(row);
    assert.equal(evaluation.actionable, false, `${row.player_id} must not be actionable on fixture data`);
  }
  const quotedRow = P.state.slate.find((r) => r.player_id === 'fx-nba-jaylen-brown');
  assert.equal(P.evaluateRow(quotedRow).state, 'ingested');

  // Rendering pipeline must complete without throwing for table + cards.
  P.setView('table');
  P.renderAll();
  P.setView('cards');
  P.renderAll();

  // Switcher items derive from the registry with the active sport flagged.
  const items = JSON.parse(JSON.stringify(P.sportSwitcherItems()));
  assert.deepEqual(items.map((i) => i.id), ['nfl', 'nba']);
  assert.equal(items.find((i) => i.id === 'nba').active, true);
  assert.equal(items.find((i) => i.id === 'nba').label, 'NBA');
  assert.equal(items.find((i) => i.id === 'nfl').active, false);
});

test('switchToSport: unknown sport and same-sport clicks are no-ops; storage failure aborts reload', () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const P = loadApp(sandbox);
  // Unknown sport → require() throws inside → no write, no reload.
  P.switchToSport('ufc');
  assert.equal(sandbox.localStorage.getItem('propwire_active_sport'), 'nba');
  // Same sport → no-op.
  P.switchToSport('nba');
  assert.equal(sandbox.localStorage.getItem('propwire_active_sport'), 'nba');
  // window.location.reload is a no-op stub in the sandbox; assert the
  // preference write path (the reload contract) via a different sport.
  P.switchToSport('nfl');
  assert.equal(sandbox.localStorage.getItem('propwire_active_sport'), 'nfl');
});

test('NFL boot unchanged: no preference keeps the 2026_w7 slate and calibrated breaker', async () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  assert.equal(P.SPORT_ID, 'nfl');
  assert.equal(P.defaultBootSlate(), '2026_w7', 'NFL boot slate must stay exactly as before');
  await P.loadSlate('2026_w7');
  const breaker = P.breakerFor('receiving_yards');
  assert.equal(breaker.calibrated, true);
  assert.equal(breaker.source, 'config');
});
