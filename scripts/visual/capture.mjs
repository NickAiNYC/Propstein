#!/usr/bin/env node
// Visual regression capture for the viewer (CSS refactor safety net).
//
//   node scripts/visual/capture.mjs <outDir> [--only <name-substring>]
//
// Determinism, so two captures of the same tree are pixel-identical:
// - Page code (HTML/CSS/JS/images) comes from the working tree: that is what a
//   refactor changes and what we want to compare.
// - Every .json/.csv is served from ONE pinned git commit (scripts/visual/data-ref),
//   because the autopilot commits fresh slates/odds several times a day.
// - Date.now() is fixed to that commit's timestamp (feed-freshness copy depends on it).
// - All cross-origin requests (Google Fonts, ESPN/NBA headshots) are aborted, so
//   fallback fonts and initials avatars are used on every run.
// - Animations/transitions/caret are disabled; the service worker is blocked.
//
// Baselines are machine-specific (font rendering differs by OS), so they are not
// committed: record on the commit you start from, then check after each change.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const VIEWER = path.join(ROOT, 'viewer');
const args = process.argv.slice(2);
const outDir = path.resolve(ROOT, args[0] || '.visual/actual');
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;

const DATA_REF = fs.readFileSync(path.join(ROOT, 'scripts/visual/data-ref'), 'utf8').trim();
const FIXED_TIME = execFileSync('git', ['log', '-1', '--format=%cI', DATA_REF], { cwd: ROOT }).toString().trim();

// ---- static server --------------------------------------------------------
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.css': 'text/css', '.json': 'application/json', '.csv': 'text/csv', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2' };
const REWRITES = { '/': '/index.html', '/ledger': '/index.html', '/audit': '/index.html', '/verify': '/verify.html' };
const pinned = new Map();

function pinnedData(rel) {
  if (!pinned.has(rel)) {
    try {
      pinned.set(rel, execFileSync('git', ['show', `${DATA_REF}:viewer/${rel}`], { cwd: ROOT, maxBuffer: 64 << 20, stdio: ['ignore', 'pipe', 'ignore'] }));
    } catch { pinned.set(rel, null); }
  }
  return pinned.get(rel);
}

function resolveFile(urlPath) {
  let p = REWRITES[urlPath] || urlPath;
  if (p.endsWith('/')) p += 'index.html';
  const abs = path.join(VIEWER, p);
  if (!abs.startsWith(VIEWER)) return null;
  if (fs.existsSync(abs) && fs.statSync(abs).isFile()) return abs;
  if (!path.extname(abs) && fs.existsSync(`${abs}.html`)) return `${abs}.html`;
  return null;
}

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const ext = path.extname(urlPath).toLowerCase();
  if (ext === '.json' || ext === '.csv') {
    const body = pinnedData(urlPath.replace(/^\/+/, ''));
    if (!body) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'content-type': TYPES[ext], 'cache-control': 'no-store' }).end(body);
    return;
  }
  const file = resolveFile(urlPath);
  if (!file) { res.writeHead(404).end(); return; }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-store' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;

// ---- scenarios --------------------------------------------------------------
const VIEWPORTS = {
  mobile: { viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  desktop: { viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 },
};
const BLANK_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
const MAX_PAGE_HEIGHT = 4000; // the board is very long; the top 4000px covers every component type

const settle = async (page) => {
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
};
// Re-shoot until two consecutive screenshots are byte-identical (what Playwright's own
// toHaveScreenshot does): raster of clipped/scrolling strips can lag a frame behind.
const stableShot = async (page, file, opts = {}) => {
  let prev = null;
  for (let i = 0; i < 8; i += 1) {
    const buf = await page.screenshot(opts);
    if (prev && buf.equals(prev)) { fs.writeFileSync(file, buf); return; }
    prev = buf;
    await page.waitForTimeout(150);
  }
  throw new Error(`${path.basename(file)}: page never reached a stable frame`);
};
// Script-driven motion (e.g. the mobile bottom-sheet dialogs) is not covered by the
// animation-off stylesheet: finish every Web Animation, then wait until every open
// dialog's box has stopped moving for a few frames.
const finishMotion = async (page) => {
  await page.evaluate(async () => {
    const boxes = () => [...document.querySelectorAll('dialog[open]')]
      .map((d) => { const r = d.getBoundingClientRect(); return `${r.x},${r.y},${r.width},${r.height}`; }).join('|');
    const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
    let last = null; let still = 0;
    for (let i = 0; i < 120 && still < 5; i += 1) {
      document.getAnimations().forEach((anim) => { try { anim.finish(); } catch (_) { /* infinite */ anim.cancel(); } });
      await frame();
      const now = boxes();
      still = now === last ? still + 1 : 0;
      last = now;
    }
  });
};
const viewportShot = (page, file) => stableShot(page, file);
const fullTop = async (page, file) => {
  const h = await page.evaluate(() => document.documentElement.scrollHeight);
  const { width } = page.viewportSize();
  await stableShot(page, file, { fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(h, MAX_PAGE_HEIGHT) } });
};
const openDialog = (id) => (page) => page.evaluate((d) => { const el = document.getElementById(d); if (el && !el.open) el.showModal(); }, id);

