import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { buildSandbox, loadApp, VIEWER } from './helpers/sandbox.mjs';

test('NBA player drawer uses NBA units and only available telemetry', async () => {
  const { sandbox, registry } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const app = loadApp(sandbox);
  await app.loadSlate('2026-10-29');
  const luka = app.state.slate.find((row) => row.player_display_name === 'Luka Doncic');
  app.renderDetailModal(luka);
  const drawer = registry.get('#detailContent').innerHTML;
  assert.match(drawer, /Usage rate/);
  assert.match(drawer, /Projected minutes/);
  assert.match(drawer, /True shooting/);
  assert.match(drawer, /Not available/);
  assert.match(drawer, /pts vs offer/);
  assert.doesNotMatch(drawer, /Target share|Air-yards share|Yards \/ reception|yds vs offer|kickoff|Snap risk/i);
  assert.doesNotMatch(drawer, /detail-verdict-card|Fair-Line Specification/);
  assert.doesNotMatch(drawer, /a054819c1cfb8fb0|Receipt-Verified|API \(Fresh\)/);
  assert.match(drawer, /No verified receipt/);
  assert.match(registry.get('#detailSummary').textContent, /31\.1 pts/);
});

test('NBA market-only date shows real unverified lines without model or edge claims', () => {
  const { sandbox, registry } = buildSandbox({ seedLocalStorage: { propwire_active_sport: 'nba' } });
  const app = loadApp(sandbox);
  app.SLATES['2026-10-31'] = { marketOnly: true, historical: false };
  app.state.slateKey = '2026-10-31';
  app.state.slate = [];
  app.state.games = [{ game_id: 'nba-20261031-PHI-CHA', away_team: 'PHI', home_team: 'CHA' }];
  app.state.odds = {
    feed_status: 'live-unverified', updated_at: '2026-10-31T15:00:00Z',
    quotes: [{ player_name: 'Test Player', game_id: 'nba-20261031-PHI-CHA', book: 'Book A',
      market: 'points', line: 24.5, over_odds: -110, under_odds: 100, _fixture: false, verified: false }]
  };
  app.renderBoard();
  const markup = registry.get('#emptyState').innerHTML;
  assert.match(markup, /Test Player/);
  assert.match(markup, /OVER 24\.5/);
  assert.match(markup, /UNDER 24\.5/);
  assert.match(markup, /UNVERIFIED/);
  assert.match(markup, /No NBA model predictions or qualified edges/);
  assert.doesNotMatch(markup, /model fair|probability edge|expected value/i);
});

/**
 * NBA INTEGRATION TESTS — Phase 2, commit 1 (adapter + fixture feeds).
 *
 * Covers: adapter contract, market hooks on fixture rows, fixture feed
 * schema + provenance, Eastern-time slate keying (DST boundaries), the
 * uncalibrated NBA breaker block, and copy compliance on every new
 * user-facing string introduced by the NBA surface.
 */

function loadSports(sandbox) {
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'registry.js'), 'utf8'), sandbox, { filename: 'registry.js' });
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nfl.js'), 'utf8'), sandbox, { filename: 'nfl.js' });
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nba.js'), 'utf8'), sandbox, { filename: 'nba.js' });
  return sandbox.window.PropWireSports;
}

function loadNba() {
  const { sandbox } = buildSandbox();
  const reg = loadSports(sandbox);
  const nba = reg.require('nba');
  nba.bindContext({
    num: (v, f = 0) => (Number.isFinite(Number(v)) ? Number(v) : f),
    pct: (v, d = 1) => `${((Number.isFinite(Number(v)) ? Number(v) : 0) * 100).toFixed(d)}%`,
    esc: (v) => String(v ?? ''),
    SVG_ICONS: { target: 'T', surge: 'S', alpha: 'A', air: 'AIR', adot: 'AD', depth: 'D', volume: 'V', starter: 'ST' },
  });
  return nba;
}

const FIXTURE_DATE = '2026-10-22';
const readViewerJson = (name) => JSON.parse(fs.readFileSync(path.join(VIEWER, name), 'utf8'));

