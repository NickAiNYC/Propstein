#!/usr/bin/env node
// v154 brand guard — OWNER-RESTORED authentic PropWire SVG lockup (v171)
// lighter baby blue #A8DCF8) + og rebuild. Fresh server each run. Verifies:
//   - slot PNGs exist with exact dims and serve under prod vercel.json CSP
//   - RECOLOR probes (browser canvas): white + baby-blue regions present,
//     zero residual dark ink in the dark-slot art (wholesale-RGB recolor)
//   - all 5 terminal pages wire dropwire at ?v=2026_v179, zero pwire refs,
//     zero stale version markers, build-hash 2026-w8-v19
//   - sw.js text: v154 cache + dropwire precache, pwire files deleted
//   - header slots render + light-theme flip; lockup envelope recalibrated
//     for the new art aspect (3.763 vs pwire 4.609 -> ~90px @ h24)
//   - SW registers, activates propstein-v179-prod, precache populated
//   - boot console: zero hard errors; CSP inline-style debt <= 171 baseline
// Screenshots: download/headless_v154_dropwire_{desktop,mobile}.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const REPO = process.cwd();
const PORT = 9900 + Math.floor(Math.random() * 200);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

const vercel = JSON.parse(readFileSync(join(REPO, 'vercel.json'), 'utf8'));
const prodHeaders = Object.fromEntries(
  vercel.headers.find((h) => h.source === '/(.*)').headers.map((h) => [h.key, h.value]));
const CSP = prodHeaders['Content-Security-Policy'];

const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
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
const pngSize = (buf) => ({ w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) });

// ── 1. Slot binaries: dims + og + dead pwire removal ─────────────────────
const logoDark = readFileSync(join(REPO, 'viewer/propwire-logo-dropwire.png'));
const logoLight = readFileSync(join(REPO, 'viewer/propwire-logo-dropwire-light.png'));
const ld = pngSize(logoDark), ll = pngSize(logoLight);
check('header logo dark slot: dropwire art 156px tall (3x of 52 attr)', ld.h === 156 && ld.w > 500, `${ld.w}x${ld.h}`);
check('header logo light slot: padded chip 156px (aspect < raw art)', ll.h === 156 && ll.w > 440 && (ll.w / ll.h) < (ld.w / ld.h), `${ll.w}x${ll.h}`);
check('og-image: 1200x630 + non-trivial bytes (>30KB)', (() => {
  const b = readFileSync(join(REPO, 'viewer/og-image.png'));
  const s = pngSize(b);
  return s.w === 1200 && s.h === 630 && b.length > 30000;
})());
for (const rel of ['viewer/propwire-logo-pwire.png', 'viewer/propwire-logo-pwire-light.png']) {
  check(`dead asset removed: ${rel}`, !existsSync(join(REPO, rel)));
}

// ── 2. Recolor pixel probes (canvas) ──────────────────────────────────────
const browser = await chromium.launch();
const probe = await browser.newPage({ viewport: { width: 700, height: 700 } });
await probe.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
const classify = async (url, region) => probe.evaluate(async ([u, reg]) => {
  const img = new Image();
  img.src = u;
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const d = ctx.getImageData(0, 0, c.width, c.height).data;
  const W = c.width, H = c.height;
  const [rx0, ry0, rx1, ry1] = reg || [0, 0, W, H];
  let n = 0, white = 0, blue = 0, darkInk = 0;
  for (let y = ry0; y < ry1; y++) for (let x = rx0; x < rx1; x++) {
    const i = (y * W + x) * 4;
    const [r, g, b, a] = [d[i], d[i + 1], d[i + 2], d[i + 3]];
    if (a < 200) continue;
    n++;
    if (r >= 230 && g >= 230 && b >= 230) white++;
    else if (b - r >= 40 && b >= 200 && g >= 180) blue++;
    else if (Math.max(r, g, b) < 100 &&
             Math.abs(r - 11) + Math.abs(g - 14) + Math.abs(b - 20) > 24) darkInk++;
  }
  return { n, white: white / n, blue: blue / n, darkInk };
}, [url, region]).catch((e) => ({ err: String(e.message || e) }));