const SCENARIOS = [
  { name: 'home', path: '/', shot: fullTop },
  { name: 'home-scrolled-header', path: '/', vp: ['mobile'], before: async (page) => {
      for (let y = 0; y <= 900; y += 60) { await page.evaluate((v) => window.scrollTo(0, v), y); await page.waitForTimeout(30); }
      await page.waitForTimeout(500);
    }, shot: viewportShot },
  { name: 'board-cards', path: '/', vp: ['desktop'], before: async (page) => { await page.click('[data-view="cards"]'); await settle(page); }, shot: fullTop },
  { name: 'board-table', path: '/', vp: ['desktop'], before: async (page) => { await page.click('[data-view="table"]'); await settle(page); }, shot: fullTop },
  { name: 'dialog-pricing', path: '/', before: openDialog('pricingDialog'), shot: viewportShot },
  { name: 'dialog-settings', path: '/', before: openDialog('settingsDialog'), shot: viewportShot },
  { name: 'dialog-detail', path: '/', before: async (page) => {
      await page.evaluate(() => document.querySelector('[data-testid="slate-card"]')?.scrollIntoView());
      await page.click('[data-testid="slate-card"] .card-player-name');
      await page.waitForSelector('#detailDialog[open]');
      await page.waitForTimeout(300);
    }, shot: viewportShot },
  { name: 'ledger', path: '/ledger.html', shot: fullTop },
  { name: 'audit', path: '/audit.html', shot: fullTop },
];

// ---- run --------------------------------------------------------------------
fs.mkdirSync(outDir, { recursive: true });
// Software rasterization + fixed color profile: GPU raster made backdrop-filter blur
// (bottom nav, dialog backdrops) differ by a few pixels between identical runs.
const browser = await chromium.launch({ channel: 'chromium', args: [
  '--disable-gpu', '--disable-gpu-rasterization', '--force-color-profile=srgb',
  '--disable-lcd-text', '--font-render-hinting=none', '--disable-partial-raster',
  '--disable-threaded-scrolling', '--disable-checker-imaging'] });
let count = 0;
try {
  for (const s of SCENARIOS) {
    for (const [vpName, vpOpts] of Object.entries(VIEWPORTS)) {
      if (s.vp && !s.vp.includes(vpName)) continue;
      const name = `${s.name}--${vpName}`;
      if (only && !name.includes(only)) continue;
      const context = await browser.newContext({ ...vpOpts, reducedMotion: 'reduce', serviceWorkers: 'block',
        colorScheme: 'dark', locale: 'en-US', timezoneId: 'America/New_York' });
      // Cross-origin requests never reach the network. Images get an instant transparent
      // pixel and stylesheets empty CSS: an aborted <img> paints its broken state at a
      // timing-dependent moment, which made the ESPN team badges flicker between runs.
      await context.route('**/*', (route) => {
        const req = route.request();
        if (req.url().startsWith(ORIGIN)) return route.continue();
        const type = req.resourceType();
        if (type === 'image') return route.fulfill({ status: 200, contentType: 'image/png', body: BLANK_PNG });
        if (type === 'stylesheet') return route.fulfill({ status: 200, contentType: 'text/css', body: '' });
        return route.abort();
      });
      const page = await context.newPage();
      await page.clock.setFixedTime(new Date(FIXED_TIME));
      await page.goto(ORIGIN + s.path, { waitUntil: 'load' });
      await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}' });
      await settle(page);
      if (s.before) { await s.before(page); await settle(page); }
      // showModal() focuses the close button; a focus ring is state, not layout.
      await page.evaluate(() => document.activeElement && document.activeElement !== document.body && document.activeElement.blur());
      await page.mouse.move(0, 0);
      await finishMotion(page);
      await s.shot(page, path.join(outDir, `${name}.png`));
      await context.close();
      count += 1;
      process.stdout.write(`  captured ${name}\n`);
    }
  }
} finally {
  await browser.close();
  server.close();
}
console.log(`${count} screenshots -> ${path.relative(ROOT, outDir)} (data @ ${DATA_REF.slice(0, 8)}, clock ${FIXED_TIME})`);
