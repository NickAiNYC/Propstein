import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { buildSandbox, loadApp, VIEWER } from './helpers/sandbox.mjs';

/**
 * NBA AVAILABILITY / INJURIES WIRING — completes the NBA section.
 *
 * The generic app machinery (availability pill, drawer cards, surge intent,
 * minutes-vacancy driver badges) was NFL-only in practice because the NBA
 * adapter shipped `injuries: null`. These tests pin the full NBA path:
 *
 *  1. the availability feed loads and renders on the fixture slates;
 *  2. beneficiaries drive the Surge intent filter and driver badges;
 *  3. minutes-based quant impact renders through the adapter label (the
 *     app.js gate must accept `vacated_minutes`, not just NFL `vacated_targets`);
 *  4. the injury drawer receipt pill is dynamic — the stale hardcoded
 *     "64/64" string is banned at source level;
 *  5. the slate selector never renders "Wundefined" for week-less slates;
 *  6. the Oct 23 full night boots with game-filter joins intact.
 */

function attachLocalDom(sandbox) {
  const els = new Map();
  sandbox.document.getElementById = (id) => {
    if (!els.has(id)) {
      els.set(id, {
        id, innerHTML: '', textContent: '', hidden: true, className: '',
        dataset: {}, style: { cssText: '' },
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        addEventListener() {}, removeEventListener() {},
      });
    }
    return els.get(id);
  };
  return els;
}

function bootNba({ slateKey } = {}) {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const els = attachLocalDom(sandbox);
  const P = loadApp(sandbox);
  return { sandbox, els, P, ready: P.loadSlate(slateKey || P.defaultBootSlate()) };
}

test('NBA availability feed loads and renders the alert pill + drawer data (Oct 22 opener)', async () => {
  const { sandbox, P, ready } = bootNba();
  await ready;

  assert.equal(P.state.injuries.injuries.length, 2, 'availability items loaded');
  assert.equal(Object.keys(P.state.injuries.impacted_beneficiaries).length, 2, 'beneficiary map loaded');

  P.renderAll();
  // renderInjuries writes through $() (querySelector), not getElementById —
  // read the same channel the app writes to.
  const count = sandbox.document.querySelector('#injuryAlertCount');
  assert.ok(count, 'availability pill element resolved');
  assert.equal(count.textContent, '2 Injury Alerts');
  const preview = sandbox.document.querySelector('#injuryAlertPreview');
  assert.match(preview.textContent, /OUT/, 'preview names the OUT status');
});

test('Surge intent filters to modeled beneficiaries and driver badge shows added minutes', async () => {
  const { P, ready } = bootNba();
  await ready;

  const beneficiaries = P.state.injuries.impacted_beneficiaries;
  P.state.filters.intent = 'surge';
  P.state.filters.playMode = 'all';
  const surgeRows = P.filteredRows();
  assert.ok(surgeRows.length >= 1, 'surge intent has rows on the fixture slate');
  for (const row of surgeRows) {
    assert.ok(beneficiaries[row.player_id], `surge row ${row.player_id} is a modeled beneficiary`);
  }

  const bene = Object.values(beneficiaries).find((b) => Number(b.added_minutes) > 0);
  const row = P.state.slate.find((r) => r.player_id === bene.player_id);
  const badge = P.adapter.driverTag(row, bene);
  assert.match(badge, /Surge \(\+\d+ min\)/, 'driver badge carries the minutes vacancy');
  assert.match(badge, new RegExp(bene.catalyst_injury.split(' ')[0].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), 'badge tooltip cites the catalyst');
});

test('minutes-vacated injuries render adapter quant impact (vacated_minutes gate)', async () => {
  const { P, ready } = bootNba();
  await ready;

  const item = P.state.injuries.injuries.find((i) => i.report_status === 'OUT');
  assert.ok(item, 'an OUT item exists');
  // The adapter label owns the unit wording for minutes-based vacation.
  const text = P.adapter.labels.injuredQuantImpact.vacated(item);
  assert.match(text, /Vacates \d+(\.\d+)? min\/g/);
  assert.match(text, /\d+% usage/);

  // Source-level pin: the app.js gate must accept vacated_minutes, or every
  // NBA item silently degrades to the generic "Priced In" fallback.
  const src = fs.readFileSync(path.join(VIEWER, 'app.js'), 'utf8');
  assert.ok(
    /item\.vacated_targets \|\| item\.vacated_minutes/.test(src),
    'quant impact gate must include vacated_minutes (NBA semantics)'
  );
});

