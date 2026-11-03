#!/usr/bin/env node
// Headless boot check for the 2026-10-28 v149 iPhone webapp pass.
// Fresh port each run (SW-cache trap discipline). Verifies:
//   - PWA manifest: valid JSON, standalone, #0b0e14 theme/background,
//     every declared icon URL resolves and is a real centered mark
//     (canvas pixel probe — the old set had the mark stuck in the corner)
//   - iOS head metas on all 5 terminal pages (capable / black-translucent /
//     title / viewport-fit=cover / theme-color #0b0e14 / manifest link)
//   - service worker: registers, activates propwire-v154-prod, and the
//     precache list actually populated (v148 bug: /manifest.json 404 made
//     addAll() silently precache NOTHING)
//   - standalone safe-area layer present in CSSOM (topbar spacer math
//     untouched from v148 — topbar stays exactly its designed height)
//   - iPhone 390x844 DPR3 boot: zero console errors, logo unclipped (34px),
//     bottom nav renders with safe-area calc height
// Screenshots: /home/z/my-project/download/headless_v149_*.png
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
const pngSize = (buf) => ({ w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) });

// ── 1. Manifest: parse + colors + display + icon URLs live ───────────────
const manifestRes = await fetch(`http://127.0.0.1:${PORT}/site.webmanifest?v=2026_v154`);
const manifest = JSON.parse(await manifestRes.text());
check('manifest: fetch 200 + valid JSON', manifestRes.ok && !!manifest.name);
check('manifest: display standalone', manifest.display === 'standalone');
check('manifest: theme_color #0b0e14', (manifest.theme_color || '').toLowerCase() === '#0b0e14');
check('manifest: background_color #0b0e14', (manifest.background_color || '').toLowerCase() === '#0b0e14');
check('manifest: scope / + start_url', manifest.scope === '/' && !!manifest.start_url);
check('manifest: id present (PWA identity)', !!manifest.id);
const iconChecks = [];
for (const ic of manifest.icons || []) {
  const r = await fetch(`http://127.0.0.1:${PORT}${ic.src}`);
  const buf = Buffer.from(await r.arrayBuffer());
  const isPng = buf.slice(1, 4).toString('latin1') === 'PNG';
  const isSvg = ic.type === 'image/svg+xml' && buf.slice(0, 5).toString('latin1').includes('<');
  iconChecks.push(r.ok && (isPng || isSvg) && !!ic.sizes);
}
check('manifest: all declared icons resolve as PNGs', iconChecks.length >= 3 && iconChecks.every(Boolean), `${iconChecks.length} icons`);

// ── 2. Icon pixel sanity: mark centered, not corner-stuck ────────────────
const browser = await chromium.launch();
// Navigate to a same-origin HTML document first — about:blank has an opaque
// origin (canvas taint) and an SVG document lacks the HTML canvas API.
const probe = await browser.newPage({ viewport: { width: 600, height: 600 } });
await probe.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
const pixelProbe = async (url, expW, expH) => {
  return probe.evaluate(async ([u, ew, eh]) => {
    const img = new Image();
    img.src = u;
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
    if (img.naturalWidth !== ew || img.naturalHeight !== eh) return { err: `size ${img.naturalWidth}x${img.naturalHeight}` };
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    const painted = (x0, y0, x1, y1) => {
      let n = 0, tot = 0;
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
        const i = (y * c.width + x) * 4;
        tot++;
        if (Math.abs(d[i] - 11) + Math.abs(d[i + 1] - 14) + Math.abs(d[i + 2] - 20) > 72) n++;
      }
      return n / tot;
    };
    const S = c.width;
    return {
      center: painted(Math.round(S * 0.2), Math.round(S * 0.2), Math.round(S * 0.8), Math.round(S * 0.8)),
      corner: painted(0, 0, Math.round(S * 0.12), Math.round(S * 0.12)),
    };
  }, [url, expW, expH]).catch((e) => ({ err: String(e.message || e) }));
};
for (const [url, w, h, minCenter] of [
  ['/apple-touch-icon.png?v=2026_v154', 180, 180, 0.06],
  ['/icon-192.png?v=2026_v154', 192, 192, 0.04],
  ['/icon-512.png?v=2026_v154', 512, 512, 0.04],
]) {
  const m = await pixelProbe(`http://127.0.0.1:${PORT}${url}`, w, h);
  if (m.err) { check(`icon ${url}: pixel probe`, false, m.err); continue; }
  check(`icon ${url}: exact ${w}x${h}`, true);
  check(`icon ${url}: mark centered (center painted ${(m.center * 100).toFixed(1)}% > corner ${(m.corner * 100).toFixed(1)}%)`,
    m.center > minCenter && m.corner < 0.04);
}
await probe.close();

