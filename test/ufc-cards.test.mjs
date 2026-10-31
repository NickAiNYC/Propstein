import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

/**
 * UFC CARD PARITY (2026-10-31) — the UFC fight cards must render with the SAME
 * today-game-card anatomy as the NFL/NBA schedule cards (viewer/js/today-schedule.js):
 * trigger face (meta row + status, mirrored matchup blocks, market context row,
 * action bar with chevron) plus an expandable panel of fighter rows, all via the
 * shared today-* classes from style.css.
 *
 * Honesty invariants under test (charter): fight.edge ("NO EDGE") stays on every
 * card face, the banner keeps the receipt count and the metered-pulls warning,
 * and the panel labels quotes as metered pulls — nothing may hide behind the
 * collapsed state.
 *
 * Interaction guard: UFC triggers carry NO data-game-index, and the capture-phase
 * click handler calls stopPropagation(), so today-schedule.js's delegated
 * `.today-game-trigger` handler (which resolves NFL/NBA event indexes and would
 * reject on UFC data) can never see a UFC card click.
 *
 * The card JSON below is a SYNTHETIC FIXTURE (deterministic shape coverage:
 * market present / market absent / void + winner). The shipped card files are
 * refreshed by the UFC autopilot and must never be pinned by a golden.
 */

const VIEWER = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'viewer');

const CARD = {
  event_name: 'UFC Test Night: Parity vs Fixture',
  honesty: 'NO EDGE · model unbacktested vs closing lines',
  receipts_verified: 0,
  market_as_of: '2026-10-31T18:00:00Z',
  backtest: { brier: 0.25, n: 10 },
  fights: [
    {
      fight_id: '9001',
      start: '2026-11-01T00:00:00Z',
      weight_class: 'Lightweight',
      sched_rounds: 3,
      status: 'scheduled',
      void: false,
      result: null,
      edge: 'NO EDGE',
      fighters: [
        { id: '1', name: 'Alpha "The Test" Fighter', record: '10-0-0', age: 29, reach_in: 70, stance: 'Orthodox', headshot: 'https://a.espncdn.com/i/headshots/mma/players/full/1.png' },
        { id: '2', name: 'Beta Fighter', record: '9-1-0', age: 31, reach_in: 72, stance: 'Southpaw', headshot: '' }
      ],
      model: { p: [0.6, 0.4], p_finish: 0.55, p_over_by_line: { '1.5': 0.7 } },
      market: { h2h_novig: [0.55, 0.45], best: [{ price: -120, book: 'draftkings' }, { price: 105, book: 'betonlineag' }] },
      totals: [{ line: 1.5, p_over_novig: 0.63, model_p_over: 0.7 }]
    },
    {
      fight_id: '9002',
      start: '2026-11-01T01:00:00Z',
      weight_class: "Women's Strawweight",
      sched_rounds: 3,
      status: 'cancelled',
      void: true,
      result: 'win',
      edge: 'NO EDGE',
      fighters: [
        { id: '3', name: 'Gamma Won', record: '5-0-0', winner: true, headshot: '' },
        { id: '4', name: 'Delta Lost', record: '4-1-0', winner: false, headshot: '' }
      ],
      model: { p: [0.7, 0.3], p_finish: 0.4, p_over_by_line: { '1.5': 0.6 } },
      market: {},
      totals: []
    }
  ]
};

class StubEl {
  constructor(id = '') {
    this.id = id;
    this._attrs = {};
    this.hidden = false;
    this.textContent = '';
    this.value = '';
    this._html = '';
    this.classList = { add() {}, remove() {}, contains() { return false; } };
  }
  setAttribute(key, value) { this._attrs[key] = String(value); }
  getAttribute(key) { return key in this._attrs ? this._attrs[key] : null; }
  set innerHTML(value) { this._html = String(value); }
  get innerHTML() { return this._html; }
}

