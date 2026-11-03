import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { buildSandbox, VIEWER } from './helpers/sandbox.mjs';

function loadRegistry(sandbox) {
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'registry.js'), 'utf8'), sandbox, { filename: 'registry.js' });
  return sandbox.window.PropWireSports;
}

function minimalAdapter(overrides = {}) {
  return {
    id: 'test',
    label: 'Test',
    periodNoun: 'Round',
    markets: { m1: { id: 'm1' } },
    defaultMarket: 'm1',
    slates: {},
    ...overrides,
  };
}

test('adapter registry: registers, retrieves, and lists adapters', () => {
  const { sandbox } = buildSandbox();
  const reg = loadRegistry(sandbox);
  reg.register(minimalAdapter());
  assert.equal(reg.get('test').label, 'Test');
  assert.deepEqual(JSON.parse(JSON.stringify(reg.ids())), ['test']);
  assert.equal(reg.get('missing'), null);
  assert.throws(() => reg.require('missing'), /unknown sport/);
  assert.equal(reg.defaultId(), 'nfl');
});

test('adapter registry: rejects duplicates and incomplete adapters', () => {
  const { sandbox } = buildSandbox();
  const reg = loadRegistry(sandbox);
  reg.register(minimalAdapter());
  assert.throws(() => reg.register(minimalAdapter()), /duplicate adapter id/);
  assert.throws(() => reg.register({ id: 'x', label: 'X' }), /missing required field/);
  assert.throws(() => reg.register(minimalAdapter({ id: null })), /adapter\.id/);
});

test('NFL adapter: contract complete, markets cover marketOrder, storage keys namespaced', () => {
  const { sandbox } = buildSandbox();
  const reg = loadRegistry(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nfl.js'), 'utf8'), sandbox, { filename: 'nfl.js' });
  const nfl = reg.require('nfl');

  assert.equal(nfl.id, 'nfl');
  assert.equal(nfl.periodNoun, 'Week');
  for (const id of nfl.marketOrder) {
    const m = nfl.markets[id];
    assert.ok(m, `market ${id} missing`);
    for (const field of ['fair', 'projection', 'actual', 'settledActual', 'settledLine', 'dist', 'prediction', 'fairProbText']) {
      assert.equal(typeof m[field], 'function', `market ${id} missing hook ${field}`);
    }
    assert.ok(m.breaker && Number.isFinite(m.breaker.driftHurdle));
  }
  assert.deepEqual(JSON.parse(JSON.stringify(nfl.positions)), ['WR', 'TE', 'RB']);
  for (const key of Object.values(nfl.storageKeys)) {
    // The v2 ledger is the single shared store (entries carry a `sport` field
    // per the spec); every other key must be sport-namespaced.
    if (key === 'propwire_portfolio_ledger_v2') continue;
    assert.ok(key.includes('nfl'), `storage key ${key} must be sport-namespaced`);
  }
  // Storage keys must never collide with the legacy keys (30-day dual-write policy).
  for (const legacy of Object.values(nfl.legacyKeys)) {
    assert.ok(!Object.values(nfl.storageKeys).includes(legacy), `storage key collides with legacy ${legacy}`);
  }
  // Correlation key shape is load-bearing for dismissal lookups.
  assert.equal(nfl.correlationKey({ team: 'NE' }, 'receiving_yards'), 'NE::receiving_yards');
});

test('NFL adapter: market hooks reproduce pre-adapter value branches exactly', () => {
  const { sandbox } = buildSandbox();
  const reg = loadRegistry(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nfl.js'), 'utf8'), sandbox, { filename: 'nfl.js' });
  const nfl = reg.require('nfl');
  nfl.bindContext({
    num: (v, f = 0) => (Number.isFinite(Number(v)) ? Number(v) : f),
    pct: (v, d = 1) => `${((Number.isFinite(Number(v)) ? Number(v) : 0) * 100).toFixed(d)}%`,
    esc: (v) => String(v ?? ''),
    SVG_ICONS: { target: 'T', surge: 'S', alpha: 'A', air: 'AIR', adot: 'AD', depth: 'D', volume: 'V', starter: 'ST' },
  });

  const row = {
    fair_line_yards: 43.5, proj_yards: 30.6, receiving_yards: 51,
    fair_line_rec: 3.5, proj_rec: 2.6, mu_rec: 2.66, receptions: 4,
    f_tgt_share: 0.105, target_share: 0.136, c_targets: 6.8,
    f_ay_share: 0.145, air_yards_share: 0.2, f_adot: 8.6, adot: 11.1,
  };
  const y = nfl.markets.receiving_yards;
  const r = nfl.markets.receptions;
  const t = nfl.markets.anytime_td;

  assert.equal(y.fair(row), 43.5);
  assert.equal(y.projection(row), 30.6);
  assert.equal(y.actual(row), 51);
  assert.equal(r.fair(row), 3.5);
  assert.equal(r.fairProbText(row), 'P(over fair) 0.0%'); // p_rec_at_fair_line absent → num fallback 0
  // f_tgt_share (0.105) wins over target_share (0.136) per the legacy `||` chain.
  assert.equal(t.fair(row), Math.round(0.105 * 2.2 * 10) / 10);
  assert.equal(t.projection(row), Math.round(0.105 * 2.4 * 10) / 10);
  assert.equal(t.settledActual(row), 4); // legacy quirk: anytime_td settles against receptions
  assert.equal(t.fairProbText(row), 'Poisson Red Zone Model (Holdout)');

  const distY = y.dist(row);
  assert.equal(distY.low, Math.max(0, Math.round(43.5 * 0.58)));
  assert.equal(distY.high, Math.round(30.6 * 1.48));
  const distR = r.dist(row);
  assert.equal(distR.isRec, true);
  const distT = t.dist(row);
  assert.equal(distT.isTd, true);

  // Breaker fallbacks equal the calibrated NFL values (never reuse elsewhere).
  assert.equal(y.breaker.driftHurdle, 5.0);
  assert.equal(y.breaker.beneficiaryMax, 8.5);
  assert.equal(r.breaker.driftHurdle, 1.0);
  assert.equal(r.breaker.beneficiaryMax, 2.0);
  assert.equal(t.breaker.driftHurdle, 1.0); // legacy: anytime_td inherited reception scale
});
