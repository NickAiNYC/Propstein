#!/usr/bin/env node
// Headless boot check for the 2026-10-27 v148 owner revision pass.
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - BRAND FIX: .pw-brand-img renders unclipped inside .pw-brand and
//     .pw-topbar at 1280/1600/390 (P-stem clearance guard, was 7px cut)
//   - mint accent layer: active toggles rgba(16,185,129,.16)/#6ee7b7,
//     focus rail #3ccf91, live ping ring green, bullet marker #3ccf91
//   - regression guards: v147 canvas + pills + density + motion,
//     v146 fonts, v145 messaging honesty
// Screenshots: download/headless_v148_{paused_1280,desktop_1600}.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9300 + Math.floor(Math.random() * 400);
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

// ── 1. BRAND FIX: P-stem clearance at every probed width ────────────────
const logoCheck = async (vw, expectH) => {
  const m = await page.evaluate(() => {
    const img = document.querySelector('.pw-brand-img.pw-brand-dark-only') || document.querySelector('.pw-brand-img');
    if (!img) return { err: 'no brand img' };
    const ir = img.getBoundingClientRect();
    const chip = img.closest('.pw-brand').getBoundingClientRect();
    const bar = document.querySelector('.pw-topbar').getBoundingClientRect();
    const eps = 0.6;
    return {
      h: +ir.height.toFixed(1),
      insideChip: ir.top >= chip.top - eps && ir.bottom <= chip.bottom + eps && ir.left >= chip.left - eps && ir.right <= chip.right + eps,
      insideBar: ir.top >= bar.top - eps && ir.bottom <= bar.bottom + eps,
      tileInsideBar: chip.top >= bar.top - eps && chip.bottom <= bar.bottom + eps,
      chipH: +chip.height.toFixed(1), barH: +bar.height.toFixed(1),
    };
  });
  if (m.err) { check(`logo @${vw}: img present`, false, m.err); return; }
  check(`logo @${vw}: unclipped inside brand tile`, m.insideChip, JSON.stringify(m));
  check(`logo @${vw}: unclipped inside topbar`, m.insideBar, `img ${m.h}px / bar ${m.barH}px`);
  check(`logo @${vw}: brand tile flush with topbar (no poke-out)`, m.tileInsideBar, `chip ${m.chipH}px / bar ${m.barH}px`);
  check(`logo @${vw}: lockup height ${expectH}px preserved`, Math.abs(m.h - expectH) < 1, String(m.h));
};
await logoCheck(1280, 52);

// ── 2. Palette — computed canvas (v147 guard) ───────────────────────────
const bodyBg = await page.$eval('body', (el) => getComputedStyle(el).backgroundColor);
// v154 merge re-pin: invariant 2027 redesign (5f2e1ef) moved the canvas
// token to obsidian rgb(7,7,9) — deliberate owner drift, new baseline
check('canvas = obsidian rgb(7,7,9) (2027 redesign baseline)', bodyBg === 'rgb(7, 7, 9)', bodyBg);

