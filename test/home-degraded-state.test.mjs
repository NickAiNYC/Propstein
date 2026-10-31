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
  assert.match(status, /Live qualification paused/);
  assert.equal((cards.match(/class="home-edge-card home-research-card"/g) || []).length, 5);
  assert.match(cards, /MODEL FAIR · NO LIVE PRICE/);
  assert.match(cards, /no current edge or stake is available/);
  assert.doesNotMatch(cards, /Top 5 plays|verified edge/i);
});
