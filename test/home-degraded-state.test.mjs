import assert from 'node:assert/strict';
import test from 'node:test';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

test('stale homepage shows fair-line research when observed lines are unavailable', async () => {
  const { sandbox, registry } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const app = loadApp(sandbox);
  await app.loadSlate(app.defaultBootSlate());
  app.state.livePicks = { picks: [] };
  app.renderHomeEdgePreview();

  const title = registry.get('#homeEdgeTitle').textContent;
  const status = registry.get('#homeEdgeStatus').textContent;
  const cards = registry.get('#homeEdgeList').innerHTML;
  assert.equal(title, 'Model fair lines');
  assert.match(status, /No verified plays/);
  assert.equal((cards.match(/class="home-edge-card home-research-card"/g) || []).length, 5);
  assert.match(cards, /MODEL FAIR · NO LIVE PRICE/);
  assert.match(cards, /no current edge or stake is available/);
  assert.doesNotMatch(cards, /Top 5 plays|verified edge/i);
  assert.match(registry.get('#homeEdgeFallbackText').textContent, /Displaying last quantitative model baseline/);
});

test('unverified observed lines render ranked model deltas without edge claims', async () => {
  const { sandbox, registry } = buildSandbox();
  const app = loadApp(sandbox);
  await app.loadSlate('2026_w7');
  app.state.livePicks = { picks: [
    { player: 'Player Alpha', market: 'receiving_yards', side: 'over', projection: 72.5, line: 61.5, odds: 110, edge: 0.18, book: 'draftkings' },
    { player: 'Player Beta', market: 'receptions', side: 'under', projection: 3.1, line: 4.5, odds: -105, edge: 0.12, book: 'betmgm' }
  ] };
  app.renderBoard();

  assert.equal(registry.get('#topModelStrip').hidden, false);
  assert.equal(registry.get('#topModelStripTitle').textContent, 'TOP MODEL DELTAS (N=2)');
  assert.equal(registry.get('#topModelStripState').textContent, 'UNVERIFIED SNAPSHOT');
  assert.match(registry.get('#topModelStripNote').textContent, /not live recommendations/i);
  const cards = registry.get('#topModelStripGrid').innerHTML;
  assert.match(cards, /MODEL Δ/);
  assert.doesNotMatch(cards, />EDGE</);
  assert.doesNotMatch(cards, /verified/);
});