test('injury drawer receipt pill is dynamic — stale 64/64 hardcode is banned', async () => {
  const src = fs.readFileSync(path.join(VIEWER, 'app.js'), 'utf8');
  assert.ok(!src.includes('64/64'), 'app.js must not carry the stale hardcoded receipt count');
  assert.ok(src.includes('receiptPillText'), 'drawer pill must render the dynamic count');
  assert.ok(
    /quoteState\(quote\) === 'verified'/.test(src),
    'drawer pill derives from the same verified-quote computation as the header'
  );
});

test('slate selector renders shortLabels; no Wundefined, no doubled Fixture suffix', async () => {
  const { els, P, ready } = bootNba();
  await ready;

  P.renderSportChrome();
  const selector = els.get('slateSelector');
  assert.ok(selector, 'slate selector resolved');
  assert.match(selector.innerHTML, /Oct 22 Fixture/, 'Oct 22 option uses its shortLabel');
  assert.match(selector.innerHTML, /Oct 23 Fixture/, 'Oct 23 option uses its shortLabel');
  assert.ok(!selector.innerHTML.includes('Fixture slate ·'), 'no long state text in options');
  assert.ok(!selector.innerHTML.includes('Wundefined'), 'no Wundefined leakage');
  assert.ok(!selector.innerHTML.includes('Fixture Fixture'), 'no doubled Fixture suffix');

  // Source-level pins: options build from shortLabel; the feed-status suffix
  // only applies to week-based (live) slates; no bare W${week} construction.
  const src = fs.readFileSync(path.join(VIEWER, 'app.js'), 'utf8');
  assert.ok(src.includes('slate.shortLabel || slate.state || key'), 'slateOptions prefers shortLabel');
  assert.ok(
    !/const slateLabel = `W\$\{SLATES\[state\.slateKey\]\.week\}`/.test(src),
    'bare W${week} construction must stay replaced'
  );
  assert.ok(/if \(slateCfg\.week != null\)/.test(src), 'suffix gated to week-based slates');
  assert.equal(P.feedVerificationLabel(), 'FIXTURE', 'fixture labeling unchanged');
});

test('Oct 23 full night boots: 10 games, 70 rows, availability data, game filter joins', async () => {
  const { P, ready } = bootNba({ slateKey: '2026-10-23' });
  await ready;

  assert.equal(P.state.slate.length, 140, 'full-night modeled rows');
  assert.equal(P.state.games.length, 10, 'full-night games');
  assert.equal(P.state.injuries.injuries.length, 3, 'full-night availability items');

  // Regression for the Oct 22 game_id convention bug: every slate row must
  // join the games feed, so the per-game filter can never silently empty.
  const gameIds = new Set(P.state.games.map((g) => g.game_id));
  for (const row of P.state.slate) {
    assert.ok(gameIds.has(row.game_id), `row ${row.player_id} game_id joins the games feed`);
  }

  P.state.filters.gameId = 'nba-20261023-MIL-CLE';
  P.state.filters.playMode = 'all';
  const inGame = P.filteredRows();
  assert.ok(inGame.length >= 5, 'per-game filter returns that game’s players');
  assert.ok(inGame.every((r) => r.game_id === 'nba-20261023-MIL-CLE'));

  // EV-ranked Top Plays works on the larger quote set.
  P.state.filters.gameId = '';
  P.state.filters.playMode = 'top';
  const top = P.filteredRows();
  assert.ok(top.length >= 5, 'EV-ranked Top Plays populated from fixture quotes');
  const evs = top.map((r) => {
    const q = P.evaluateRow(r);
    return q.ev;
  });
  for (let i = 1; i < evs.length; i += 1) {
    assert.ok(Number(evs[i - 1]) >= Number(evs[i]) - 1e-9, 'Top Plays stay EV-descending');
  }
});