async function renderUfc({ timeZone = 'et' } = {}) {
  const listeners = [];
  const byId = new Map([['todayScheduleTimezone', { value: timeZone }]]);
  const document = {
    getElementById: (id) => byId.get(String(id)) || null,
    addEventListener: (type, fn) => { listeners.push({ type, fn }); }
  };
  const window = {};
  const fetchImpl = async (rawPath) => {
    const clean = String(rawPath).split('?')[0];
    if (clean === '/feeds/slate-index.json') {
      const manifest = { sports: { ufc: { default_card: 'x', cards: { x: { card: 'ufc_card_fixture.json' } } } } };
      return { ok: true, json: async () => manifest };
    }
    if (clean === '/ufc_card_fixture.json') return { ok: true, json: async () => CARD };
    return { ok: false, status: 404, json: async () => { throw new Error('not found'); } };
  };
  const sandbox = {
    document, window, fetch: fetchImpl,
    console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    Intl, Date, Math, JSON, String, Number, Array, Object, Map, Set, Promise, Error, RegExp,
    encodeURIComponent, setTimeout: () => 0, clearTimeout() {}
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VIEWER, 'js', 'sports', 'ufc.js'), 'utf8'), sandbox, { filename: 'viewer/js/sports/ufc.js' });
  const container = new StubEl('todayScheduleGames');
  const titleEl = new StubEl('todayScheduleTitle');
  const sourceEl = new StubEl('todayScheduleSource');
  await window.PropSteinUFC.render(container, titleEl, sourceEl);
  return { html: container.innerHTML, title: titleEl.textContent, source: sourceEl.textContent, listeners, byId, sandbox };
}

