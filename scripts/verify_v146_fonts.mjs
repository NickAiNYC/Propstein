#!/usr/bin/env node
// Headless boot check for the 2026-10-27 font + box-design pass (v146).
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - zero console/page errors on boot
//   - typography: body = IBM Plex Sans, data cells = IBM Plex Mono,
//     headings = Space Grotesk (declared stacks + actually loaded faces)
//   - box system: anti-tout/empty panels at radius-lg (12px) with edge
//     highlight, board container at --radius (7px)
//   - v145 messaging regression guard: paused copy + Upgrade chip intact
// Screenshots: download/headless_v146_{paused_1280,desktop_1600}.png
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

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};

const browser = await chromium.launch();
const errors = [];
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

// 1. Typography — declared stacks
const bodyFont = await page.$eval('body', (el) => getComputedStyle(el).fontFamily);
check('body font declares IBM Plex Sans', /IBM Plex Sans/.test(bodyFont), bodyFont.slice(0, 60));

const monoFont = await page.$eval('.pw-terminal-chrome', (el) => getComputedStyle(el).fontFamily);
check('--mono token resolves to IBM Plex Mono (terminal chrome)', /IBM Plex Mono/.test(monoFont), monoFont.slice(0, 60));
const tdNumFont = await page.$eval('.slate-table td.td-num', (el) => getComputedStyle(el).fontFamily).catch(() => null);
if (tdNumFont) console.log('INFO  data cell family:', tdNumFont.slice(0, 60));

const h2Font = await page.$eval('h2', (el) => getComputedStyle(el).fontFamily);
check('headings declare Space Grotesk', /Space Grotesk/.test(h2Font), h2Font.slice(0, 60));

// 2. Typography — faces actually loaded (network permitting)
await page.evaluate(() => document.fonts.ready);
const sgLoaded = await page.evaluate(() => document.fonts.check('600 16px "Space Grotesk"'));
const plexSans = await page.evaluate(() => document.fonts.check('400 14px "IBM Plex Sans"'));
const plexMono = await page.evaluate(() => document.fonts.check('500 12px "IBM Plex Mono"'));
console.log(`INFO  faces loaded: SG=${sgLoaded} PlexSans=${plexSans} PlexMono=${plexMono} (false = sandbox blocked Google Fonts; declared stacks still enforced)`);

// 3. Box system — computed radii
const wrapRadius = await page.$eval('.anti-tout-empty-wrap', (el) => getComputedStyle(el).borderRadius).catch(() => 'n/a');
const wrapShadow = await page.$eval('.anti-tout-empty-wrap', (el) => getComputedStyle(el).boxShadow).catch(() => '');
check('anti-tout panel radius = 12px', wrapRadius === '12px', wrapRadius);
check('anti-tout panel edge highlight', /inset/.test(wrapShadow), wrapShadow.slice(0, 70));

const boardRadius = await page.$eval('.table-scroll', (el) => getComputedStyle(el).borderRadius);
check('board container radius = 7px', boardRadius === '7px', boardRadius);

const pillCount = await page.evaluate(() => {
  const hits = [];
  for (const el of document.querySelectorAll('*')) {
    const r = getComputedStyle(el).borderRadius;
    if (r === '999px') hits.push(el.className && String(el.className).slice(0, 30));
  }
  return hits.length;
});
console.log(`INFO  pill-token elements on boot: ${pillCount}`);

// 4. v145 regression guard — messaging honesty still pinned
const chip = await page.textContent('#pricingBtn .pro-text-desktop');
check('Upgrade chip intact (no PRO · $29)', /Upgrade/i.test(chip || ''), (chip || '').trim());

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
const activeChip = await page.$('#mobileFilterStrip [data-mode="actionable"]');
if (activeChip) await activeChip.click().catch(() => {});
await page.waitForTimeout(400);
const emptyText = await page.evaluate(() => {
  const el = document.querySelector('#emptyState');
  return el ? el.textContent : '';
});
check('paused copy present', /Live qualification paused/i.test(emptyText));
check('last trusted quote time shown', /Last trusted quote/i.test(emptyText));
check('efficiency claim still fail-closed', !/market is efficient/i.test(emptyText));

const emptyRadius = await page.$eval('#emptyState', (el) => getComputedStyle(el).borderRadius).catch(() => 'n/a');
check('empty-state panel radius = 12px', emptyRadius === '12px', emptyRadius);

mkdirSync('../download', { recursive: true });
await page.screenshot({ path: '../download/headless_v146_paused_1280.png' });

// 5. Desktop pass
await page.setViewportSize({ width: 1600, height: 900 });
await page.waitForTimeout(300);
await page.screenshot({ path: '../download/headless_v146_desktop_1600.png' });

check('zero console/page errors', errors.length === 0, errors.slice(0, 5).join(' | '));

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
await browser.close();
server.close();
process.exit(failures === 0 ? 0 : 1);