test('NBA adapter: contract complete, markets cover marketOrder, storage keys namespaced', () => {
  const nba = loadNba();
  assert.equal(nba.id, 'nba');
  assert.equal(nba.periodNoun, 'Slate');
  assert.deepEqual(JSON.parse(JSON.stringify(nba.marketOrder)), ['points', 'rebounds', 'assists', 'threes', 'pra']);
  for (const id of nba.marketOrder) {
    const m = nba.markets[id];
    assert.ok(m, `market ${id} missing`);
    for (const field of ['fair', 'projection', 'actual', 'settledActual', 'settledLine', 'dist', 'prediction', 'fairProbText']) {
      assert.equal(typeof m[field], 'function', `market ${id} missing hook ${field}`);
    }
    assert.ok(m.breaker && Number.isFinite(m.breaker.driftHurdle));
  }
  assert.deepEqual(JSON.parse(JSON.stringify(nba.positions)), ['PG', 'SG', 'SF', 'PF', 'C']);

  // Shared ledger key + per-sport namespaces; NBA must NOT touch NFL keys.
  for (const key of Object.values(nba.storageKeys)) {
    if (key === 'propwire_portfolio_ledger_v2') continue;
    assert.ok(key.includes('nba'), `storage key ${key} must be sport-namespaced`);
    assert.ok(!key.includes('nfl'), `storage key ${key} must not collide with NFL naming`);
  }
  assert.deepEqual(JSON.parse(JSON.stringify(Object.keys(nba.legacyKeys))), [], 'NBA ships no legacy keys');
  assert.equal(nba.correlationKey({ team: 'DEN' }, 'points'), 'DEN::points');

  // Two fixture nights registered; the Oct 22 opener stays the boot default
  // (registration order IS the selector order — pinned so reordering the
  // registry can never silently move the default slate).
  assert.deepEqual(Object.keys(nba.slates), ['2026-10-22', '2026-10-23', '2026-10-29']);
  for (const slate of Object.values(nba.slates)) {
    assert.match(slate.injuries, /^nba_injuries_\d{4}-\d{2}-\d{2}\.json$/, 'availability feed wired per slate');
    assert.equal(slate.picks, null);
    assert.equal(slate.snapshots, null);
  }
  assert.equal(nba.defaultSlateKey(), '2026-10-22');

  // v1 is fixture-only and breaker values are uncalibrated by contract.
  assert.equal(nba.fixturesOnly, false, 'real market-only dates must not be mislabeled fixtures');
  assert.match(nba.fixtureNotice, /Research fixtures/);
  assert.match(nba.fixtureNotice, /Not sportsbook quotes/);
  assert.equal(nba.breakerFallback.calibrated, false);
  assert.equal(nba.topPlays.source, 'ev_ranked');
});

test('NBA adapter: market hooks resolve fixture-row fields per market', () => {
  const nba = loadNba();
  const row = {
    fair_line_pts: 27.4, proj_pts: 27.5, mu_pts: 27.5, sd_pts: 6.4, pts: 31,
    fair_line_reb: 8.1, proj_reb: 8.2, mu_reb: 8.2, sd_reb: 2.1, rebounds: 8,
    fair_line_ast: 5.0, proj_ast: 5.0, mu_ast: 5.0, sd_ast: 1.7, assists: 6,
    fair_line_fg3m: 3.2, proj_fg3m: 3.3, mu_fg3m: 3.3, sd_fg3m: 1.3, fg3m: 4,
    fair_line_pra: 40.3, proj_pra: 40.7, mu_pra: 40.7, sd_pra: 6.9,
    usage_rate: 0.315, minutes: 36.0, position: 'SF',
  };
  const pts = nba.markets.points;
  assert.equal(pts.fair(row), 27.4);
  assert.equal(pts.projection(row), 27.5);
  assert.equal(pts.actual(row), 31);
  assert.equal(pts.fairProbText(row), 'P(over fair) 50.0%');
  const d = pts.dist(row);
  assert.equal(d.low, Math.max(0, Math.round(27.5 - 0.9 * 6.4)));
  assert.equal(d.high, Math.round(27.5 + 0.9 * 6.4));
  assert.match(pts.prediction(row), /80% Range: \d+ – \d+ pts/);

  // pra actual is the pts+reb+ast compound.
  assert.equal(nba.markets.pra.actual(row), 45);
  assert.match(nba.markets.threes.prediction(row), /3pm$/);
  assert.match(nba.markets.rebounds.prediction(row), /reb$/);
  assert.match(nba.markets.assists.prediction(row), /ast$/);

  // sd fallbacks: sd_* absent → scale by mu (documented uncalibrated default).
  const noSd = { ...row, sd_pts: undefined };
  assert.equal(pts.sd(noSd), Math.max(1, 27.5 * 0.35));

  // Role/driver tags use usage & minutes (never NFL target-share fields).
  // Badge precedence: usage ≥ 0.32 → Usage; else minutes ≥ 36 → MIN.
  assert.equal(nba.roleLabel(row), 'Primary SF');
  assert.match(nba.roleLabel({ ...row, usage_rate: 0.24, minutes: 30 }), /Rotation/);
  assert.match(nba.driverTag({ ...row, usage_rate: 0.33, minutes: 30 }), /Usage \(33%\)/);
  assert.match(nba.driverTag(row), /36 MIN/);
  assert.match(nba.driverTag({ ...row, usage_rate: 0.25, minutes: 30 }), /Secondary/);
  assert.match(nba.driverTag({ ...row, usage_rate: 0.15, minutes: 12 }), /Bench/);

  // Top Plays data gate: complete row passes; incomplete projection hides.
  assert.equal(nba.hasCompleteInputs(row, 'points'), true);
  const broken = { ...row, fair_line_pts: 0, proj_pts: 0 };
  assert.equal(nba.hasCompleteInputs(broken, 'points'), false);
  // Default sort is the active-market projection.
  assert.equal(nba.sortDefault(row, 'points'), 27.5);
  assert.equal(nba.sortDefault(row, 'rebounds'), 8.2);
});

