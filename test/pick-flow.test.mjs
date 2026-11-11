import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

test('line picker uses the published NegBin-Gamma fit and states when no verified book exists', async () => {
  const { sandbox } = buildSandbox();
  const app = loadApp(sandbox);
  await app.loadSlate('2026_w7');
  const row = app.state.slate.find((item) => Number.isFinite(Number(item.mu_rec)) && Number.isFinite(Number(item.mu_ypr)) && Number.isFinite(Number(item.fair_line_yards)));
  assert.ok(row, 'week 7 slate has a priced receiver');
  const atFair = app.priceLine(row, 'receiving_yards', Number(row.fair_line_yards));
  const above = app.priceLine(row, 'receiving_yards', Number(row.fair_line_yards) + 20);
  assert.ok(atFair.pOver > 0.2 && atFair.pOver < 0.8, atFair.pOver);
  assert.ok(above.pOver < atFair.pOver, 'a higher line has a lower over probability');
  assert.ok(Math.abs(atFair.pOver + atFair.pUnder - 1) < 1e-9);
  const receptions = app.priceLine(row, 'receptions', Number(row.fair_line_rec));
  assert.ok(receptions.pOver > 0 && receptions.pOver < 1);
  assert.equal(app.priceLine(row, 'anytime_td', 0.5), null);
  assert.equal(app.resolveDataKind(app.state.slate, { feed_status: 'fixture' }), 'live');
  assert.equal(app.resolveDataKind([{ _fixture: true, proj_pts: 10 }], { feed_status: 'fixture' }), 'fixture');
  assert.equal(app.quoteIsSynthetic({ book: 'Synthetic Book A', source: 'demonstration fixture' }), true);
  assert.equal(app.quoteIsSynthetic({ book: 'DraftKings', verified: true }), false);
});
