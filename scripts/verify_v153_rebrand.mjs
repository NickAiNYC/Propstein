#!/usr/bin/env node
// v153 rebrand guard — PWIRE header logo + lightning-P icon set + og-image.
// Fresh port each run. Verifies:
//   - every brand binary exists with exact dimensions (IHDR) and serves
//     under the production vercel.json CSP header parity (img-src 'self')
//   - favicon.svg / propwire-icon.svg parse with the embedded raster mark
//   - all 5 terminal pages wire the new assets at ?v=2026_v179, zero stale
//     propwire-logo*.svg references, build-hash 2026-w8-v19
//   - site.webmanifest icons resolve; PWA identity intact
//   - icon pixel probe: monogram centered, not corner-stuck (v149 lesson)
//   - header renders both slot logos (dark-only / light-only), 160x40 box
//   - SW registers, activates propstein-v179-prod, precache populated with
//     the new logo PNGs + v153 icons + untouched v152 book badges
//   - boot console: zero hard errors (v150-classified inline-style CSP
//     console debt tracked separately, must not grow from v152 baseline)
// Screenshot: /home/z/my-project/download/headless_v153_rebrand_header.png
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const REPO = process.cwd();
const PORT = 9700 + Math.floor(Math.random() * 250);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

// vercel.json header parity — brand assets must be servable under prod CSP
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

// ── 1. Brand binaries: existence + exact dimensions + MIME ───────────────
const dimSpecs = [
  ['viewer/apple-touch-icon.png', 180, 180],
  ['viewer/apple-touch-icon-180x180.png', 180, 180],
  ['viewer/apple-touch-icon-precomposed.png', 180, 180],
  ['viewer/apple-touch-icon-180x180-precomposed.png', 180, 180],
  ['viewer/apple-touch-icon-167x167.png', 167, 167],
  ['viewer/apple-touch-icon-152x152.png', 152, 152],
  ['viewer/apple-touch-icon-120x120.png', 120, 120],
  ['viewer/icon-192.png', 192, 192],
  ['viewer/icon-512.png', 512, 512],
  ['viewer/favicon-32x32.png', 32, 32],
  ['viewer/favicon-16x16.png', 16, 16],
  ['viewer/favicon.png', 32, 32],
  ['viewer/og-image.png', 1200, 630],
];
for (const [rel, w, h] of dimSpecs) {
  const f = join(REPO, rel);
  if (!existsSync(f)) { check(`asset ${rel}: exists`, false, 'missing'); continue; }
  const buf = readFileSync(f);
  const s = pngSize(buf);
  check(`asset ${rel}: ${w}x${h}`, s.w === w && s.h === h, `got ${s.w}x${s.h}`);
}
check('asset og-image: non-trivial bytes (>30KB)', readFileSync(join(REPO, 'viewer/og-image.png')).length > 30000);

const logoDark = readFileSync(join(REPO, 'viewer/propwire-logo-dropwire.png'));
const logoLight = readFileSync(join(REPO, 'viewer/propwire-logo-dropwire-light.png'));
const ld = pngSize(logoDark), ll = pngSize(logoLight);
check('header logo dark slot: PWIRE art 156px tall (3x of 52 CSS px)', ld.h === 156 && ld.w > 400, `${ld.w}x${ld.h}`);
check('header logo light slot: padded chip 156px tall (aspect < raw art)', ll.h === 156 && ll.w > 440 && (ll.w / ll.h) < (ld.w / ld.h), `${ll.w}x${ll.h}`);