test('NBA fixture feeds: provenance flags, required schema, ISO-8601 UTC stamps (both nights)', () => {
  for (const FIXTURE_DATE of ['2026-10-22', '2026-10-23']) {
  const slate = readViewerJson(`nba_slate_${FIXTURE_DATE}.json`);
  const games = readViewerJson(`nba_games_${FIXTURE_DATE}.json`);
  const odds = readViewerJson(`nba_odds_${FIXTURE_DATE}.json`);

  // Slate/games stay BARE arrays (viewer loadSlate schema, parity guard).
  assert.ok(Array.isArray(slate) && slate.length >= 24, 'slate must be a non-empty bare array');
  assert.ok(Array.isArray(games) && games.length >= 1, 'games must be a non-empty bare array');
  // Oct 22 is the 2-game opener; Oct 23 is the generated full night.
  assert.equal(games.length, FIXTURE_DATE === '2026-10-22' ? 2 : 10, `${FIXTURE_DATE} game count pinned`);

  const marketFields = {
    points: ['proj_pts', 'fair_line_pts', 'mu_pts', 'sd_pts'],
    rebounds: ['proj_reb', 'fair_line_reb', 'mu_reb', 'sd_reb'],
    assists: ['proj_ast', 'fair_line_ast', 'mu_ast', 'sd_ast'],
    threes: ['proj_fg3m', 'fair_line_fg3m', 'mu_fg3m', 'sd_fg3m'],
    pra: ['proj_pra', 'fair_line_pra', 'mu_pra', 'sd_pra'],
  };
  const ids = new Set();
  for (const row of slate) {
    assert.equal(row._fixture, true, `${row.player_id} must carry _fixture`);
    assert.ok(row.player_id && row.player_display_name && row.team && row.opponent_team && row.game_id);
    assert.ok(nbaMarketOk(row, marketFields), `${row.player_id} market fields`);
    assert.ok(Number.isFinite(Number(row.minutes)) && Number.isFinite(Number(row.usage_rate)));
    ids.add(row.player_id);
  }
  assert.equal(ids.size, slate.length, 'player ids must be unique');
  if (FIXTURE_DATE === '2026-10-22') {
    assert.ok(slate.some((r) => r.player_id === 'fx-nba-two_way_callup'), 'data-gate probe row present');
  } else {
    assert.ok(slate.every((r) => Number.isFinite(Number(r.proj_pts))), 'full-night rows are complete (no probe row)');
  }

  // Game-feed ids and slate-row game_ids must join (away-first convention,
  // mirroring the NFL `2026_07_AWAY_HOME` shape) — a mismatch silently
  // empties the per-game filter (regression: Oct 22 shipped home-first ids).
  const gameIds = new Set(games.map((g) => g.game_id));
  for (const row of slate) {
    assert.ok(gameIds.has(row.game_id), `${row.player_id} game_id ${row.game_id} must exist in the games feed`);
  }

  for (const game of games) {
    assert.equal(game._fixture, true);
    assert.match(game.game_id, /^nba-\d{8}-[A-Z]{2,4}-[A-Z]{2,4}$/);
    assert.match(game.tipoff_utc, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/, 'tipoff must be ISO-8601 UTC');
    assert.match(game.gametime_et, /^\d{2}:\d{2}$/);
  }

  assert.equal(odds.feed_status, 'fixture');
  assert.equal(odds._fixture, true);
  assert.match(odds.fixture_notice, /Not sportsbook quotes/);
  assert.equal(odds.slate, FIXTURE_DATE);
  assert.ok(Array.isArray(odds.quotes) && odds.quotes.length >= 10);
  const quoteIds = new Set();
  for (const quote of odds.quotes) {
    assert.equal(quote._fixture, true, `${quote.quote_id} must carry _fixture`);
    assert.equal(quote.verified, false, 'fixture quotes must never claim verification');
    assert.match(quote.source, /fixture/i);
    assert.match(quote.source, /not a sportsbook quote/i);
    assert.ok(quote.market && quote.line != null && quote.fair_line != null);
    assert.match(quote.observed_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    assert.ok(quote.evaluation && Number.isFinite(quote.evaluation.prob_edge) && Number.isFinite(quote.evaluation.expected_return));
    quoteIds.add(quote.quote_id);
  }
  assert.equal(quoteIds.size, odds.quotes.length, 'quote ids must be unique');
  // Every quoted player exists on the slate (referential integrity).
  for (const quote of odds.quotes) assert.ok(ids.has(quote.player_id), `quote ${quote.quote_id} references unknown player`);

  // Availability feed: provenance + schema + referential integrity.
  const injuries = readViewerJson(`nba_injuries_${FIXTURE_DATE}.json`);
  assert.equal(injuries._fixture, true, 'injuries envelope carries _fixture');
  assert.equal(injuries.slate_date, FIXTURE_DATE);
  assert.equal(injuries.total_active_injuries, injuries.injuries.length);
  assert.ok(injuries.injuries.length >= 1, 'at least one availability item (surge machinery must have data)');
  for (const item of injuries.injuries) {
    assert.equal(item._fixture, true, `${item.injury_id} must carry _fixture`);
    assert.ok(ids.has(item.player_id), `injury ${item.injury_id} references unknown player`);
    assert.ok(['OUT', 'QUESTIONABLE', 'LIMITED', 'DAY-TO-DAY'].includes(item.report_status), `${item.injury_id} status`);
    assert.ok(Number.isFinite(Number(item.vacated_minutes)), 'minutes-vacated semantics (NBA, not NFL targets)');
    for (const bene of Object.values(item.redistribution_plan)) {
      assert.equal(bene._fixture, true);
      assert.ok(Number(bene.added_minutes) > 0, 'redistribution carries added minutes');
    }
  }
  for (const [pid, bene] of Object.entries(injuries.impacted_beneficiaries)) {
    assert.equal(bene._fixture, true, `beneficiary ${pid} must carry _fixture`);
    assert.ok(ids.has(pid), `beneficiary ${pid} references unknown player`);
    assert.equal(bene.player_id, pid);
    assert.ok(Number(bene.added_minutes) > 0);
  }

  function nbaMarketOk(row, fields) {
    for (const list of Object.values(fields)) {
      for (const field of list) {
        if (row[field] === null) continue; // the deliberate incomplete probe row
        assert.ok(Number.isFinite(Number(row[field])), `${field} must be numeric`);
      }
    }
    return true;
  }
  }
});

test('NBA slate keying: US Eastern date, DST boundaries handled', () => {
  const nba = loadNba();
  for (const FIXTURE_DATE of ['2026-10-22', '2026-10-23']) {
  const games = readViewerJson(`nba_games_${FIXTURE_DATE}.json`);
  // The slate key equals the Eastern calendar date of every game tipoff.
  for (const game of games) {
    assert.equal(nba.etDateKey(game.tipoff_utc), FIXTURE_DATE, `${game.game_id} tipoff maps to the slate key in ET`);
  }
  }
  // DST boundaries: EDT (UTC-4) → EST (UTC-5) on 2026-11-01; EST → EDT on 2026-03-08.
  assert.equal(nba.etDateKey('2026-11-01T03:30:00Z'), '2026-10-31', '23:30 EDT Oct 31');
  assert.equal(nba.etDateKey('2026-11-01T05:30:00Z'), '2026-11-01', '01:30 EDT Nov 1 (before fallback)');
  assert.equal(nba.etDateKey('2026-11-01T06:30:00Z'), '2026-11-01', '01:30 EST Nov 1 (after fallback, same date)');
  assert.equal(nba.etDateKey('2026-03-08T06:30:00Z'), '2026-03-08', '01:30 EST Mar 8 (before spring-forward)');
  assert.equal(nba.etDateKey('2026-03-08T07:30:00Z'), '2026-03-08', '03:30 EDT Mar 8 (after spring-forward)');
  assert.equal(nba.etDateKey('not-a-date'), null, 'invalid input maps to null');
  // Cross-midnight PT tips (audit M13): a 10:30pm PT tip is 1:30am ET the
  // NEXT calendar day — the DST vectors above do not catch this case, so it
  // gets explicit vectors in both winter (PST, UTC-8) and summer (PDT, UTC-7).
  assert.equal(nba.etDateKey('2026-01-15T06:30:00Z'), '2026-01-15',
    '10:30pm PST Jan 14 tip = 1:30am ET Jan 15 → slate key is the ET date');
  assert.equal(nba.etDateKey('2026-07-15T05:30:00Z'), '2026-07-15',
    '10:30pm PDT Jul 14 tip = 1:30am ET Jul 15 → slate key is the ET date');
  // defaultSlateKey resolves the first non-historical Eastern-dated slate.
  assert.equal(nba.defaultSlateKey(), FIXTURE_DATE);
});

test('NBA breaker block: uncalibrated, per-market bounds, no NFL value copying', () => {
  const cfg = JSON.parse(fs.readFileSync(path.join(VIEWER, 'circuit_breaker_config.json'), 'utf8'));
  const nba = cfg.sports.nba;
  const nfl = cfg.sports.nfl;
  assert.ok(nba, 'sports.nba block present');
  assert.equal(nba.calibrated, false);
  assert.equal(nba.calibration, 'uncalibrated_tuning_parameters');
  for (const market of ['points', 'rebounds', 'assists', 'threes', 'pra']) {
    const mk = nba.markets[market];
    assert.ok(mk && Number.isFinite(mk.drift_hurdle) && mk.drift_hurdle > 0, `market ${market} drift_hurdle`);
    assert.ok(Number.isFinite(mk.beneficiary_max_drift) && mk.beneficiary_max_drift > 0);
    assert.ok(mk.unit && mk.unit.length > 0);
  }
  // Guard against threshold copying: NBA points drift (3.0) != NFL yards (5.0);
  // every NBA market bound differs from every NFL market bound.
  const nflBounds = Object.values(nfl.markets).map((m) => `${m.drift_hurdle}/${m.beneficiary_max_drift}`);
  for (const mk of Object.values(nba.markets)) {
    assert.ok(!nflBounds.includes(`${mk.drift_hurdle}/${mk.beneficiary_max_drift}`), `NBA ${mk.unit} must not reuse NFL bounds`);
  }
  // Adapter fallback mirrors the config block (resilience path only).
  const nbaAdapter = loadNba();
  assert.equal(nbaAdapter.breakerFallback.drift_pct_hurdle, nba.thresholds.drift_pct_hurdle);
  assert.equal(nbaAdapter.breakerFallback.high_edge_caution_hurdle, nba.thresholds.high_edge_caution_hurdle);
  assert.equal(nbaAdapter.breakerFallback.calibrated, false);
});

test('NBA copy compliance: no banned marketing words on any new NBA surface', () => {
  const banned = /\b(guaranteed|lock|locks|sure thing|banker|free money|can'?t lose|proven winner)\b/i;
  // NOTE: "verified" is checked separately below — the schema field
  // verified:false is compliant (it DENIES verification); only marketing
  // claims are banned.
  const sources = [
    path.join(VIEWER, 'js', 'sports', 'nba.js'),
    path.join(VIEWER, 'nba_slate_2026-10-22.json'),
    path.join(VIEWER, 'nba_games_2026-10-22.json'),
    path.join(VIEWER, 'nba_odds_2026-10-22.json'),
    path.join(VIEWER, 'nba_injuries_2026-10-22.json'),
    path.join(VIEWER, 'nba_slate_2026-10-23.json'),
    path.join(VIEWER, 'nba_games_2026-10-23.json'),
    path.join(VIEWER, 'nba_odds_2026-10-23.json'),
    path.join(VIEWER, 'nba_injuries_2026-10-23.json'),
  ];
  for (const file of sources) {
    const text = fs.readFileSync(file, 'utf8');
    assert.ok(!banned.test(text), `${path.basename(file)} contains a banned marketing word`);
  }

  // "verified" may only appear as the DENIAL form in fixture data:
  //   · the JSON boolean "verified": false
  //   · the phrase "unverified ..." (word-boundary safe)
  for (const date of ['2026-10-22', '2026-10-23']) {
    const oddsText = fs.readFileSync(path.join(VIEWER, `nba_odds_${date}.json`), 'utf8');
    for (const match of oddsText.matchAll(/"verified"\s*:\s*(true|false)/g)) {
      assert.equal(match[1], 'false', 'fixture quotes must set verified:false');
    }
  }
  const nbaJs = fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'nba.js'), 'utf8')
    // Strip comments and template interpolations so only literal copy is
    // scanned (parameter names like `(ingested, verified)` are not copy).
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '')
    .replace(/\$\{[^}]*\}/g, '');
  assert.ok(!/\bverified\b/i.test(nbaJs.replace(/unverified/gi, '')), 'nba.js must not claim verified');
});
