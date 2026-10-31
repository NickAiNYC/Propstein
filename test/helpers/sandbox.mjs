/**
 * Shared VM sandbox for PropWire browser-code tests.
 * Zero dependencies: stub DOM + frozen Date + file-backed fetch.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
export const VIEWER = path.join(ROOT, 'viewer');
const REPO = ROOT;
export const FROZEN_MS = Date.parse('2026-10-22T12:00:00Z');

export function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
}

export function normalizeTokens(text) {
  return String(text)
    .replace(/bet_\d+_[a-z0-9]+/g, 'bet_<TOKEN>')
    .replace(/"ticket_id":"[^"]*"/g, '"ticket_id":"<TOKEN>"')
    .replace(/"logged_at":"[^"]*"/g, '"logged_at":"<TOKEN>"');
}

export function makeElement(knownIds) {
  const el = {
    textContent: '', value: '', hidden: false, disabled: false,
    open: false, offsetWidth: 0, scrollTop: 0, dataset: {}, style: { cssText: '' },
    title: '', id: '',
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    appendChild() {}, insertBefore() {}, remove() {}, focus() {}, blur() {},
    scrollIntoView() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return makeElement(knownIds); }, querySelectorAll() { return []; },
    closest() { return null; }, showModal() { this.open = true; }, close() { this.open = false; }, insertAdjacentHTML() {},
  };
  // innerHTML setter mimics live-DOM behavior: ids injected via markup
  // (e.g. the banner's dqRetryBtn) become resolvable by getElementById, so
  // the parity harness exercises the same paths a real page does.
  let inner = '';
  Object.defineProperty(el, 'innerHTML', {
    get: () => inner,
    set: (value) => {
      inner = String(value);
      if (knownIds) {
        for (const match of inner.matchAll(/\bid="([^"]+)"/g)) knownIds.add(match[1]);
      }
    },
  });
  return el;
}

export function buildSandbox({ seedLocalStorage = {} } = {}) {
  const registry = new Map();
  const getEl = (selector) => {
    if (!registry.has(selector)) registry.set(selector, makeElement(knownIds));
    return registry.get(selector);
  };
  // Static id inventory of the shipped page (viewer/index.html): the stub
  // DOM resolves getElementById ONLY for ids a real browser could resolve —
  // ids present in the static HTML, plus ids injected later via innerHTML.
  // Every call is recorded so the parity test can pin exactly which elements
  // the booted app reads and populates (dom_access_log snapshot).
  const staticIds = (() => {
    try {
      const html = fs.readFileSync(path.join(VIEWER, 'index.html'), 'utf8');
      return new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
    } catch (_) {
      return new Set();
    }
  })();
  const knownIds = new Set(staticIds);
  const domCalls = [];
  const lsStore = new Map(Object.entries(seedLocalStorage));
  const localStorage = {
    getItem: (k) => (lsStore.has(k) ? lsStore.get(k) : null),
    setItem: (k, v) => lsStore.set(k, String(v)),
    removeItem: (k) => lsStore.delete(k),
  };
  const FrozenDate = class extends Date {
    constructor(...args) {
      if (args.length === 0) super(FROZEN_MS);
      else super(...args);
    }
    static now() { return FROZEN_MS; }
  };

  const document = {
    querySelector: (sel) => getEl(sel),
    querySelectorAll: () => [],
    getElementById: (id) => {
      const key = String(id);
      const resolved = knownIds.has(key);
      domCalls.push({ id: key, resolved });
      return resolved ? getEl(`#${key}`) : null;
    },
    addEventListener() {},
    removeEventListener() {},
    createElement: () => makeElement(),
    body: { appendChild() {}, classList: { add() {}, remove() {}, toggle() {} }, dataset: {} },
    documentElement: { dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {} },
    title: '',
  };

  const window = {
    matchMedia: () => ({ matches: false, media: '', addEventListener() {}, addListener() {} }),
    addEventListener() {},
    removeEventListener() {},
    scrollTo() {},
    open() { return null; },
    location: { href: 'https://propwire.test/', protocol: 'https:', pathname: '/', search: '', hash: '', reload() {} },
    navigator: {},
    localStorage,
  };

  const fetchImpl = async (rawPath) => {
    const clean = String(rawPath).split('?')[0];
    const file = path.join(VIEWER, clean.replace(/^\/+/, ''));
    // The parity/unit suites pin the LEGACY baseline (built-in 2026_w7 slate
    // registry): the autopilot manifest (feeds/slate-index.json, regenerated
    // by scripts/autopilot.py as weeks roll over) is deliberately 404 here so
    // golden snapshots stay pinned to a fixed data context. Manifest-driven
    // discovery is covered by scripts/verify_v151_autopilot.mjs over real HTTP.
    if (clean === '/feeds/slate-index.json') {
      return { ok: false, status: 404, json: async () => { throw new Error('not found'); } };
    }
    // Same determinism contract for the odds feed: viewer/live_odds_feed.json
    // now carries REAL Polymarket quotes (v176, refreshed by the daily
    // autopilot run), so the suites pin it to the committed w7 fixture —
    // goldens and staleness scenarios never drift with live data. Live-feed
    // behavior is covered by scripts/verify_v176_cards.mjs over real HTTP.
    if (clean === '/live_odds_feed.json' || clean === 'live_odds_feed.json') {
      const text = fs.readFileSync(path.join(REPO, 'test', 'fixtures', 'live_odds_feed_w7_pinned.json'), 'utf8');
      return { ok: true, status: 200, json: async () => JSON.parse(text) };
    }
    if (clean.startsWith('http') || !fs.existsSync(file)) {
      return { ok: false, status: 404, json: async () => { throw new Error('not found'); } };
    }
    const text = fs.readFileSync(file, 'utf8');
    return { ok: true, status: 200, json: async () => JSON.parse(text) };
  };

  const sandbox = {
    console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    document, window, localStorage, Date: FrozenDate,
    fetch: fetchImpl, URL, URLSearchParams, AbortController, Event: class { constructor() {} },
    navigator: window.navigator,
    location: window.location,
    matchMedia: window.matchMedia,
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    cancelAnimationFrame() {},
    isFinite, Number, String, Boolean, Array, Object, Math, JSON, Map, Set,
    Promise, Error, RegExp, parseFloat, parseInt,
    globalThis: {},
  };
  sandbox.globalThis = sandbox;
  sandbox.window.matchMedia = window.matchMedia;
  return { sandbox, registry, lsStore, domCalls, knownIds };
}

/**
 * Harness-only: attach ONE synthetic quote to the FIRST WR row of the active
 * slate so render/modal/ledger paths stay golden-covered.
 *
 * Why this exists: the provenance hotfix de-identified the shipped demo feeds
 * (players -> "Player A..G", books -> "Synthetic Book A..D") AND made demo
 * quotes intentionally fail slate matching, so no shipped quote can attach to
 * a real slate row. That is the correct fail-closed end state for SHIPPED
 * data — but the render/eval/modal/ledger code paths need at least one
 * attached quote to be exercised at all. This injects that input at the
 * harness boundary only: the quote is never written to any shipped file, and
 * it carries the efficient-market shape (line == fair, -110/-110, PASS,
 * stake 0, verified: false) so nothing actionable is simulated.
 */
