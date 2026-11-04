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
  assert.equal((cards.match(/class="home-edge-card home-research-card"/g) || []).length, 8);
  assert.match(cards, /MODEL FAIR · NO LIVE PRICE/);
  assert.match(cards, /no current edge or stake is available/);
  assert.doesNotMatch(cards, /Top 5 plays|verified edge/i);
  assert.equal(registry.get('#homeEdgeFallback').hidden, true);
});

test('NFL research preview ranks and limits the daily model signals to eight', async () => {
  const { sandbox, registry } = buildSandbox();
  const app = loadApp(sandbox);
  await app.loadSlate(app.defaultBootSlate());
  app.state.livePicks = {
    picks: Array.from({ length: 10 }, (_, index) => ({
      player: `Player ${index + 1}`,
      market: 'receiving_yards',
      side: 'over',
      line: 40.5 + index,
      odds: -110,
      book: 'draftkings',
      edge: (index + 1) / 100,
      ev_per_unit: (index + 1) / 10,
    })),
  };
  app.renderHomeEdgePreview();

  const cards = registry.get('#homeEdgeList').innerHTML;
  assert.equal(registry.get('#homeEdgeTitle').textContent, 'Top 8 model signals');
  assert.equal((cards.match(/class="home-edge-card home-research-card"/g) || []).length, 8);
  assert.ok(cards.indexOf('Player 10') < cards.indexOf('Player 9'));
  assert.doesNotMatch(cards, /Player 2<|Player 1</);
  assert.match(registry.get('#homeEdgeStatus').textContent, /8 of 10 model-ranked research lines/);
  assert.equal(registry.get('#homeEdgeFallback').hidden, true);
});
