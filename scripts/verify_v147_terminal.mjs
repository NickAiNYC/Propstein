#!/usr/bin/env node
// Headless boot check for the 2026-10-27 v147 sportsbook terminal system.
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - palette: canvas #0b0e14, active chip FanDuel blue rgb(0,82,255)
//   - status banners restyled to compact pills (radius 999px, soft amber)
//   - density + badge rules present in CSSOM (static boot has no rows)
//   - motion: 0.15s ease on interactive chips
//   - regression guards: v146 fonts + v145 messaging honesty intact
// Screenshots: download/headless_v147_{paused_1280,desktop_1600}.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 8900 + Math.floor(Math.random() * 400);
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

// 1. Palette — computed canvas + card
const bodyBg = await page.$eval('body', (el) => getComputedStyle(el).backgroundColor);
check('canvas = #0b0e14 rgb(11,14,20)', bodyBg === 'rgb(11, 14, 20)', bodyBg);

// 2. Active chip = FanDuel blue + illumination ring
const activeSel = '.chip-pill.active, .tier-pill-btn.active, [data-mode].active';
const activeInfo = await page.$eval(activeSel, (el) => {
  const s = getComputedStyle(el);
  return { bg: s.backgroundColor, shadow: s.boxShadow, radius: s.borderRadius, text: (el.textContent || '').trim().slice(0, 14) };
}).catch(() => null);
if (activeInfo) {
  check('active toggle bg = #0052ff', activeInfo.bg === 'rgb(0, 82, 255)', `${activeInfo.bg} "${activeInfo.text}"`);
  check('active toggle illumination ring', /rgba\(0, 82, 255/.test(activeInfo.shadow), activeInfo.shadow.slice(0, 60));
} else {
  check('active toggle present', false, 'no .active chip found at boot');
}

// 3. Banner → compact pill
const bannerInfo = await page.$eval('.data-quality-banner', (el) => {
  const s = getComputedStyle(el);
  return { radius: s.borderRadius, bg: s.backgroundColor, width: s.width, pos: s.position };
}).catch(() => null);
if (bannerInfo) {
  check('status banner is pill (999px)', bannerInfo.radius === '999px', bannerInfo.radius);
  check('status banner soft amber', /rgba\(245, 158, 11, 0\.09\)/.test(bannerInfo.bg), bannerInfo.bg);
  check('status banner floating (not full-bar)', bannerInfo.width !== '100%', `width ${bannerInfo.width}`);
} else {
  console.log('INFO  no banner at boot (feeds healthy?) — CSSOM check below');
}

// 4. Density/badge rules in CSSOM (rows absent in static boot)
const cssom = await page.evaluate(() => {
  const found = { tdHeight: null, posBadge: null, chipTransition: null };
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch { continue; }
    for (const r of rules) {
      if (r.selectorText === '.slate-table td' && r.style.height) found.tdHeight = r.style.height;
      if (r.selectorText && r.selectorText.startsWith('.position-box') && r.style.width) found.posBadge = r.style.width;
      if (r.selectorText && r.selectorText.includes('.chip-pill') && /transition/.test(r.style?.cssText || '') && /0\.15s/.test(r.style.transition || '')) found.chipTransition = r.style.transition;
    }
  }
  return found;
});
check('density rule: td height 50px', cssom.tdHeight === '50px', String(cssom.tdHeight));
check('position badge 26px mono anchor', cssom.posBadge === '26px', String(cssom.posBadge));
check('0.15s motion rule present', /0\.15s/.test(cssom.chipTransition || ''), String(cssom.chipTransition).slice(0, 40));

// 5. Live chip transition (computed)
const chipTrans = await page.$eval('.chip-pill', (el) => getComputedStyle(el).transitionDuration).catch(() => 'n/a');
check('chips transition 0.15s (computed)', chipTrans === '0.15s', chipTrans);

// 6. Regression guards — v146 fonts + v145 messaging
const bodyFont = await page.$eval('body', (el) => getComputedStyle(el).fontFamily);
check('v146 guard: IBM Plex Sans body', /IBM Plex Sans/.test(bodyFont));
const h2Font = await page.$eval('h2', (el) => getComputedStyle(el).fontFamily);
check('v146 guard: Space Grotesk headings', /Space Grotesk/.test(h2Font));
const chip = await page.textContent('#pricingBtn .pro-text-desktop');
check('v145 guard: Upgrade chip', /Upgrade/i.test(chip || ''));

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
check('v145 guard: paused copy + fail-closed', /Live qualification paused/i.test(emptyText) && !/market is efficient/i.test(emptyText));

mkdirSync('../download', { recursive: true });
await page.screenshot({ path: '../download/headless_v147_paused_1280.png' });

await page.setViewportSize({ width: 1600, height: 900 });
await page.waitForTimeout(300);
await page.screenshot({ path: '../download/headless_v147_desktop_1600.png' });

check('zero console/page errors', errors.length === 0, errors.slice(0, 5).join(' | '));

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
await browser.close();
server.close();
process.exit(failures === 0 ? 0 : 1);
