#!/usr/bin/env node
// Headless boot check for the 2026-10-27 messaging/density pass.
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - zero console/page errors on boot
//   - Upgrade chip renders (no PRO · $29)
//   - receipt badge demoted below 1500px (display:none at 1280, visible at 1600)
//   - paused/anti-tout empty state reachable: force stale health + 0 actionable
// Screenshots: download/headless_v145_{desktop,empty,paused}.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 8900 + Math.floor(Math.random() * 400); // fresh port per run
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png' };

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

const browser = await chromium.launch();
const errors = [];
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

// 1. header chip
const chip = await page.textContent('#pricingBtn .pro-text-desktop');
console.log('upgrade chip          :', JSON.stringify(chip?.trim()));

// 2. receipt badge demotion at 1280
const badgeDisplay = await page.$eval('.pw-receipt-badge', (el) => getComputedStyle(el).display);
console.log('receipt badge @1280   :', badgeDisplay, '(expect none)');

// 3. force the stale-feed scenario and read the empty state
await page.evaluate(() => {
  const S = window.__PROP_WIRE_STATE__;
  S.feedHealth = {
    slate: 'ok', games: 'ok', odds: 'ok', news: 'ok', dataKind: 'live',
    oddsUpdatedAt: new Date(Date.now() - 6 * 864e5).toISOString(),
    newsLastPolledAt: new Date().toISOString(),
  };
  S.odds.quotes = [];
  S.filters.playMode = 'actionable';
});
await page.evaluate(() => window.dispatchEvent(new Event('resize')));
await page.waitForTimeout(400);
// renderBoard may not be exposed on window; flip the mode via the UI chip instead
const activeChip = await page.$('#mobileFilterStrip [data-mode="actionable"]');
if (activeChip) await activeChip.click().catch(() => {});
await page.waitForTimeout(400);
const emptyText = await page.evaluate(() => {
  const el = document.querySelector('#emptyState');
  return el ? el.textContent : '';
});
console.log('empty state visible   :', await page.$eval('#emptyState', (el) => !el.hidden).catch(() => 'n/a'));
console.log('paused copy present   :', /Live qualification paused/i.test(emptyText));
console.log('last trusted shown    :', /Last trusted quote/i.test(emptyText));
console.log('efficiency claim gone :', !/market is efficient/i.test(emptyText));

mkdirSync('../download', { recursive: true });
await page.screenshot({ path: '../download/headless_v145_paused_1280.png' });

// 4. desktop density at 1600 (badge visible again)
await page.setViewportSize({ width: 1600, height: 900 });
await page.waitForTimeout(300);
console.log('receipt badge @1600   :', await page.$eval('.pw-receipt-badge', (el) => getComputedStyle(el).display), '(expect flex)');

console.log('console/page errors   :', errors.length ? errors.slice(0, 5) : 'NONE');
await browser.close();
server.close();
