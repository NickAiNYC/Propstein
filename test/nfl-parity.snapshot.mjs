import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { canonical, normalizeTokens, buildSandbox, loadApp, attachSyntheticQuote, authorizeSyntheticExecution, VIEWER } from './helpers/sandbox.mjs';

/**
 * NFL PARITY SNAPSHOT HARNESS — test/nfl-parity.snapshot.mjs
 *
 *   node --test test/nfl-parity.snapshot.mjs                  # assert parity
 *   PW_UPDATE_SNAPSHOTS=1 node --test test/nfl-parity.snapshot.mjs  # re-capture
 *
 * Determinism: Date frozen at 2026-10-22T12:00:00Z (pre-kickoff for the whole
 * 2026_w7 slate), TZ pinned America/New_York, ledger id/ticket/logged_at
 * tokenized, stub-DOM VM harness (zero new deps).
 *
 * ANNOUNCED, INTENTIONAL post-refactor deltas (whitelisted here, each
 * documented in the Phase 1 report — anything else failing is a regression):
 *   1. ledger entries gain `sport: "nfl"` (spec'd migration, user-approved)
 *   2. ledger `config_version` becomes the versioned config value
 *      ("2026.10.24-1") instead of the hardcoded "1.1.0" (spec item 5)
 *   3. evaluateRow output gains `exemption_audit` on exempted rows
 *      (user small-edit #4: auditable beneficiary exemption)
 *   4. circuit_breaker_config.json is restructured per-sport; the snapshot
 *      compares SEMANTIC NFL VALUES only (structure asserted in
 *      test/circuit-breaker-config.test.mjs)
 *   5. provenance hotfix: shipped demo feeds de-identified and no longer
 *      attach to the slate; the harness attaches ONE synthetic quote
 *      (attachSyntheticQuote) so render/modal/ledger goldens keep covering
 *      those paths. Goldens re-captured via PW_UPDATE_SNAPSHOTS=1.
 */

process.env.TZ = 'America/New_York';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const SNAPDIR = path.join(ROOT, 'test', 'snapshots', 'nfl');
const UPDATE = process.env.PW_UPDATE_SNAPSHOTS === '1';

/** Strip announced post-refactor additions before byte comparison. */
function stripWhitelisted(value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(stripWhitelisted);
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    if (k === 'exemption_audit' || k === 'sport') continue; // announced additions
    out[k] = stripWhitelisted(v);
  }
  return out;
}

function dumpRegistry(registry) {
  const out = {};
  for (const [selector, el] of [...registry.entries()].sort()) {
    out[selector] = { innerHTML: el.innerHTML, textContent: el.textContent };
  }
  return canonical(out);
}

function dumpEvaluations(P) {
  const markets = ['receiving_yards', 'receptions', 'anytime_td'];
  const out = {};
  for (const market of markets) {
    P.state.filters.market = market;
    const rows = {};
    for (const row of P.state.slate) rows[row.player_id] = stripWhitelisted(P.evaluateRow(row));
    out[market] = { rows, order: P.filteredRows().map((r) => r.player_id) };
  }
  return canonical(out);
}

function dumpProjections(P) {
  return canonical(stripWhitelisted(P.state.slate));
}

async function dumpRender(P, registry, view, market) {
  P.state.filters.market = market;
  P.setView(view);
  P.renderAll();
  return dumpRegistry(registry);
}

/**
 * Detail-modal golden: capture the exact modal markup for one quoted NFL
 * row. Captured from the PRE-adapterization code path (commit 83714bd tree)
 * so the Phase 2 remediation that routes the modal through adapter.detail
 * hooks must reproduce this markup byte-for-byte.
 */
function dumpDetailModal(P, registry) {
  const quoted = P.state.odds.quotes.find((q) => q.market === 'receiving_yards' && q.player_id);
  assert.ok(quoted, 'live_odds_feed must contain a receiving_yards quote for the modal golden');
  const row = P.state.slate.find((r) => r.player_id === quoted.player_id);
  assert.ok(row, 'slate row for the modal golden must exist');
  P.state.filters.market = 'receiving_yards';
  P.state.scenarioTargetShare = null; // openDetail() pre-state
  P.renderDetailModal(row);
  const pick = {};
  for (const sel of ['#detailTitle', '#detailMeta', '#detailContent']) {
    const el = registry.get(sel);
    pick[sel] = el ? { innerHTML: el.innerHTML, textContent: el.textContent } : null;
  }
  return canonical(pick);
}