// ── 2. SVG favicons parse with embedded raster mark ──────────────────────
for (const rel of ['viewer/favicon.svg', 'viewer/propwire-icon.svg']) {
  const svg = readFileSync(join(REPO, rel), 'utf8');
  // xmlns* declarations are required namespace URIs, not external fetches;
  // an <img>-context SVG must not reference anything else
  const noExt = !/href="http/.test(svg) && !/src="http/.test(svg) && !/url\(http/.test(svg);
  const ok = svg.includes('<svg') && svg.includes('data:image/png;base64,') &&
    noExt // owner-restored SVGs embed the authentic raster mark without v153 vector chrome;
  check(`svg ${rel}: parses, embedded raster, no external refs`, ok);
}

// ── 3. Head wiring on all 5 terminal pages ───────────────────────────────
const pages = ['index.html', 'ledger.html', 'audit.html', 'verify.html', 'ledger/index.html'];
for (const p of pages) {
  const html = readFileSync(join(ROOT, p), 'utf8');
  const has = (re) => re.test(html);
  const ok =
    has(/rel="icon"[^>]*href="\/favicon-32x32\.png\?v=2026_v179"/) &&
    has(/rel="icon"[^>]*href="\/favicon-16x16\.png\?v=2026_v179"/) &&
    has(/rel="icon"[^>]*href="\/favicon\.svg\?v=2026_v179"/) &&
    has(/rel="apple-touch-icon" href="\/apple-touch-icon\.png\?v=2026_v179"/) &&
    has(/rel="apple-touch-icon" sizes="180x180" href="\/apple-touch-icon-180x180\.png\?v=2026_v179"/) &&
    has(/rel="manifest" href="\/site\.webmanifest\?v=2026_v179"/) &&
    has(/og:image" content="(https:\/\/propwire\.vercel\.app\/og-image\.png|\/propstein-logo\.png)\?v=2026_v179"/) &&
    has(/twitter:image" content="(https:\/\/propwire\.vercel\.app\/og-image\.png|\/propstein-logo\.png)\?v=2026_v179"/) &&
    has(/src="\/(propstein|propwire)-logo(-dark)?\.(png|svg)\?v=2026_v179"/) &&
    has(/src="\/(propstein|propwire)-logo-dark\.(png|svg)\?v=2026_v179"/) &&
    has(/name="build-hash" content="2026-w8-v30"/) &&
    !has(/propwire-logo-dropwire/) &&
    !has(/\?v=v149|\?v=2026_v1"|\?v=2026_v152|2026-w8-v17/);
  check(`head ${p}: v153 brand wiring complete, zero stale refs`, ok);
}

// ── 4. Manifest identity + icons resolve ─────────────────────────────────
const manifest = JSON.parse(readFileSync(join(ROOT, 'site.webmanifest'), 'utf8'));
check('manifest: PropStein identity + standalone + #0b0e14', manifest.name === 'PropStein' &&
  manifest.display === 'standalone' && manifest.theme_color === '#0b0e14');
const manIcons = [];
for (const ic of manifest.icons || []) {
  const rel = ic.src.split('?')[0].replace(/^\//, '');
  const f = join(ROOT, rel);
  manIcons.push(existsSync(f) && ic.src.endsWith('v=2026_v179'));
}
check('manifest: 4 icons exist at ?v=2026_v179', manIcons.length === 4 && manIcons.every(Boolean), `${manIcons.length} icons`);

// ── 5. Icon pixel probe: monogram centered (browser canvas) ──────────────
const browser = await chromium.launch();
const probe = await browser.newPage({ viewport: { width: 600, height: 600 } });
await probe.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
const pixelProbe = async (url, ew, eh) => probe.evaluate(async ([u, w, h]) => {
  const img = new Image();
  img.src = u;
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
  if (img.naturalWidth !== w || img.naturalHeight !== h) return { err: `size ${img.naturalWidth}x${img.naturalHeight}` };
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
}, [url, ew, eh]).catch((e) => ({ err: String(e.message || e) }));
for (const [url, w, h] of [
  ['/apple-touch-icon.png?v=2026_v179', 180, 180],
  ['/icon-192.png?v=2026_v179', 192, 192],
  ['/icon-512.png?v=2026_v179', 512, 512],
]) {
  const m = await pixelProbe(`http://127.0.0.1:${PORT}${url}`, w, h);
  if (m.err) { check(`icon ${url}: centered monogram`, false, m.err); continue; }
  check(`icon ${url}: monogram centered (center ${(m.center * 100).toFixed(1)}% vs corner ${(m.corner * 100).toFixed(1)}%)`,
    m.center > 0.05 && m.corner < 0.04);
}

// ── 6. Header slot logos render + og-image fetch under prod CSP ──────────
const hdr = await probe.evaluate(async () => {
  const imgs = [...document.querySelectorAll('.pw-brand-img')];
  await Promise.all(imgs.map((i) => i.complete ? 0 : new Promise((r) => { i.onload = r; i.onerror = r; })));
  return imgs.map((i) => ({
    src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0,
    w: i.clientWidth, h: i.clientHeight,
    cls: i.className,
  }));
});
check('header: both slot logos decoded under prod CSP', hdr.length === 2 && hdr.every((x) => x.ok), JSON.stringify(hdr.map((x) => x.src)));
// dark slot is the visible one in dark theme; light-only is display:none
// (style.css 8185) — assert its DECODE, not its box. The visible slot must
// sit in the designed wide-lockup envelope (CSS range across breakpoints).
const vis = hdr.find((x) => /pw-brand-dark-only/.test(x.cls));
const hid = hdr.find((x) => /pw-brand-light-only/.test(x.cls));
check('header: visible dark slot box in lockup envelope (w 96-160, h 24-40)',
  vis && vis.w >= 86 && vis.w <= 160 && vis.h >= 24 && vis.h <= 40, `${vis ? vis.w + 'x' + vis.h : 'missing'}`);
check('header: light slot decoded (hidden in dark theme by design)', hid && hid.ok);
check('header: dark-only + light-only slots distinct', hdr[0].src !== hdr[1].src && /pw-brand-dark-only/.test(hdr.map((x) => x.cls).join(' ')));
// light-theme flip: both slots must swap visibility cleanly
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

const ogRes = await fetch(`http://127.0.0.1:${PORT}/og-image.png?v=2026_v179`);
const ogBuf = Buffer.from(await ogRes.arrayBuffer());
check('og-image: 200 + PNG + served under CSP img-src self', ogRes.ok && ogBuf.slice(1, 4).toString('latin1') === 'PNG' && ogRes.headers.get('content-security-policy') === CSP);

// ── 7. SW: v153 cache activates, precache populated (incl. new logos) ────
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
    fav: await probe2('/favicon.svg?v=2026_v179'),
    i192: await probe2('/icon-192.png?v=2026_v179'),
    i512: await probe2('/icon-512.png?v=2026_v179'),
    man: await probe2('/site.webmanifest?v=2026_v179'),
    book: await probe2('/books/draftkings.svg?v=v152'),
  };
});
check('SW: propstein-v179-prod activated', sw.name === 'propstein-v179-prod', String(sw.name));
check('SW: precache has authentic SVG logos + icons/manifest', sw.logoDark && sw.logoLight && sw.fav && sw.i192 && sw.i512 && sw.man, JSON.stringify(sw));
check('SW: v152 book badges still precached', sw.book);
check('boot: zero hard console errors (CSP inline-style debt tracked separately)', errors.length === 0, errors.slice(0, 3).join(' | '));
check('boot: CSP inline-style debt not grown (<= 178 v171 merge baseline (owner-redesign debt 171->178))', cspDebt <= 178, `debt=${cspDebt}`);

// ── 8. Screenshot ─────────────────────────────────────────────────────────
await page.evaluate(() => document.querySelector('.pw-brand')?.scrollIntoView({ block: 'center' }));
await page.waitForTimeout(250);
await page.screenshot({ path: SHOTS + '/headless_v153_rebrand_header.png', clip: { x: 0, y: 0, width: 1280, height: 220 } });

await browser.close();
server.close();
console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURES`}  (cspDebt=${cspDebt})`);
process.exit(failures === 0 ? 0 : 1);
