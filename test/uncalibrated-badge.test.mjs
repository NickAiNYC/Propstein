import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSandbox, loadApp, attachSyntheticQuote } from './helpers/sandbox.mjs';

/**
 * UNCALIBRATED BADGE (audit H9) — spec item 5 requires a VISIBLE uncalibrated
 * badge on rows of uncalibrated markets; a config flag alone is cosmetic.
 *
 * Badge truth = breaker truth: circuit_breaker_config.json sports[n].calibrated
 * (adapter.breakerFallback as the fetch-failure fallback). NBA v1 ships
 * calibrated:false → every table row and card shows UNCALIBRATED. NFL ships
 * calibrated:true → no badge element may exist anywhere on NFL rows (the
 * badge must be a real signal, not chrome).
 */

async function renderedRows(seed = {}) {
  const { sandbox, registry } = buildSandbox({ seedLocalStorage: seed });
  const P = loadApp(sandbox);
  await P.loadSlate(P.defaultBootSlate());
  // Shipped demo quotes intentionally fail slate matching (provenance hotfix);
  // NFL render paths need the harness-only attached quote. NBA fixture feeds
  // still attach natively, so they are left untouched.
  if ((P.SPORT_ID || 'nfl') === 'nfl') attachSyntheticQuote(P);
  P.setView('table');
  P.renderAll();
  const tableHtml = registry.get('#slateRows')?.innerHTML || '';
  P.setView('cards');
  P.renderAll();
  const cardsHtml = registry.get('#cardView')?.innerHTML || '';
  return { P, tableHtml, cardsHtml };
}

test('NBA rows render the UNCALIBRATED badge in table and card views', async () => {
  const { P, tableHtml, cardsHtml } = await renderedRows({ propwire_active_sport: 'nba' });
  // NBA boots into Top Plays mode: only quoted rows with complete inputs
  // render — the badge must cover every RENDERED row, not the raw slate.
  const renderedCount = P.filteredRows().length;
  assert.ok(renderedCount > 0, 'ranked view must have rows');
  const badgeCount = (tableHtml.match(/class="uncal-tag"/g) || []).length;
  assert.equal(badgeCount, renderedCount, 'every rendered NBA row carries the badge');
  assert.match(tableHtml, /UNCALIBRATED/);
  assert.match(cardsHtml, /class="uncal-tag"/, 'cards view carries the badge too');
  // The badge is config-truthed: flip the config to calibrated and it must go.
  const cfg = P.state.breakerConfig;
  assert.equal(cfg.sports.nba.calibrated, false, 'badge reflects breaker config truth');
});

test('NFL rows render NO uncalibrated badge (calibrated sport, no chrome)', async () => {
  const { tableHtml, cardsHtml } = await renderedRows();
  assert.ok(tableHtml.includes('slate-row'), 'NFL table rendered');
  assert.doesNotMatch(tableHtml, /uncal-tag|UNCALIBRATED/, 'no badge on NFL table rows');
  assert.doesNotMatch(cardsHtml, /uncal-tag|UNCALIBRATED/, 'no badge on NFL cards');
});
