import assert from 'node:assert/strict';
import test from 'node:test';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

test('settings distinguish CLOB quotes from the Odds API research scan', async () => {
  const { sandbox, registry } = buildSandbox();
  const app = loadApp(sandbox);
  await app.loadSlate(app.defaultBootSlate());
  app.state.odds = { feed_status: 'LIVE_POLYMARKET_CLOB_UNVERIFIED', quotes: [
    { book: 'Polymarket', market: 'receiving_yards' }
  ] };
  app.state.livePicks = { source: 'The Odds API', picks: [{ player: 'Player A' }] };
  app.state.feedHealth = { dataKind: 'live', odds: 'ok', news: 'error', oddsUpdatedAt: '2026-10-22T11:59:00Z' };
  app.updateFeedVerificationUI();

  assert.equal(registry.get('#settingsFeedProvider').textContent, 'Polymarket CLOB');
  assert.equal(registry.get('#settingsResearchSource').textContent, 'The Odds API');
  assert.match(registry.get('#settingsReceiptsStatus').textContent, /0 feed-verified quotes/);
  assert.match(registry.get('#settingsQualificationStatus').textContent, /independent quote audit/);
});

test('sportsbook gap view excludes Polymarket and research fixtures', async () => {
  const { sandbox } = buildSandbox();
  const app = loadApp(sandbox);
  await app.loadSlate(app.defaultBootSlate());
  const row = app.state.slate[0];
  app.state.filters.market = 'receiving_yards';
  const base = { player_id: row.player_id, market: 'receiving_yards', observed_at: '2026-10-22T11:59:00Z' };
  app.state.odds.quotes = [
    { ...base, book: 'Polymarket', line: 74.5 },
    { ...base, book: 'Synthetic Book A', line: 80.5 },
    { ...base, book: 'DraftKings', line: 79.5 }
  ];
  assert.equal(app.detectBookDiscrepancy(row), null);
  app.state.odds.quotes.push({ ...base, book: 'FanDuel', line: 80.5 });
  assert.equal(app.detectBookDiscrepancy(row).diff, '1.0');
});