// ── 3. iOS head metas on all 5 terminal pages ────────────────────────────
const pages = ['index.html', 'ledger.html', 'audit.html', 'verify.html', 'ledger/index.html'];
for (const p of pages) {
  const html = readFileSync(join(ROOT, p), 'utf8');
  const has = (re) => re.test(html);
  const ok =
    has(/name="apple-mobile-web-app-capable" content="yes"/) &&
    has(/name="apple-mobile-web-app-status-bar-style" content="black-translucent"/) &&
    has(/name="apple-mobile-web-app-title" content="PropWire"/) &&
    has(/viewport-fit=cover/) &&
    has(/name="theme-color" content="#0b0e14"/) &&
    has(/rel="manifest" href="\/site\.webmanifest\?v=2026_v154"/) &&
    has(/rel="apple-touch-icon" href="\/apple-touch-icon\.png\?v=2026_v154"/);
  check(`head ${p}: full iOS PWA meta set`, ok);
}

// ── 4. SW: registers, activates v149 cache, precache actually populated ──
const errors = [];
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
const sw = await page.evaluate(async () => {
  if (!('serviceWorker' in navigator)) return { err: 'no SW support' };
  const reg = await navigator.serviceWorker.ready;
  const keys = await caches.keys();
  const target = keys.find((k) => k === 'propwire-v154-prod');
  if (!target) return { err: 'v149 cache missing', keys };
  const cache = await caches.open(target);
  const entries = await cache.keys();
  const urls = entries.map((r) => new URL(r.url).pathname + (new URL(r.url).search || ''));
  const hasManifest = await cache.match('/site.webmanifest?v=2026_v154');
  const hasBustedCss = await cache.match('/style.css?v=2026_v154');
  return { cache: target, count: entries.length, hasManifest: !!hasManifest, hasBustedCss: !!hasBustedCss, urls };
});
if (sw.err) check('service worker v149: activated + precached', false, sw.err + ' ' + JSON.stringify(sw.keys || ''));
else {
  check('service worker: propwire-v154-prod active', true);
  check('precache: populated (v148 silent-empty bug fixed)', sw.count >= 10, `${sw.count} entries`);
  check('precache: /site.webmanifest?v=2026_v154 present', sw.hasManifest);
  check('precache: /style.css?v=2026_v154 present', sw.hasBustedCss);
}

// ── 5. Standalone safe-area layer in CSSOM ───────────────────────────────
const cssom = await page.evaluate(() => {
  let found = null;
  const scan = (rules) => {
    for (const r of rules) {
      if (r.media && /display-mode.*standalone/.test(r.media.mediaText)) {
        for (const inner of r.cssRules || []) {
          if (inner.selectorText && inner.selectorText.includes('.pw-terminal-chrome') && /safe-area-inset-top/.test(inner.cssText)) {
            found = inner.cssText.slice(0, 120);
          }
        }
      }
      if (r.cssRules) try { scan(r.cssRules); } catch {}
    }
  };
  for (const sheet of document.styleSheets) {
    try { scan(sheet.cssRules); } catch {}
  }
  return found;
});
check('CSSOM: standalone safe-area topbar spacer present', !!cssom, cssom || 'rule not found');

// ── 6. iPhone boot: chrome structure + logo + bottom nav + zero errors ───
const boot = await page.evaluate(() => {
  const bar = document.querySelector('.pw-topbar');
  const img = document.querySelector('.pw-brand-img.pw-brand-dark-only') || document.querySelector('.pw-brand-img');
  const nav = document.querySelector('.mobile-bottom-nav');
  const ir = img ? img.getBoundingClientRect() : null;
  const br = bar ? bar.getBoundingClientRect() : null;
  return {
    barH: br ? +br.height.toFixed(1) : null,
    imgH: ir ? +ir.height.toFixed(1) : null,
    logoOk: ir && br ? ir.top >= br.top - 0.6 && ir.bottom <= br.bottom + 0.6 : false,
    navH: nav ? +nav.getBoundingClientRect().height.toFixed(1) : null,
    themeColor: document.querySelector('meta[name="theme-color"]')?.content,
    buildHash: document.querySelector('meta[name="build-hash"]')?.content,
  };
});
check('iphone 390: topbar height = designed mobile 48px', boot.barH !== null && boot.barH >= 45 && boot.barH <= 50, String(boot.barH));
check('iphone 390: logo unclipped inside topbar', boot.logoOk, `img ${boot.imgH}px / bar ${boot.barH}px`);
check('iphone 390: bottom nav renders w/ safe-area calc', boot.navH !== null && boot.navH >= 57 && boot.navH <= 60, String(boot.navH));
check('iphone 390: theme-color #0b0e14 + build-hash 2026-w8-v19', boot.themeColor === '#0b0e14' && boot.buildHash === '2026-w8-v19', `theme=${boot.themeColor} hash=${boot.buildHash}`);
check('iphone 390: zero console/page errors', errors.length === 0, errors.slice(0, 3).join(' | ') || 'clean');

await page.screenshot({ path: join(SHOTS, 'headless_v149_iphone_390.png'), clip: { x: 0, y: 0, width: 390, height: 500 } });

// Desktop sanity screenshot (fresh page, wide)
const desk = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await desk.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await desk.waitForTimeout(1200);
await desk.screenshot({ path: join(SHOTS, 'headless_v149_desktop_1600.png'), clip: { x: 0, y: 0, width: 1600, height: 400 } });
await desk.close();

await browser.close();
server.close();

console.log('─'.repeat(60));
if (failures) { console.log(`v149 iOS harness: ${failures} FAILURES`); process.exit(1); }
console.log('v149 iOS harness: ALL PASS');
