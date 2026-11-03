#!/usr/bin/env node
// v175 visual + honesty harness — browser-verified at 1440px and 390px.
// Covers: (a) owner v174 compact grid / hover elevation / sticky first table
// column / mobile 4-tab nav & wrapping, viewed in a real browser (not just
// syntax/snapshot-checked); (b) the v175 honesty layer — CLV ribbon driven
// from the graded ledger (never 74.2% static), the heartbeat probe reporting
// the OBSERVED feed age (fixture feed is 7d stale -> must say STALE, never
// "verified"), and the simulator relabeled as an approximation.
// Screenshots: download/headless_v175_visual_{desktop,mobile}.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const REPO = process.cwd();
const PORT = 9700 + Math.floor(Math.random() * 200);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

const vercel = JSON.parse(readFileSync(join(REPO, 'vercel.json'), 'utf8'));
const prodHeaders = Object.fromEntries(
  vercel.headers.find((h) => h.source === '/(.*)').headers.map((h) => [h.key, h.value]));
const CSP = prodHeaders['Content-Security-Policy'];

// v176 determinism: viewer/live_odds_feed.json now carries real Polymarket
// quotes whose freshness varies with wall-clock time. The stale-feed honesty
// probes below need a FIXED stale context, so the odds route serves the
// committed w7 demo fixture (timestamps frozen in the past -> always stale).
const PINNED_ODDS = readFileSync(join(REPO, 'test', 'fixtures', 'live_odds_feed_w7_pinned.json'), 'utf8');
const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  if (rel === 'live_odds_feed.json') {
    res.writeHead(200, { 'Content-Type': 'application/json', ...prodHeaders });
    res.end(PINNED_ODDS);
    return;
  }
  const file = join(ROOT, rel);
  if (!existsSync(file)) { res.writeHead(404, prodHeaders); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream', ...prodHeaders });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, r));

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};

const bootPage = async (context, label) => {
  const page = await context.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  page.on('pageerror', (err) => pageErrors.push(String(err)));
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => window.__PROP_WIRE_READY__ === true, null, { timeout: 25000 });
  check(`${label}: boots to __PROP_WIRE_READY__ under prod CSP`, true);
  check(`${label}: zero uncaught page errors`, pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '));
  if (consoleErrors.length) console.log(`INFO  ${label}: ${consoleErrors.length} console error entries (pre-existing noise tolerated)`);
  return page;
};

// ── Static honesty: the fabricated figures must be gone from source ──────
const idx = readFileSync(join(ROOT, 'index.html'), 'utf8');
check('source: fabricated 74.2% CLV rate removed from index.html', !idx.includes('74.2%'));
check('source: fabricated +5.8% trend delta removed from index.html', !idx.includes('+5.8%'));
check('source: fabricated 7-point sparkline polyline removed', !idx.includes('2,14 10,12 19,13 28,7 37,9 46,4 54,5'));
check('source: CLV ribbon elements are ledger-driven (ids present)', idx.includes('id="clvBeatRateVal"') && idx.includes('id="clvTrendWrap"'));
check('source: simulator relabeled as approximate (inline panel)',
  readFileSync(join(ROOT, 'app.js'), 'utf8').includes('Approximate Line Simulator'));