/**
 * DOM-access spy summary (audit B2, remediation option b): every
 * getElementById call the booted NFL app makes, with resolved counts. The
 * stub DOM resolves only ids a real page could resolve (static index.html
 * ids + ids injected via innerHTML). Pinned as a golden: any NEW element the
 * NFL path starts populating must appear here and be consciously allowed.
 */
function dumpDomAccess(domCalls) {
  const summary = {};
  for (const call of domCalls) {
    if (!summary[call.id]) summary[call.id] = { calls: 0, resolved: 0 };
    summary[call.id].calls += 1;
    if (call.resolved) summary[call.id].resolved += 1;
  }
  return canonical(summary);
}

/** Ids the NFL boot/render path is ALLOWED to resolve via getElementById. */
const NFL_DOM_ALLOWLIST = new Set([
  // Phase 2 sport chrome (the earned, documented whitelist delta)
  'sportSwitcher', 'mobileSportSwitcher', 'marketChipGroup', 'positionChipGroup', 'signalSheetChips',
  'slateSelector', 'mobileSlateSelector', 'modeTopBtn', 'topCount',
  // Feed-health failure-mode UI
  'dataQualityBanner', 'dqRetryBtn',
  'snapshotAgePill',
]);

async function dumpLedger(P, lsStore) {
  const quoted = P.state.odds.quotes.find((q) => q.market === 'receiving_yards' && q.player_id);
  assert.ok(quoted, 'live_odds_feed must contain at least one receiving_yards quote');
  P.state.filters.market = 'receiving_yards';
  P.state.portfolio = [];
  P.logBet(quoted.player_id);
  P.confirmExecution(quoted.player_id);
  const entry = P.state.portfolio[0];
  assert.ok(entry, 'logBet must create a ledger entry');

  // Post-refactor assertions (announced deltas must exist and be correct).
  assert.equal(entry.sport, 'nfl', 'ledger entries must be sport-tagged "nfl" post-migration');
  if (P.state.breakerConfig) {
    assert.equal(entry.config_version, P.state.breakerConfig.config_version,
      'ledger config_version must come from the versioned breaker config');
  }

  const normalized = canonical(stripWhitelisted(JSON.parse(normalizeTokens(canonical(entry)))))
    .replace(/"config_version":"[^"]*"/g, '"config_version":"<TOKEN>"');
  const storedRaw = lsStore.get('propwire_portfolio_ledger_v2') || lsStore.get('propwire_portfolio_ledger') || '';
  return { entry: normalized, stored: normalizeTokens(storedRaw) };
}

function dumpBreakerNflValues() {
  const raw = fs.readFileSync(path.join(VIEWER, 'circuit_breaker_config.json'), 'utf8');
  const parsed = JSON.parse(raw);
  const nfl = parsed.sports && parsed.sports.nfl ? parsed.sports.nfl : parsed;
  const th = nfl.thresholds || {};
  const mk = nfl.markets || {};
  return canonical({
    drift_pct_hurdle: th.drift_pct_hurdle,
    high_edge_caution_hurdle: th.high_edge_caution_hurdle,
    cooldown_minutes: th.cooldown_minutes,
    deadman_switch_max_age_seconds: th.deadman_switch_max_age_seconds,
    receiving_yards_drift_hurdle: mk.receiving_yards && mk.receiving_yards.drift_hurdle,
    receiving_yards_beneficiary_max_drift: mk.receiving_yards && mk.receiving_yards.beneficiary_max_drift,
    receptions_drift_hurdle: mk.receptions && mk.receptions.drift_hurdle,
    receptions_beneficiary_max_drift: mk.receptions && mk.receptions.beneficiary_max_drift,
    anytime_td_drift_hurdle: mk.anytime_td && mk.anytime_td.drift_hurdle,
    anytime_td_beneficiary_max_drift: mk.anytime_td && mk.anytime_td.beneficiary_max_drift,
  });
}

