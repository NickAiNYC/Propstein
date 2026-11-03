import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

/**
 * TOP PLAYS RANKING — Phase 2, commit 4 (revised by the Phase 2 audit, H5).
 *
 * EV-ranked Top Plays mode (adapter-driven). Order contract (audit-revised):
 * EV per unit staked desc → probability edge desc → MODEL CONFIDENCE
 * (narrower adapter distribution interval first — receipt coverage is a
 * data-availability signal, not a quality signal, so "verified" no longer
 * ranks plays) → sample size (games_prior desc, neutral when absent) →
 * player name asc. Rows without a bookable quote in the active market, or
 * with incomplete projection inputs, are hidden.
 *
 * The fixture feed carries REAL player names (owner decision 2026-10-27,
 * see docs/MULTISPORT.md §2). Deterministic ties are engineered in-test so
 * the full tie-break chain stays pinned regardless of file content:
 * equal EV + edge with different model interval widths → confidence decides.
 */

async function loadNba() {
  const { sandbox } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const P = loadApp(sandbox);
  await P.loadSlate(P.defaultBootSlate());
  P.setPlayMode('top');
  return P;
}

test('Top Plays: EV per unit descending within the active market', async () => {
  const P = await loadNba();
  P.state.filters.market = 'points';
  const names = P.filteredRows().map((r) => r.player_display_name);
  // points quotes on the opener night: Jaylen Brown .195, Jalen Brunson .191,
  // Nikola Jokic .191, Shai Gilgeous-Alexander .156 — every other player lacks
  // a points quote. Brunson/Jokic share EV AND edge, share interval width
  // (identical mu/sd profiles), so the name tie-break orders them.
  assert.deepEqual(names, [
    'Jaylen Brown',
    'Jalen Brunson',
    'Nikola Jokic',
    'Shai Gilgeous-Alexander',
  ]);
});

test('Top Plays: model confidence (narrower interval) breaks EV and edge ties', async () => {
  const P = await loadNba();
  P.state.filters.market = 'rebounds';
  // Engineer the full EV+edge tie on the only two rebound quotes: Jamal
  // Murray (EV .402, edge .072, interval width 2) vs Karl-Anthony Towns
  // (narrowed via sd_reb 0.6 → width 1). Towns sorts LATER by name, so the
  // confidence tie-break — not the name — must put Towns first.
  const townsQuote = P.state.odds.quotes.find((q) => q.player_id === 'fx-nba-karl-anthony-towns');
  const murrayQuote = P.state.odds.quotes.find((q) => q.player_id === 'fx-nba-jamal-murray');
  assert.ok(townsQuote && murrayQuote, 'both rebound quotes exist on the opener night');
  townsQuote.evaluation.expected_return = murrayQuote.evaluation.expected_return;
  townsQuote.evaluation.prob_edge = murrayQuote.evaluation.prob_edge;
  const townsRow = P.state.slate.find((r) => r.player_id === 'fx-nba-karl-anthony-towns');
  townsRow.sd_reb = 0.6;
  const names = P.filteredRows().map((r) => r.player_display_name);
  assert.deepEqual(names, [
    'Karl-Anthony Towns', // width 1 beats width 2 on the confidence tie-break
    'Jamal Murray',
  ]);
});

test('Top Plays: incomplete projection inputs are hidden even when quoted', async () => {
  const P = await loadNba();
  // The deliberate probe row has points/pra inputs = null. Give it a quote
  // so ONLY the input gate can exclude it (a missing quote would trivially
  // hide it), then confirm both the ranked list and adapter gate agree.
  P.state.odds.quotes.push({
    quote_id: 'fixture_probe_two_way',
    provider_quote_id: 'fixture_probe_two_way',
    book: 'PropWire Fixture',
    player_id: 'fx-nba-two_way_callup',
    player_name: 'Two-Way Callup',
    team: 'NYK', opponent: 'BOS',
    game_id: 'nba-20261022-BOS-NYK',
    position: 'SG', market: 'points',
    line: 4.5, fair_line: 4.0, over_odds: -110, under_odds: -110,
    observed_at: '2026-10-22T17:00:00Z',
    source: 'PropWire synthetic fixture (not a sportsbook quote; unverified research data)',
    verified: false, _fixture: true,
    evaluation: { is_qualified: false, status: 'UNVERIFIED', best_side: 'OVER', prob_edge: 0.5, break_even_adv: 0.4, expected_return: 0.9, actionable_stake: 0, catalyst: 'none', injury_context: 'none (fixture)' },
  });
  P.state.filters.market = 'points';
  const names = P.filteredRows().map((r) => r.player_display_name);
  assert.ok(!names.includes('Two-Way Callup'), 'incomplete-input row hidden from ranked view despite huge EV');
  const probe = P.state.slate.find((r) => r.player_id === 'fx-nba-two_way_callup');
  assert.equal(P.adapter.hasCompleteInputs(probe, 'points'), false);
});

test('Top Plays: sample size and name decide after confidence; verified flag is ignored', async () => {
  const P = await loadNba();
  P.state.filters.market = 'points';
  const brownQuote = P.state.odds.quotes.find((q) => q.player_id === 'fx-nba-jaylen-brown');
  const jokicQuote = P.state.odds.quotes.find((q) => q.player_id === 'fx-nba-nikola-jokic');
  const brownRow = P.state.slate.find((r) => r.player_id === 'fx-nba-jaylen-brown');
  const jokicRow = P.state.slate.find((r) => r.player_id === 'fx-nba-nikola-jokic');
  // Force a full EV+edge+confidence tie: Jokic width 13 (mu 28.5/sd 6.8)
  // → narrow sd to 6.1 so the interval width equals Brown's 11.
  jokicQuote.evaluation.expected_return = brownQuote.evaluation.expected_return;
  jokicQuote.evaluation.prob_edge = brownQuote.evaluation.prob_edge;
  jokicRow.sd_pts = 6.1;
  const pairOrder = () => P.filteredRows()
    .map((r) => r.player_display_name)
    .filter((n) => n === 'Jaylen Brown' || n === 'Nikola Jokic');

  // Equal confidence, no sample info → name decides (Brown < Jokic).
  assert.deepEqual(pairOrder(), ['Jaylen Brown', 'Nikola Jokic']);

  // Sample size decides: more prior games ranks first.
  brownRow.games_prior = 12;
  jokicRow.games_prior = 5;
  assert.deepEqual(pairOrder(), ['Jaylen Brown', 'Nikola Jokic']);

  // "verified" is a data-availability flag, not a quality signal: marking
  // the losing side verified must NOT reorder the ranking (audit H5).
  jokicQuote.verified = true;
  jokicQuote.receipt_id = 'deadbeefcafebabe';
  assert.deepEqual(pairOrder(), ['Jaylen Brown', 'Nikola Jokic'],
    'a verified receipt must never outrank an equally supported play');
});

test('NFL Top Plays keeps the picks-file behavior (verbatim, parity-guarded)', async () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');
  P.setPlayMode('top');
  const topList = (P.state.picks && P.state.picks.top_projections) || [];
  assert.ok(topList.length > 0, 'W7 picks file carries top_projections');
  const rows = P.filteredRows();
  const listNames = topList.map((p) => String(p.player).toLowerCase());
  for (const row of rows) {
    assert.ok(listNames.includes(String(row.player_display_name).toLowerCase()),
      `${row.player_display_name} must come from picks.top_projections`);
  }
  assert.equal(rows.length, new Set(listNames).size, 'all and only the picks-file names render');
});