test('UFC cards render with the shared NFL/NBA today-game-card anatomy', async () => {
  const { html } = await renderUfc();
  assert.equal((html.match(/class="today-game-card ufc-fight/g) || []).length, 2, 'two fight cards');
  assert.equal((html.match(/today-game-trigger ufc-game-trigger/g) || []).length, 2, 'each face is a trigger');
  assert.equal((html.match(/class="today-game-matchup"/g) || []).length, 2);
  assert.equal((html.match(/class="today-team[ "]/g) || []).length, 4, 'one matchup block per fighter');
  assert.equal((html.match(/today-team is-winner/g) || []).length, 1, 'graded winner flagged');
  assert.equal((html.match(/class="today-versus">VS</g) || []).length, 2, 'VS center like NFL/NBA');
  assert.equal((html.match(/class="today-game-action"/g) || []).length, 2);
  assert.equal((html.match(/today-game-chevron/g) || []).length, 2, 'chevron like NFL/NBA');
  assert.equal((html.match(/class="today-game-props"/g) || []).length, 2, 'expandable panel per fight');
  // Face context row mirrors SPREAD/O/U: totals chip when a market exists.
  assert.match(html, /O\/U 1\.5 RDS/);
  assert.match(html, /NO MARKET LINES/);
  assert.match(html, /Women&#39;s Strawweight · 3 RDS/, 'weight class chip is escaped');
});

test('UFC cards keep every honesty signal visible on the face', async () => {
  const { html } = await renderUfc();
  assert.equal((html.match(/class="ufc-noedge">NO EDGE</g) || []).length, 2, 'fight.edge on every card face');
  assert.match(html, /NO EDGE<\/b> · MODEL VS MARKET/, 'action bar explains the panel');
  assert.match(html, /Receipt-verified quotes: 0 — displayed lines are metered pulls, not receipts/, 'banner receipt state');
  assert.match(html, /Results-only backtest: Brier 0\.25 vs 0\.25 coin flip \(n=10\)/, 'banner backtest state');
  assert.match(html, /Metered odds pulls, not receipts · model unbacktested/, 'panel heading honesty');
  // Graded + void state stays on the face (cancelled fight, not hidden).
  assert.match(html, /ufc-status-cancelled">Cancelled</);
  assert.match(html, /today-game-card ufc-fight is-void/);
});

test('UFC panel rows show model vs market with book-attributed best prices', async () => {
  const { html } = await renderUfc();
  assert.equal((html.match(/class="today-prop-row ufc-prop-row"/g) || []).length, 4, 'fighter rows link to fighter pages');
  assert.equal((html.match(/data-ufc-fighter=/g) || []).length, 4);
  assert.match(html, /href="\/ufc\/fighter\?id=1"/);
  assert.match(html, /<b>60%<\/b><small>MODEL WIN<\/small>/);
  assert.match(html, /<b>MARKET NOVIG<\/b><small>55%<\/small>/);
  assert.match(html, /<b>BEST<\/b><small>-120 · draftkings<\/small>/, 'book attribution preserved');
  assert.match(html, /<b>BEST<\/b><small>\+105 · betonlineag<\/small>/);
  assert.match(html, /<b>BEST<\/b><small>no line pulled<\/small>/, 'absent market stays explicit');
  assert.match(html, /O\/U 1\.5 rds · market over 63% · model 70%/);
  assert.match(html, /No totals lines pulled · model over 1\.5 rds 60% \(model only, no market\) · model finish 40%/);
  // Fighter meta carries record/age/reach/stance; names with quotes are escaped.
  assert.match(html, /Alpha &quot;The Test&quot; Fighter/);
  assert.match(html, /10-0-0 · 29y · 70&quot; reach · Orthodox/, 'reach inches are attribute-escaped');
});

test('UFC triggers never collide with the NFL/NBA schedule handler', async () => {
  const { html, listeners } = await renderUfc();
  // The shared handler resolves data-game-index into its own event list;
  // UFC triggers must not carry that attribute at all.
  assert.doesNotMatch(html, /data-game-index/, 'UFC triggers carry no NFL/NBA event index');
  // The capture-phase click handler is registered and guards with stopPropagation.
  const click = listeners.find((l) => l.type === 'click');
  assert.ok(click, 'click handler registered');
  // Fighter-page stash stays wired for instant paint.
  assert.ok(listeners.some((l) => l.type === 'pointerdown'), 'pointerdown fighter stash registered');
});

test('UFC card expand/collapse toggles aria-expanded and the panel', async () => {
  const { html, listeners, byId } = await renderUfc();
  const click = listeners.find((l) => l.type === 'click');
  const trigger = new StubEl();
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-controls', 'ufcFightProps9001');
  const panel = new StubEl('ufcFightProps9001');
  panel.hidden = true;
  byId.set('ufcFightProps9001', panel);
  const event = () => {
    let stopped = false;
    return { target: { closest: (sel) => (sel === '.ufc-game-trigger' ? trigger : null) }, stopPropagation: () => { stopped = true; } , get stopped() { return stopped; } };
  };
  let ev = event();
  click.fn(ev);
  assert.equal(trigger.getAttribute('aria-expanded'), 'true');
  assert.equal(panel.hidden, false);
  assert.ok(ev.stopped, 'capture handler stops propagation before the shared schedule handler');
  ev = event();
  click.fn(ev);
  assert.equal(trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(panel.hidden, true);
  // Panels ship hidden and every aria-controls matches a real panel id.
  assert.equal((html.match(/<div class="today-game-props" id="ufcFightProps\d+" hidden>/g) || []).length, 2);
  const controls = [...html.matchAll(/aria-controls="(ufcFightProps\d+)"/g)].map((m) => m[1]);
  const panels = [...html.matchAll(/class="today-game-props" id="(ufcFightProps\d+)" hidden>/g)].map((m) => m[1]);
  assert.deepEqual([...controls].sort(), [...panels].sort(), 'aria wiring is complete');
});

test('UFC card times honor the schedule time-zone selector like NFL/NBA', async () => {
  const { html, source } = await renderUfc({ timeZone: 'et' });
  assert.match(html, /Sat, \d{1,2}:\d{2} (AM|PM) E[SD]T/, 'Eastern time on the face, same Intl shape as NFL/NBA');
  assert.match(source, /Times in Eastern time/);
  assert.match(source, /Odds as of /);
  assert.match(source, /2 fights/);
});