// ── 3. Active toggles = mint accent layer ───────────────────────────────
const activeSel = '.chip-pill.active, .tier-pill-btn.active, .pw-seg-btn.active, .sport-switcher-bar .active';
const activeInfo = await page.$eval(activeSel, (el) => {
  const s = getComputedStyle(el);
  return { bg: s.backgroundColor, color: s.color, shadow: s.boxShadow, text: (el.textContent || '').trim().slice(0, 14) };
}).catch(() => null);
if (activeInfo) {
  check('active toggle bg = mint rgba(16,185,129,.16)', activeInfo.bg === 'rgba(16, 185, 129, 0.16)', `${activeInfo.bg} "${activeInfo.text}"`);
  check('active toggle text = #6ee7b7', activeInfo.color === 'rgb(110, 231, 183)', activeInfo.color);
  check('active toggle mint illumination ring', /rgba\(16, 185, 129/.test(activeInfo.shadow), activeInfo.shadow.slice(0, 60));
} else {
  check('active toggle present', false, 'no .active chip found at boot');
}

// ── 4. Banner → compact pill (v147 guard) ───────────────────────────────
const bannerInfo = await page.$eval('.data-quality-banner', (el) => {
  const s = getComputedStyle(el);
  return { radius: s.borderRadius, bg: s.backgroundColor, width: s.width };
}).catch(() => null);
if (bannerInfo) {
  check('status banner is pill (999px)', bannerInfo.radius === '999px', bannerInfo.radius);
  check('status banner soft amber', /rgba\(245, 158, 11, 0\.09\)/.test(bannerInfo.bg), bannerInfo.bg);
  check('status banner floating (not full-bar)', bannerInfo.width !== '100%', `width ${bannerInfo.width}`);
} else {
  console.log('INFO  no banner at boot (feeds healthy?) — CSSOM check below');
}

// ── 5. CSSOM: mint details + v147 density (rows absent in static boot) ──
const cssom = await page.evaluate(() => {
  const found = { tdHeight: null, posBadge: null, chipTransition: null, navActive: null, projMarker: null, focusRail: null, pingRing: null };
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch { continue; }
    for (const r of rules) {
      const sel = r.selectorText || '';
      if (sel === '.slate-table td' && r.style.height) found.tdHeight = r.style.height;
      if (sel.startsWith('.position-box') && r.style.width) found.posBadge = r.style.width;
      if (sel.includes('.chip-pill') && /transition/.test(r.style?.cssText || '') && /0\.15s/.test(r.style.transition || '')) found.chipTransition = r.style.transition;
      if (sel === '.bottom-nav-item.active' && r.style.color) found.navActive = r.style.color;
      if (sel === '.bullet-svg .bullet-proj-marker' && r.style.fill) found.projMarker = r.style.fill;
      if (sel.includes('keyboard-focus') && sel.includes('td:first-child') && r.style.borderLeft) found.focusRail = r.style.borderLeft;
      if (sel.includes('.polling-dot::after') && r.style.borderColor) found.pingRing = r.style.borderColor;
    }
  }
  return found;
});
check('density rule: td height 50px', cssom.tdHeight === '50px', String(cssom.tdHeight));
check('position badge 26px mono anchor', cssom.posBadge === '26px', String(cssom.posBadge));
check('0.15s motion rule present', /0\.15s/.test(cssom.chipTransition || ''), String(cssom.chipTransition).slice(0, 40));
// v154 merge re-pin: redesign accent = electric chartreuse rgb(212,251,17)
check('bottom-nav active = chartreuse text (2027 redesign baseline)', cssom.navActive === 'rgb(212, 251, 17)', String(cssom.navActive));
check('bullet projection marker = #3ccf91', cssom.projMarker === 'rgb(60, 207, 145)', String(cssom.projMarker));
check('keyboard focus rail = mint #3ccf91', /rgb\(60, 207, 145\)/.test(cssom.focusRail || ''), String(cssom.focusRail));
check('live ping ring = mint', /rgba\(52, 211, 153/.test(cssom.pingRing || ''), String(cssom.pingRing));

// ── 6. Live chip transition (computed, v147 guard) ──────────────────────
const chipTrans = await page.$eval('.chip-pill', (el) => getComputedStyle(el).transitionDuration).catch(() => 'n/a');
check('chips transition 0.15s (computed)', chipTrans === '0.15s', chipTrans);

// ── 7. Regression guards — v146 fonts + v145 messaging ──────────────────
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
await page.screenshot({ path: '../download/headless_v148_paused_1280.png' });

await page.setViewportSize({ width: 1600, height: 900 });
await page.waitForTimeout(300);
await logoCheck(1600, 52);
await page.screenshot({ path: '../download/headless_v148_desktop_1600.png' });
const tb = await page.$('.pw-topbar');
if (tb) await tb.screenshot({ path: '../download/headless_v148_topbar_1600.png' });

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
await logoCheck(390, 34);

check('zero console/page errors', errors.length === 0, errors.slice(0, 5).join(' | '));

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
await browser.close();
server.close();
process.exit(failures === 0 ? 0 : 1);
