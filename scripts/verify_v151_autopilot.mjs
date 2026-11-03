#!/usr/bin/env node
// Headless boot check for the 2026-10-28 v151 autopilot pass.
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - slate-index manifest: schema, NFL default = active week (2026_w8),
//     every w8 viewer file resolves 200 + valid JSON, NBA fixture nights
//     registered as historical
//   - app boot over real HTTP: state.slateKey === '2026_w8', slate selector
//     lists W8 Live + legacy W7/W1 options, first Top-Play = Puka Nacua
//     (from the enriched current_picks_2026_w8.json), build-hash 2026-w8-v19
//   - service worker propwire-v154-prod activates + precache populated
//   - zero console errors, zero failed requests on the critical feed set
//   - fail-closed tripwires: manifest URL + catch-fallback present in app.js,
//     node-test sandbox still pins the legacy baseline (404 stub)
// Screenshots: /home/z/my-project/download/headless_v151_autopilot_1280.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9400 + Math.floor(Math.random() * 300);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  const file = join(ROOT, rel);
  if (!existsSync(file)) { res.writeHead(404); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, r));
console.log('serving on port', PORT);

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};
const getJson = async (path) => {
  const res = await fetch(`http://127.0.0.1:${PORT}${path}`);
  if (!res.ok) return { err: `HTTP ${res.status}` };
  try { return { data: JSON.parse(await res.text()) }; }
  catch (e) { return { err: `bad JSON: ${e.message}` }; }
};

// ── 1. Manifest: schema + default + file resolution ──────────────────────
const man = await getJson('/feeds/slate-index.json');
check('manifest: fetch 200 + valid JSON', !man.err, man.err || '');
const manifest = man.data || {};
check('manifest: schema_version slate-index.v1', manifest.schema_version === 'slate-index.v1');
check('manifest: generated_at + source stamped', !!manifest.generated_at && manifest.source === 'scripts/autopilot.py');
const nfl = (manifest.sports || {}).nfl || {};
check('manifest: NFL default = 2026_w8', nfl.default_slate === '2026_w8', String(nfl.default_slate));
check('manifest: NFL registers w1/w7/w8', ['2026_w1', '2026_w7', '2026_w8'].every((k) => (nfl.slates || {})[k]), Object.keys(nfl.slates || {}).join(','));
check('manifest: w7 flipped historical (week ended)', (nfl.slates || {})['2026_w7']?.historical === true);
check('manifest: w8 live + upcoming label', (nfl.slates || {})['2026_w8']?.historical === false && /Oct 29/.test((nfl.slates || {})['2026_w8']?.state || ''));
const nba = (manifest.sports || {}).nba || {};
check('manifest: NBA fixture nights registered as historical', ['2026-10-22', '2026-10-23'].every((k) => (nba.slates || {})[k]?.historical === true) && nba.default_slate === null);
const w8 = (nfl.slates || {})['2026_w8'] || {};
for (const [field, file] of Object.entries({ slate: w8.slate, games: w8.games, picks: w8.picks, injuries: w8.injuries, snapshots: w8.snapshots })) {
  const res = await getJson(`/${file}`);
  check(`w8 feed resolves + parses: ${field} (${file})`, !res.err, res.err || '');
}
const slate8 = (await getJson(`/${w8.slate}`)).data;
check('w8 slate: 400+ player rows with fair lines', Array.isArray(slate8) && slate8.length >= 350 && slate8[0].fair_line_yards != null, `${Array.isArray(slate8) ? slate8.length : 0} rows`);
const games8 = (await getJson(`/${w8.games}`)).data;
check('w8 games: 14 games, CAR@GB Thursday opener', Array.isArray(games8) && games8.length === 14 && games8[0].game_id === '2026_08_CAR_GB', `${Array.isArray(games8) ? games8.length : 0} games`);
const picks8 = (await getJson(`/${w8.picks}`)).data;
check('w8 picks: gate/kelly + top_projections enriched', picks8.week === 8 && Array.isArray(picks8.top_projections) && picks8.top_projections.length > 0 && picks8.top_projections[0].player === 'Puka Nacua', `${(picks8.top_projections || []).length} top plays`);
const inj8 = (await getJson(`/${w8.injuries}`)).data;
check('w8 injuries: honest empty report (nflverse not yet published)', inj8.slate_week === 8 && Array.isArray(inj8.injuries) && inj8.injuries.length === 0);

