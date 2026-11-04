#!/usr/bin/env node
// Iteration-2 computed-style capture — BEFORE/AFTER regression harness.
// Captures computed styles for a pinned selector set on the terminal and a
// public player page at 1440 / 390, plus layout metrics. Run with
//   node /home/z/my-project/scripts/iter2_capture_styles.mjs <out.json>
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, statSync } from 'fs';
import { join, extname } from 'path';

const OUT = process.argv[2] || '/tmp/styles.json';
const REPO = '/home/z/my-project/propstein-src';
const ROOT = join(REPO, 'viewer');
const PORT = 9700 + Math.floor(Math.random() * 200);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  let rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  let file = join(ROOT, rel);
  if (existsSync(join(file, 'index.html'))) file = join(file, 'index.html');
  let isFile = false;
  try { isFile = statSync(file).isFile(); } catch { /* 404 below */ }
  if (!isFile) { res.writeHead(404); res.end('nf'); return; }
  try {
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
    res.end(readFileSync(file));
  } catch { res.writeHead(404); res.end('nf'); }
});
await new Promise((r) => server.listen(PORT, r));
const BASE = `http://localhost:${PORT}`;

const PROPS = ['background-color', 'color', 'border-color', 'border-bottom-color', 'font-family', 'display', 'position', 'height', 'width', 'min-height'];
const SELECTORS = [
  'body', '.pw-terminal-chrome', '.pw-topbar', '.pw-filterbar',
  '.mobile-bottom-nav', '.bottom-nav-item', '.chip-pill.active',
  '#slateRows tr td', '.mobile-quant-row', '.card-grid-col', '.home-edge-card',
  '.detail-dialog', 'a',
  '.pub-header', '.pub-brand', '.pub-nav a', '.pub-stats div',
  '.pub-table th', '.pub-status-quoted', '.pub-note', 'h1', '.pub-footer',
  '.pub-footer-nav',
];

async function capture(page) {
  return page.evaluate(({ selectors, props }) => {
    const out = {};
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (!el) { out[sel] = null; continue; }
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const entry = {};
      for (const p of props) entry[p] = cs.getPropertyValue(p);
      entry._box = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
      out[sel] = entry;
    }
    out._scrollWidth = document.documentElement.scrollWidth;
    out._innerWidth = window.innerWidth;
    return out;
  }, { selectors: SELECTORS, props: PROPS });
}

const browser = await chromium.launch();
const result = { capturedAt: new Date().toISOString(), surfaces: {} };

async function loadTerminal(page, width, height, openBoard) {
  await page.setViewportSize({ width, height });
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  // deterministic slate: switch to the populated 2026_w7 fixture
  await page.evaluate(() => {
    const s = document.querySelector('#slateSelector');
    if (s && s.value !== '2026_w7') {
      s.value = '2026_w7';
      s.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
  // wait for the switched slate's board content specifically (front-page
  // home cards render earlier and would satisfy a looser selector)
  try {
    await page.waitForFunction(() =>
      (document.querySelectorAll('#slateRows tr').length > 0) ||
      (document.querySelectorAll('#cardView .mobile-quant-row').length > 0), { timeout: 15000 });
    await page.waitForTimeout(600);
  } catch { /* capture whatever rendered — harness reports selectors as null */ }
  if (openBoard) {
    await page.evaluate(() => document.getElementById('explorePropsBtn')?.click());
    await page.waitForTimeout(1200);
  }
}

// Terminal @1440 (board open, table view)
let page = await browser.newPage();
await loadTerminal(page, 1440, 900, true);
result.surfaces['terminal-1440'] = await capture(page);
// Terminal @390 (board open)
await loadTerminal(page, 390, 844, true);
result.surfaces['terminal-390'] = await capture(page);
await page.close();

// Player page @1440 and @390
page = await browser.newPage();
const PLAYER = '/nfl/players/a-j-brown/receiving-yards/';
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(BASE + PLAYER, { waitUntil: 'networkidle' });
result.surfaces['player-1440'] = await capture(page);
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(BASE + PLAYER, { waitUntil: 'networkidle' });
result.surfaces['player-390'] = await capture(page);
await page.close();

await browser.close();
server.close();
const { writeFileSync } = await import('fs');
writeFileSync(OUT, JSON.stringify(result, null, 1));
console.log('captured ->', OUT);