// ── Desktop 1440x900: compact grid, hover elevation, sticky column ───────
const browser = await chromium.launch();
try {
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await bootPage(desktop, 'desktop 1440');

  // v175 CLV ribbon — driven from the graded ledger (8/8 beat close)
  const clv = await page.evaluate(() => ({
    rate: document.getElementById('clvBeatRateVal')?.textContent?.trim(),
    delta: document.getElementById('clvTrendDelta')?.textContent?.trim(),
    title: document.getElementById('clvTrendWrap')?.title || '',
    points: document.getElementById('clvSparkLine')?.getAttribute('points') || '',
    barVar: getComputedStyle(document.querySelector('.telemetry-progress-bar')).getPropertyValue('--clv-beat-rate').trim()
  }));
  check('CLV ribbon: beat rate from ledger (100.0%, not 74.2%)', clv.rate === '100.0%', clv.rate);
  check('CLV ribbon: sample-size chip (n=8) replaces fabricated delta', clv.delta === 'n=8', clv.delta);
  check('CLV ribbon: tooltip cites 8/8 graded receipts', clv.title.includes('8/8'), clv.title);
  check('CLV ribbon: sparkline has 8 ledger points', clv.points.split(' ').length === 8, `${clv.points.split(' ').length} pts`);
  check('CLV ribbon: progress bar width tracks ledger rate', ['100%', '100.0%'].includes(clv.barVar), clv.barVar);

  // v175 heartbeat probe — fixture feed is 7d stale; must NOT claim verified
  await page.click('#ribbonRefreshBtn');
  await page.waitForFunction(() => /Heartbeat (checked|verified|FAILED)/.test(document.getElementById('ribbonHeartbeatStatus')?.textContent || ''), null, { timeout: 15000 });
  const probe = await page.evaluate(() => ({
    status: document.getElementById('ribbonHeartbeatStatus')?.textContent?.trim(),
    title: document.getElementById('ribbonHealthTitle')?.textContent?.trim(),
    age: document.getElementById('ribbonHealthAge')?.textContent?.trim()
  }));
  check('probe: reports OBSERVED stale age honestly', /STALE/.test(probe.status) && /ago/.test(probe.status), probe.status);
  check('probe: never claims "verified" on a stale feed', !/verified/.test(probe.status), probe.status);
  check('probe: ribbon health title stays ODDS STALE', probe.title === 'ODDS STALE', `${probe.title} ${probe.age}`);

  // v174 compact grid (viewed in a real browser)
  await page.click('[data-view="compact-grid"]');
  await page.waitForSelector('#cardView.compact-grid');
  const compact = await page.evaluate(() => {
    const cv = document.getElementById('cardView');
    const cs = getComputedStyle(cv);
    return { display: cs.display, cols: (cs.gridTemplateColumns || '').split(' ').filter(Boolean).length, rows: cv.querySelectorAll('.mobile-quant-row').length };
  });
  check('compact grid: #cardView switches to CSS grid', compact.display === 'grid', compact.display);
  check('compact grid: 4-5 fluid columns at 1440px', compact.cols >= 4, `${compact.cols} cols`);
  check('compact grid: player rows render inside it', compact.rows >= 5, `${compact.rows} rows`);

  // v174 hover elevation (computed style under :hover — mouse.move with
  // steps is required; a single-step locator.hover() is not registered
  // reliably by headless Chromium right after a screenshot)
  const firstRow = page.locator('#cardView .mobile-quant-row').first();
  const rowBox = await firstRow.boundingBox();
  await page.mouse.move(rowBox.x + rowBox.width / 2, rowBox.y + rowBox.height / 2, { steps: 5 });
  await page.waitForTimeout(350);
  const transform = await firstRow.evaluate((el) => getComputedStyle(el).transform);
  check('hover elevation: translateY(-2px) applies on hover', /-2/.test(transform) && /matrix/.test(transform), transform);
  await page.screenshot({ path: join(SHOTS, 'headless_v175_visual_desktop.png'), fullPage: false });

  // v174 fluid table + sticky first column
  await page.click('[data-view="table"]');
  await page.waitForSelector('#slateRows tr');
  const sticky = await page.evaluate(() => {
    const th = document.querySelector('.slate-table th:first-child');
    const td = document.querySelector('.slate-table tbody tr td:first-child');
    return { th: getComputedStyle(th).position, td: td ? getComputedStyle(td).position : 'none', thLeft: getComputedStyle(th).left };
  });
  check('fluid table: header first column is sticky', sticky.th === 'sticky', sticky.th);
  check('fluid table: body first column is sticky', sticky.td === 'sticky', sticky.td);

  // v175/v176 simulator honesty labels — the simulator now lives INSIDE the
  // card (inline panel; the modal was retired). Same honesty strings.
  await page.click('[data-view="cards"]');
  await page.waitForSelector('.card-sim-primary');
  await page.click('.card-sim-primary');
  await page.waitForSelector('.csim-panel .csim-readout', { timeout: 10000 });
  const sim = await page.evaluate(() => {
    const panel = document.querySelector('.csim-panel');
    return {
      body: panel ? panel.textContent : '',
      eyebrow: panel?.querySelector('.csim-eyebrow')?.textContent?.trim() || '',
      note: panel?.querySelector('.sim-approx-note')?.textContent || ''
    };
  });
  check('simulator: P(Win) relabeled as model approximation', sim.body.includes('P(Win) Model Approx.'));
  check('simulator: Kelly relabeled half-Kelly capped 3%', sim.body.includes('Kelly (½·cap 3%)'));
  check('simulator: explicit approximation footnote present', /normal approximation/.test(sim.note) && /half-Kelly/.test(sim.note), sim.note.slice(0, 60) + '…');
  check('simulator: panel eyebrow says Approximate', sim.eyebrow === 'Approximate Line Simulator', sim.eyebrow);
  await desktop.close();

  // ── Mobile 390x844: wrapping, 4-tab nav, no horizontal overflow ────────
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    deviceScaleFactor: 2, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  });
  const mpage = await bootPage(mobile, 'mobile 390');

  const overflow = await mpage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('mobile 390: no horizontal overflow beyond baseline (<=10px)', overflow <= 10, `scrollWidth-clientWidth=${overflow}`);

  const nav = await mpage.evaluate(() => {
    const items = Array.from(document.querySelectorAll('.bottom-nav .bottom-nav-item, #bottomNav .bottom-nav-item, .bottom-nav-item'));
    const visible = items.filter((el) => el.offsetParent !== null && !el.hidden);
    const heights = visible.map((el) => Math.round(el.getBoundingClientRect().height));
    return { count: visible.length, minH: heights.length ? Math.min(...heights) : 0 };
  });
  check('mobile 390: bottom nav renders 4 tabs', nav.count >= 4, `${nav.count} tabs`);
  check('mobile 390: nav touch targets >= 40px (44px spec w/ safe-area clamp)', nav.minH >= 40, `min ${nav.minH}px`);

  const cards = await mpage.evaluate(() => document.querySelectorAll('#cardView .mobile-quant-row').length);
  check('mobile 390: quant cards render (default cards view)', cards >= 5, `${cards} cards`);

  // v176: the research card's old .card-quote-standby-wrap was retired with
  // the decision-card redesign — the honest wrap contract now lives on the
  // thumb-zone action bar (SIM primary / COPY FAIR / research tag).
  const wrap = await mpage.evaluate(() => {
    const el = document.querySelector('.card-action-bar');
    return el ? getComputedStyle(el).flexWrap : 'missing';
  });
  check('mobile 390: card action bar wraps (flex-wrap: wrap)', wrap === 'wrap', wrap);

  // Compact is a desktop-only density mode: the view switch must keep cards
  // on a 768px-or-below viewport even if the button is tapped.
  const compactBtnVisible = await mpage.evaluate(() => {
    const btn = document.querySelector('[data-view="compact-grid"]');
    return btn ? btn.offsetParent !== null : false;
  });
  if (compactBtnVisible) {
    await mpage.click('[data-view="compact-grid"]');
    await mpage.waitForTimeout(400);
    const stayed = await mpage.evaluate(() => !document.getElementById('cardView').classList.contains('compact-grid'));
    check('mobile 390: compact mode correctly withheld (cards fallback)', stayed);
  } else {
    check('mobile 390: compact mode button hidden on mobile (cards-only)', true);
  }
  const overflow2 = await mpage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('mobile 390: still no horizontal overflow after view interaction', overflow2 <= 10, `scrollWidth-clientWidth=${overflow2}`);
  await mpage.screenshot({ path: join(SHOTS, 'headless_v175_visual_mobile.png'), fullPage: false });
  await mobile.close();
} finally {
  await browser.close();
  server.close();
}

console.log(failures === 0 ? '\nv175 visual+honesty harness: ALL PASS' : `\nv175 visual+honesty harness: ${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