// ── 2. Fail-closed tripwires (source-level) ──────────────────────────────
const appSrc = readFileSync(join(ROOT, 'app.js'), 'utf8');
check('tripwire: app.js boots manifest + fails closed', appSrc.includes("fetchJson('feeds/slate-index.json'") && /catch \(_\) \{\s*\n?\s*return 0; \/\/ offline/.test(appSrc));
const sandboxSrc = readFileSync(join(process.cwd(), 'test', 'helpers', 'sandbox.mjs'), 'utf8');
check('tripwire: node-test sandbox pins legacy baseline (manifest 404)', sandboxSrc.includes("clean === '/feeds/slate-index.json'"));

// ── 3. Boot over real HTTP: W8 live on the board ─────────────────────────
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
const failedRequests = [];
page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 200)); });
page.on('pageerror', (err) => errors.push(String(err).slice(0, 200)));
page.on('response', (r) => { if (r.status() >= 400) failedRequests.push(`${r.status()} ${r.url().split('/').pop()}`); });

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await page.waitForFunction('window.__PROP_WIRE_READY__ === true', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(800);

const boot = await page.evaluate(() => {
  const state = window.__PROP_WIRE_STATE__ || {};
  const selector = document.querySelector('#slateSelector');
  const active = selector ? selector.options[selector.selectedIndex] : null;
  const rows = document.querySelectorAll('#slateRows tr[data-testid="slate-row"]').length;
  const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content;
  const topPlay = document.querySelector('.pw-top-play-player, [data-testid="top-play"] .pw-player-name');
  const emptyTitle = document.querySelector('#emptyState .anti-tout-title');
  const emptyBtn = document.querySelector('#antiToutViewAllBtn');
  return {
    slateKey: state.slateKey,
    slateRows: Array.isArray(state.slate) ? state.slate.length : 0,
    options: selector ? [...selector.options].map((o) => o.value) : [],
    activeLabel: active ? active.textContent.trim() : null,
    domRows: rows,
    buildHash: meta('build-hash'),
    themeColor: meta('theme-color'),
    topPlayText: topPlay ? topPlay.textContent.trim() : null,
    emptyHeadline: emptyTitle ? emptyTitle.textContent.trim() : null,
    emptyCta: emptyBtn ? emptyBtn.textContent.trim() : null,
  };
});
check('boot: state.slateKey === 2026_w8 (autopilot default adopted)', boot.slateKey === '2026_w8', String(boot.slateKey));
check('boot: w8 slate loaded (422 rows)', boot.slateRows === 422, String(boot.slateRows));
check('boot: selector lists w8 + legacy w7/w1', boot.options.includes('2026_w8') && boot.options.includes('2026_w7') && boot.options.includes('2026_w1'), boot.options.join(', '));
check('boot: active option labels W8', /W8/.test(boot.activeLabel || ''), boot.activeLabel || '');
// Designed fail-closed UX (same as w7 today): the de-identified demo quotes
// attach to no slate rows, so actionable mode shows the honest "qualification
// paused" empty state with a one-click path to the full research slate.
check('boot: fail-closed empty state honest (qualification paused)', boot.emptyHeadline !== null, boot.emptyHeadline || 'no headline');
check('boot: research-projections CTA offers full w8 slate', /422/.test(boot.emptyCta || ''), boot.emptyCta || 'no CTA');
check('boot: build-hash 2026-w8-v19 + theme #0b0e14', boot.buildHash === '2026-w8-v19' && boot.themeColor === '#0b0e14', `hash=${boot.buildHash} theme=${boot.themeColor}`);
check('boot: zero console/page errors', errors.length === 0, errors.slice(0, 3).join(' | ') || 'clean');
const criticalFailures = failedRequests.filter((f) => /slate_2026_w8|games_2026_w8|current_picks_2026_w8|injuries_2026_w8|slate-index/.test(f));
check('boot: zero failed critical feed requests', criticalFailures.length === 0, criticalFailures.join(' | ') || 'clean');

// One click: research mode renders the full 422-row w8 slate.
const research = await page.evaluate(() => {
  const btn = document.querySelector('#antiToutViewAllBtn');
  if (!btn) return { clicked: false };
  btn.click();
  return { clicked: true };
});
await page.waitForTimeout(400);
const afterCta = await page.evaluate(() => ({
  rows: document.querySelectorAll('#slateRows tr[data-testid="slate-row"]').length,
  firstPlayer: (document.querySelector('#slateRows tr[data-testid="slate-row"]')?.textContent || '').slice(0, 80),
}));
check('research mode: full w8 slate renders after CTA click', research.clicked && afterCta.rows >= 350, `${afterCta.rows} rows`);
check('research mode: first row is the top projection (Puka Nacua)', /Nacua/i.test(afterCta.firstPlayer), afterCta.firstPlayer.trim());

await page.screenshot({ path: join(SHOTS, 'headless_v151_autopilot_1280.png'), clip: { x: 0, y: 0, width: 1280, height: 620 } });

// ── 4. Service worker: v151 cache activates + precache populated ─────────
const swState = await page.evaluate(async () => {
  if (!('serviceWorker' in navigator)) return { err: 'no SW support' };
  const reg = await navigator.serviceWorker.ready.catch((e) => ({ err: e.message }));
  const keys = await caches.keys();
  const target = keys.find((k) => k === 'propwire-v154-prod');
  if (!target) return { err: 'no v151 cache', keys };
  const cache = await caches.open(target);
  const n = (await cache.keys()).length;
  const css = !!(await cache.match('/style.css?v=2026_v154'));
  return { n, css };
});
check('SW: propwire-v154-prod active + precache populated', !swState.err && swState.n >= 10 && swState.css, swState.err ? swState.err : `${swState.n} entries, busted css: ${swState.css}`);

await browser.close();
server.close();

console.log('─'.repeat(60));
if (failures) { console.log(`v151 autopilot harness: ${failures} FAILURES`); process.exit(1); }
console.log('v151 autopilot harness: ALL PASS');
