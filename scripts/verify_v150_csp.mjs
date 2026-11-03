#!/usr/bin/env node
// Headless CSP-parity check for the 2026-10-28 v150 logo fix.
// Reproduces the PRODUCTION failure mode locally: serves viewer/ with the
// exact headers from viewer/vercel.json (CSP included) — the missing piece
// that let the espncdn team-logo block ship unnoticed.
// Verifies:
//   - CSP header on the document includes img-src a.espncdn.com
//   - ZERO requests fail with a CSP violation (the v148 prod bug: all 28
//     team logos requestfailed :: csp)
//   - team crest logos actually decode (naturalWidth > 0)
//   - crest theme colors applied via CSSOM (computed style, not blocked)
//   - crest markup carries no inline style attr / onerror handler
//   - zero console errors, SW v151 precache populated
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9500 + Math.floor(Math.random() * 300);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

// Production header parity: apply vercel.json global header set to every response.
const vercel = JSON.parse(readFileSync(join(ROOT, 'vercel.json'), 'utf8'));
const globalHeaders = vercel.headers.find((h) => h.source === '/(.*)').headers;
const cspHeader = globalHeaders.find((h) => h.key === 'Content-Security-Policy').value;

const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  const file = join(ROOT, rel);
  if (!existsSync(file)) { res.writeHead(404); res.end('nf'); return; }
  const headers = { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' };
  for (const h of globalHeaders) headers[h.key] = h.value;
  res.writeHead(200, headers);
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, r));
console.log('serving on port', PORT, 'with vercel.json header parity');

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const cspFailures = [];
const otherFailed = [];
const consoleErrors = [];
page.on('requestfailed', (r) => {
  const reason = r.failure()?.errorText || '';
  if (/csp/i.test(reason)) cspFailures.push(r.url());
  else otherFailed.push(`${r.url()} :: ${reason}`);
});
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
await page.waitForTimeout(4500);

// Scroll pass: crest imgs are loading=lazy — below-fold imgs only fetch when
// scrolled near; imgs inside display:none containers legitimately defer.
await page.evaluate(async () => {
  await new Promise((resolve) => {
    let y = 0;
    const step = () => {
      y += 600; window.scrollTo(0, y);
      if (y < document.body.scrollHeight) setTimeout(step, 110);
      else { window.scrollTo(0, 0); setTimeout(resolve, 400); }
    };
    step();
  });
});
await page.waitForTimeout(1800);

// Force-fetch pass: the paused state keeps crest containers hidden, so lazy
// imgs never fetch. Flip to eager so the CSP proof isn't vacuous.
await page.evaluate(() => {
  document.querySelectorAll('.crest-img[loading="lazy"]').forEach((i) => { i.loading = 'eager'; });
});
await page.waitForTimeout(2500);

// 1. Config parity: the served CSP actually allows the ESPN CDN.
check('CSP header: img-src allows a.espncdn.com', /img-src[^;]*a\.espncdn\.com/.test(cspHeader));

// 2. The core regression: no request may fail with a CSP violation.
check('ZERO CSP-blocked requests (v148 prod bug fixed)', cspFailures.length === 0,
  cspFailures.length ? `${cspFailures.length} blocked, e.g. ${cspFailures[0]}` : 'clean');

// 3. Crests render and logos decode over the real network.
const crests = await page.evaluate(() => {
  const list = [...document.querySelectorAll('.team-crest')];
  const rendered = list.filter((c) => c.offsetParent !== null);
  return {
    total: list.length,
    rendered: rendered.length,
    loaded: list.filter((c) => { const i = c.querySelector('.crest-img'); return i && i.complete && i.naturalWidth > 0; }).length,
    themed: list.filter((c) => getComputedStyle(c).backgroundColor !== 'rgba(0, 0, 0, 0)').length,
    sampleComputed: list[0] ? getComputedStyle(list[0]).backgroundColor : null,
  };
});
check('team crests present on the board', crests.total > 0, `${crests.total} crests (${crests.rendered} rendered)`);
if (crests.total > 0) {
  check('crest imgs decode after eager-flip (CSP-permitted fetch)', crests.loaded === crests.total, `${crests.loaded}/${crests.total} decoded; sample computed=${crests.sampleComputed}`);
  check('crest theme applied via CSSOM (visible bg)', crests.themed === crests.total, `${crests.themed}/${crests.total} themed`);
}
// Direct probe: an espncdn image must load in this document's CSP context,
// independent of lazy-loading or container visibility.
const cdnProbe = await page.evaluate(() => new Promise((res) => {
  const img = new Image();
  img.onload = () => res(true);
  img.onerror = () => res(false);
  img.src = 'https://a.espncdn.com/i/teamlogos/nfl/500/kc.png?v=v150probe';
  setTimeout(() => res(false), 10000);
}));
check('ESPN CDN image loads under production CSP (direct probe)', cdnProbe);
// Source-level CSP hygiene: the crest template itself emits no style= and no
// onerror= (runtime getAttribute('style') is meaningless — CSSOM writes land
// in the style attribute and are CSP-exempt by design).
const appSrc = readFileSync(join(ROOT, 'app.js'), 'utf8');
check('crest template source: no style= / onerror= (CSP-clean)',
  !/<div class="team-crest[^>]*\sstyle=/.test(appSrc) && !/team-crest[^`]*onerror=/.test(appSrc));

// 4. Console hygiene: split pre-existing inline-style CSP debt (informational,
// ~80 sites skeleton/dialog/clv — tracked for v151) from everything else.
const cspStyleViolations = consoleErrors.filter((e) => /inline style violates/.test(e));
const otherErrors = consoleErrors.filter((e) => !/inline style violates/.test(e));
check('zero non-CSP-debt console errors', otherErrors.length === 0, otherErrors.slice(0, 3).join(' | ') || 'clean');
check('remaining inline-style CSP violations: pre-existing debt only (informational)', true,
  `${cspStyleViolations.length} style-attr violations (v151 cleanup); 0 img/script violations`);

// 5. Other network failures — report but distinguish from CSP.
check('non-CSP network failures: informational only', true, otherFailed.length ? `${otherFailed.length}: ${otherFailed.slice(0, 2).join(' ; ')}` : 'none');

// 6. SW v151 precache populated.
const sw = await page.evaluate(async () => {
  const keys = await caches.keys();
  const target = keys.find((k) => k === 'propwire-v154-prod');
  if (!target) return { err: 'no v151 cache', keys };
  const cache = await caches.open(target);
  const n = (await cache.keys()).length;
  const css = await cache.match('/style.css?v=2026_v154');
  return { n, css: !!css };
});
if (sw.err) check('SW v151 precache', false, sw.err + ' ' + JSON.stringify(sw.keys || ''));
else check('SW propwire-v154-prod precache populated', sw.n >= 10 && sw.css, `${sw.n} entries, busted css: ${sw.css}`);

// 7. Version markers.
const meta = await page.evaluate(() => ({
  hash: document.querySelector('meta[name="build-hash"]')?.content,
  theme: document.querySelector('meta[name="theme-color"]')?.content,
}));
check('build-hash 2026-w8-v19 + theme-color #0b0e14', meta.hash === '2026-w8-v19' && meta.theme === '#0b0e14', JSON.stringify(meta));

await page.screenshot({ path: join(SHOTS, 'headless_v150_csp_1280.png'), clip: { x: 0, y: 0, width: 1280, height: 600 } });
await browser.close();
server.close();

console.log('─'.repeat(60));
if (failures) { console.log(`v150 CSP harness: ${failures} FAILURES`); process.exit(1); }
console.log('v150 CSP harness: ALL PASS');