async function captureAll() {
  const { sandbox, registry, lsStore, domCalls } = buildSandbox();
  const P = loadApp(sandbox);

  // Mirror init() (viewer/app.js): chrome render precedes the slate load on
  // a real page. Before the B2 remediation the sandbox could not run this
  // path at all (no getElementById), which is exactly the blind spot the
  // audit flagged — Phase 2 chrome was invisible to the golden captures.
  P.renderSportChrome();
  await P.loadSlate('2026_w7');
  // Provenance hotfix: shipped demo quotes must never attach to the real
  // slate, so the harness injects its own efficient-market quote (see
  // sandbox.mjs attachSyntheticQuote) before modal/ledger/renders capture.
  const synthetic = attachSyntheticQuote(P);
  authorizeSyntheticExecution(P, synthetic);
  P.state.filters.market = 'receiving_yards';

  const snaps = {};
  for (const market of ['receiving_yards', 'receptions', 'anytime_td']) {
    snaps[`renders_table_${market}.json`] = await dumpRender(P, registry, 'table', market);
  }
  snaps['renders_cards_receiving_yards.json'] = await dumpRender(P, registry, 'cards', 'receiving_yards');
  // v176: research-mode decision card golden — receptions carries no
  // synthetic quote, so with playMode 'all' this pins the money row /
  // signal row / action bar layout (the default live state) byte-exact,
  // not just the quoted state. playMode is restored right after so the
  // remaining captures keep their original semantics.
  P.setPlayMode('all');
  snaps['renders_cards_research_receptions.json'] = await dumpRender(P, registry, 'cards', 'receptions');
  P.setPlayMode('actionable');
  snaps['evaluations.json'] = dumpEvaluations(P);
  snaps['projections_slate_2026_w7.json'] = dumpProjections(P);
  snaps['detail_modal.json'] = dumpDetailModal(P, registry);
  snaps['ledger_entry.json'] = canonical(await dumpLedger(P, lsStore));
  snaps['breaker_config.json'] = dumpBreakerNflValues();
  snaps['dom_access_log.json'] = dumpDomAccess(domCalls);

  // Spy assertion (audit B2 option b): the NFL path may only populate the
  // allowlisted chrome elements — proving "no unexpected element was
  // populated" rather than achieving silence by omission.
  const unexpected = [...new Set(domCalls.filter((c) => c.resolved).map((c) => c.id))]
    .filter((id) => !NFL_DOM_ALLOWLIST.has(id));
  assert.deepStrictEqual(unexpected, [],
    `NFL path populated non-allowlisted element(s) via getElementById: ${unexpected.join(', ')}`);
  return snaps;
}

function compareOrUpdate(snaps) {
  const results = { updated: [], passed: [], failed: [] };
  for (const [name, actual] of Object.entries(snaps).sort()) {
    const file = path.join(SNAPDIR, name);
    if (UPDATE) {
      fs.mkdirSync(SNAPDIR, { recursive: true });
      fs.writeFileSync(file, actual);
      results.updated.push(name);
      continue;
    }
    if (!fs.existsSync(file)) { results.failed.push(`${name}: snapshot file missing`); continue; }
    const expected = fs.readFileSync(file, 'utf8');
    if (expected !== actual) results.failed.push(`${name}: OUTPUT DIFFERS from golden snapshot`);
    else results.passed.push(name);
  }
  return results;
}

test('NFL parity: rendered output, evaluations, projections, ledger, breaker values', async () => {
  assert.equal(process.env.TZ, 'America/New_York', 'TZ pin failed — Date formatting would be machine-dependent');
  const snaps = await captureAll();
  const results = compareOrUpdate(snaps);

  if (UPDATE) {
    console.log(`parity snapshots UPDATED: ${results.updated.join(', ')}`);
    return;
  }
  assert.deepStrictEqual(
    results.failed, [],
    `NFL PARITY REGRESSION — golden snapshots do not match.\n${results.failed.join('\n')}\n` +
    'If (and only if) this diff is an announced, intentional change, re-capture with PW_UPDATE_SNAPSHOTS=1 and document it in the phase report.',
  );
  assert.ok(results.passed.length >= 10, `expected 10 snapshots (8 goldens + modal + dom access log), passed: ${results.passed.length}`);
});