export function attachSyntheticQuote(P, { market = 'receiving_yards' } = {}) {
  const rows = P.state.slate || [];
  const row = rows.find((r) => r.position === 'WR')
    || rows.find((r) => ['WR', 'TE', 'RB'].includes(r.position));
  if (!row) throw new Error('attachSyntheticQuote: no skill-position row in the active slate');
  const quote = {
    quote_id: 'harness_synthetic_open',
    provider_quote_id: 'harness_synthetic_open',
    book: 'Synthetic Book A',
    player_id: row.player_id,
    player_name: row.player_display_name,
    team: row.team,
    opponent: row.opponent_team,
    game_id: row.game_id,
    position: row.position,
    market,
    line: Number(row.fair_line_rec ?? 3.5), // efficient-market case: line == fair
    fair_line: Number(row.fair_line_rec ?? 3.5),
    over_odds: -110,
    under_odds: -110,
    observed_at: '2026-10-20T06:23:35.000137+00:00',
    source: 'Synthetic Book A Manual Entry (UNVERIFIED - harness fixture)',
    source_url: '',
    receipt_id: '',
    content_hash: 'harness-synthetic',
    verified: false,
    evaluation: {
      is_qualified: false,
      status: 'PASS',
      best_side: 'OVER',
      prob_edge: 0.0,
      break_even_adv: -0.0238,
      expected_return: -0.0455,
      actionable_stake: 0.0,
      catalyst: 'pricing',
      injury_context: null,
    },
  };
  P.state.odds.quotes = [quote, ...((P.state.odds && P.state.odds.quotes) || [])];
  return quote;
}

/** Harness-only trusted state for exercising the allowed mutation path. */
export function authorizeSyntheticExecution(P, quote) {
  P.state.userTier = 'sharp';
  quote.verified = true;
  quote.source_url = 'https://example.test/quotes/harness';
  quote.receipt_id = 'receipt_harness_verified';
  quote.observed_at = '2026-10-22T11:59:30Z';
  quote.evaluation.prob_edge = 0.11;
  quote.evaluation.expected_return = 0.05;
  quote.evaluation.status = 'QUALIFIED';
  P.state.feedHealth = {
    slate: 'ok', games: 'ok', odds: 'ok', news: 'ok', dataKind: 'live',
    oddsUpdatedAt: '2026-10-22T11:59:30Z',
    newsLastPolledAt: '2026-10-22T11:59:30Z',
  };
  return quote;
}

/** Load registry.js + every adapter + app.js (same order as the HTML pages). */
export function loadApp(sandbox) {
  const sources = [
    ['viewer/js/sports/registry.js', path.join(VIEWER, 'js', 'sports', 'registry.js')],
    ['viewer/js/sports/nfl.js', path.join(VIEWER, 'js', 'sports', 'nfl.js')],
    ['viewer/js/sports/nba.js', path.join(VIEWER, 'js', 'sports', 'nba.js')],
  ];
  const source = fs.readFileSync(path.join(VIEWER, 'app.js'), 'utf8');
  const hook = `
  globalThis.__PW_PARITY__ = {
    state, SLATES, SPORT_ID, adapter, loadSlate, evaluateRow, filteredRows,
    renderAll, renderBoard, renderHomeEdgePreview, fairValue, projectionValue, logBet, openExecutionSlip, confirmExecution, setView,
    setPlayMode, breakerFor,
    sportSwitcherItems, switchToSport, defaultBootSlate,
    feedHealthStates, updateFeedHealthUI, feedVerificationLabel, updateFeedVerificationUI, marketFeedSourceLabel, detectBookDiscrepancy, executionDecision, stampProvenance,
    renderSportChrome, renderDetailModal,
    storage: { loadPortfolio, savePortfolio, loadWatchlist, saveWatchlist, migrateLegacyStorage, MIGRATION_FLAG, STORE, migrationResult }
  };
})();`;
  const injected = source.replace(/\}\)\(\);\s*$/, hook);
  if (injected === source) throw new Error('Failed to inject parity hook into viewer/app.js');
  vm.createContext(sandbox);
  for (const [name, file] of sources) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: name });
  }
  vm.runInContext(injected, sandbox, { filename: 'viewer/app.js' });
  return sandbox.__PW_PARITY__;
}