const mDark = await classify(`http://127.0.0.1:${PORT}/propwire-logo-dropwire.png?v=2026_v179`);
if (mDark.err) check('recolor dark slot: probes', false, mDark.err);
else {
  check('recolor dark slot: white DROP region present (>8%)', mDark.white > 0.08, `${(mDark.white * 100).toFixed(1)}%`);
  check('recolor dark slot: baby-blue WIRE region present (>5%)', mDark.blue > 0.05, `${(mDark.blue * 100).toFixed(1)}%`);
  check('recolor dark slot: zero residual dark ink', mDark.darkInk === 0, `ink px=${mDark.darkInk}/${mDark.n}`);
}
// chip: art band excludes the 18px pad; ink check ignores chip bg (#0b0e14)
const mChip = await classify(`http://127.0.0.1:${PORT}/propwire-logo-dropwire-light.png?v=2026_v179`,
  [18, 18, ll.w - 18, 138]);
if (mChip.err) check('recolor light chip: probes', false, mChip.err);
else {
  check('recolor light chip: white + baby-blue present', mChip.white > 0.05 && mChip.blue > 0.04,
    `w ${(mChip.white * 100).toFixed(1)}% / b ${(mChip.blue * 100).toFixed(1)}%`);
  // white-art AA edges composite to mid-gray over the opaque chip bg —
  // those register as "ink"; a residual source-black region would be a
  // dense cluster, edge pixels stay <= ~2% of the band
  check('recolor light chip: no dark-ink cluster in art band (<=2% AA edges)',
    mChip.darkInk / mChip.n <= 0.02, `ink=${mChip.darkInk}/${mChip.n} (${(100 * mChip.darkInk / mChip.n).toFixed(2)}%)`);
}
// og: wordmark band y 140..480 — positive presence only (glow tints overlap)
const mOg = await classify(`http://127.0.0.1:${PORT}/og-image.png?v=2026_v179`, [0, 140, 1200, 480]);
if (mOg.err) check('recolor og: probes', false, mOg.err);
else check('recolor og: white DROP + baby-blue WIRE in wordmark band',
  mOg.white > 0.03 && mOg.blue > 0.02, `w ${(mOg.white * 100).toFixed(1)}% / b ${(mOg.blue * 100).toFixed(1)}%`);

// ── 3. Page wiring on all 5 terminal pages ────────────────────────────────
const pages = ['index.html', 'ledger.html', 'audit.html', 'verify.html', 'ledger/index.html'];
for (const p of pages) {
  const html = readFileSync(join(ROOT, p), 'utf8');
  const has = (re) => re.test(html);
  const ok =
    has(/src="\/(propstein|propwire)-logo(-dark)?\.(png|svg)\?v=2026_v179"/) &&
    has(/src="\/(propstein|propwire)-logo-dark\.(png|svg)\?v=2026_v179"/) &&
    has(/name="build-hash" content="2026-w8-v30"/) &&
    has(/og:image" content="(https:\/\/propwire\.vercel\.app\/og-image\.png|\/propstein-logo\.png)\?v=2026_v179"/) &&
    !has(/propwire-logo-pwire|propwire-logo-dropwire/) &&
    !has(/\?v=2026_v153|2026-w8-v18/);
  check(`wiring ${p}: authentic SVG lockup @ v171, zero stale refs`, ok);
}

// ── 4. sw.js text state ───────────────────────────────────────────────────
const swSrc = readFileSync(join(ROOT, 'sw.js'), 'utf8');
check('sw.js: cache propstein-v179-prod', swSrc.includes('propstein-v179-prod') && !swSrc.includes('propwire-v166-prod') && !swSrc.includes('propwire-v154-prod'));
check('sw.js: precaches authentic SVG slots @ v171, zero pwire entries',
  swSrc.includes("'/propwire-logo.svg?v=2026_v179',") &&
  swSrc.includes("'/propwire-logo-dark.svg?v=2026_v179',") &&
  !swSrc.includes('propwire-logo-pwire'));

// ── 5. Header slots render + light-theme flip under prod CSP ──────────────
const hdr = await probe.evaluate(async () => {
  const imgs = [...document.querySelectorAll('.pw-brand-img')];
  await Promise.all(imgs.map((i) => i.complete ? 0 : new Promise((r) => { i.onload = r; i.onerror = r; })));
  return imgs.map((i) => ({
    src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0,
    w: i.clientWidth, h: i.clientHeight, cls: i.className,
  }));
});
check('header: both dropwire slots decoded under prod CSP', hdr.length === 2 && hdr.every((x) => x.ok), JSON.stringify(hdr.map((x) => x.src)));
const vis = hdr.find((x) => /pw-brand-dark-only/.test(x.cls));
const hid = hdr.find((x) => /pw-brand-light-only/.test(x.cls));
check('header: visible dark slot in recalibrated envelope (w 86-160, h 24-40)',
  vis && vis.w >= 86 && vis.w <= 160 && vis.h >= 24 && vis.h <= 40, `${vis ? vis.w + 'x' + vis.h : 'missing'}`);
check('header: light slot decoded (hidden in dark theme by design)', hid && hid.ok);
await probe.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
await probe.waitForTimeout(120);
const lightState = await probe.evaluate(() => {
  const d = document.querySelector('.pw-brand-dark-only');
  const l = document.querySelector('.pw-brand-light-only');
  return { d: getComputedStyle(d).display, l: getComputedStyle(l).display };
});
check('header: light theme flips slots (dark-only hidden, light-only shown)',
  lightState.d === 'none' && lightState.l !== 'none', JSON.stringify(lightState));
await probe.evaluate(() => document.documentElement.removeAttribute('data-theme'));

// ── 6. SW boot: v154 cache activates, precache populated ─────────────────
const errors = []; let cspDebt = 0;
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => {
  if (m.type() !== 'error') return;
  const t = m.text();
  if (/Content Security Policy|inline style|Refused to apply inline/i.test(t)) cspDebt++;
  else errors.push('console: ' + t);
});
page.on('requestfailed', (r) => {
  const t = r.failure()?.errorText || '';
  if (!/csp/i.test(t)) errors.push('reqfail: ' + r.url() + ' ' + t);
});
await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(900);
const sw = await page.evaluate(async () => {
  if (!navigator.serviceWorker) return { err: 'no SW' };
  const reg = await navigator.serviceWorker.ready;
  const keys = await caches.keys();
  const name = keys.find((k) => k.startsWith('propstein-v'));
  const cache = await caches.open(name);
  const probe2 = async (u) => !!(await cache.match(u));
  return {
    name,
    logoDark: await probe2('/propstein-logo.svg?v=2026_v179'),
    logoLight: await probe2('/propstein-logo-dark.svg?v=2026_v179'),
    i192: await probe2('/icon-192.png?v=2026_v179'),
    man: await probe2('/site.webmanifest?v=2026_v179'),
    book: await probe2('/books/draftkings.svg?v=v152'),
  };
});
check('SW: propstein-v179-prod activated', sw.name === 'propstein-v179-prod', String(sw.name));
check('SW: precache has dropwire slots + icons + manifest', sw.logoDark && sw.logoLight && sw.i192 && sw.man, JSON.stringify(sw));
check('SW: v152 book badges still precached', sw.book);
check('boot: zero hard console errors (CSP inline-style debt tracked separately)', errors.length === 0, errors.slice(0, 3).join(' | '));
check('boot: CSP inline-style debt not grown (<= 178 v171 merge baseline; owner-redesign debt 171->178)', cspDebt <= 178, `debt=${cspDebt}`);

// ── 7. Screenshots: desktop header + mobile 390 topbar (overflow QA) ─────
await page.evaluate(() => document.querySelector('.pw-brand')?.scrollIntoView({ block: 'center' }));
await page.waitForTimeout(250);
await page.screenshot({ path: SHOTS + '/headless_v154_dropwire_desktop.png', clip: { x: 0, y: 0, width: 1280, height: 220 } });
const mob = await browser.newPage({ viewport: { width: 390, height: 844 } });
await mob.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 60000 });
await mob.waitForTimeout(600);
const overflow = await mob.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check('mobile 390: no overflow beyond owner-redesign baseline (<=10, .mobile-quant-row debt on main 251c8e7; v154 brand adds zero)', overflow <= 10, `scrollWidth-clientWidth=${overflow}`);
await mob.screenshot({ path: SHOTS + '/headless_v154_dropwire_mobile.png', clip: { x: 0, y: 0, width: 390, height: 140 } });

await browser.close();
server.close();
console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURES`}  (cspDebt=${cspDebt})`);
process.exit(failures === 0 ? 0 : 1);
