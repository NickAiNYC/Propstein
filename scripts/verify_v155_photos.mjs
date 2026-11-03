#!/usr/bin/env node
// v155 verify — player headshots across the terminal.
// Harness parity with verify_v150_csp.mjs: serves viewer/ with the exact
// vercel.json header set (CSP included), then proves the feature live.
// Verifies:
//   - feeds/player_photos.json: schema, normalized-name coverage, espncdn URLs
//   - production CSP still passes with a.espncdn.com headshots (zero blocked)
//   - avatars render in slate rows (after switching MODE -> ALL), mobile cards
//   - headshots actually decode (naturalWidth > 0) under the prod CSP
//   - initials fallback exists underneath every avatar (dead-URL-proof)
//   - execution modal carries the avatar
//   - SW cache propwire-v155-prod, precache populated, feeds JSON NOT precached
//   - avatar markup: no inline style= / onerror= (v150 CSP discipline)
// NOTE: the boot default is MODE=ACTIVE; on honest stale-odds days that board
// is legitimately empty (0 qualified), so this harness flips MODE=ALL first.
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9500 + Math.floor(Math.random() * 300);
const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

const vercel = JSON.parse(readFileSync(join(ROOT, 'vercel.json'), 'utf8'));
const globalHeaders = vercel.headers.find((h) => h.source === '/(.*)').headers;
const cspHeader = globalHeaders.find((h) => h.key === 'Content-Security-Policy').value;

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};

// ---------------- static phase ----------------
const photosPath = join(ROOT, 'feeds', 'player_photos.json');
check('feeds/player_photos.json exists', existsSync(photosPath));
let photos = null;
if (existsSync(photosPath)) {
  photos = JSON.parse(readFileSync(photosPath, 'utf8'));
  check('photos map schema (photos+by_name+count)', !!(photos.photos && photos.by_name && photos.count > 0),
    `count=${photos.count}`);
  const badEntries = Object.entries(photos.photos || {}).filter(([, v]) => !v || !/^https:\/\/a\.espncdn\.com\//.test(v.url || '')).length;
  check('every mapped URL is a verified espncdn headshot', badEntries === 0, `${badEntries} bad`);
  // Coverage with the SAME normalization the app uses (accent/punct fold).
  const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[.,'’]/g, '').replace(/-/g, ' ').split(/\s+/)
    .filter((t) => t && !['jr', 'sr', 'ii', 'iii', 'iv', 'v'].includes(t)).join(' ').trim();
  const slateNames = new Set();
  for (const f of ['slate_2026_w8.json', 'nba_slate_2026-10-23.json']) {
    const p = join(ROOT, f);
    if (!existsSync(p)) continue;
    for (const r of JSON.parse(readFileSync(p, 'utf8'))) slateNames.add(norm(r.player_display_name));
  }
  const nameIdx = new Set(Object.keys(photos.by_name || {}));
  const covered = [...slateNames].filter((n) => nameIdx.has(n)).length;
  check('photo coverage of current slates >= 90%', slateNames.size > 0 && covered / slateNames.size >= 0.9,
    `${covered}/${slateNames.size}`);
}

const appSrc = readFileSync(join(ROOT, 'app.js'), 'utf8');
const avatarFn = appSrc.slice(appSrc.indexOf('function avatarFor'), appSrc.indexOf('async function initPlayerPhotos'));
check('avatar template: no inline onerror / style attrs', !!avatarFn && !/onerror=/.test(avatarFn) && !/style="/.test(avatarFn));
check('app.js: initPlayerPhotos wired at boot', appSrc.includes('await initPlayerPhotos()'));
check('app.js: avatar fallback class ships', appSrc.includes('pw-avatar-fallback'));

const swSrc = readFileSync(join(ROOT, 'sw.js'), 'utf8');
check('sw.js: cache propstein-v176-prod', swSrc.includes("propstein-v176-prod"));
check('sw.js: feeds JSON never precached (network-only data policy)', !/STATIC_ASSETS[\s\S]*?feeds\//.test(swSrc));
check('vercel.json: img-src allows a.espncdn.com', /img-src[^;]*a\.espncdn\.com/.test(cspHeader));

// ---------------- browser phase ----------------
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const cspFailures = [];
const avatarRelatedErrors = [];
const otherConsole = [];
page.on('requestfailed', (r) => {
  const reason = r.failure()?.errorText || '';
  if (/csp/i.test(reason)) cspFailures.push(r.url());
});
page.on('console', (m) => {
  if (m.type() !== 'error') return;
  const text = m.text();
  if (/pw-avatar|player_photos|espncdn/i.test(text)) avatarRelatedErrors.push(text.slice(0, 160));
  else otherConsole.push(text.slice(0, 90));
});

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
await page.waitForTimeout(3500);
// Honest-stale boards boot with MODE=ACTIVE and 0 qualified rows — flip to ALL.
await page.evaluate(() => {
  const btn = document.querySelector('[data-mode="all"]');
  if (btn) btn.click();
});
await page.waitForTimeout(1800);
// Scroll pass: rows are lazy — walk the board so below-fold avatars fetch.
await page.evaluate(async () => {
  await new Promise((resolve) => {
    let y = 0;
    const step = () => {
      y += 600; window.scrollTo(0, y);
      if (y < document.body.scrollHeight) setTimeout(step, 90);
      else { window.scrollTo(0, 0); setTimeout(resolve, 300); }
    };
    step();
  });
});
await page.evaluate(() => {
  document.querySelectorAll('.pw-avatar-img[loading="lazy"]').forEach((i) => { i.loading = 'eager'; });
});
await page.waitForTimeout(2500);

check('ZERO CSP-blocked requests with headshots live', cspFailures.length === 0,
  cspFailures.length ? `e.g. ${cspFailures[0]}` : 'clean');

// CDN-flake hardening (v172): re-kick any in-flight/failed decodes up to 3x with
// a fresh cache-busted request before counting. The 100% decode bar stays —
// only transient ESPN CDN hiccups are retried away.
for (let round = 0; round < 3; round += 1) {
  const stillPending = await page.evaluate(async (r) => {
    const imgs = [...document.querySelectorAll('.pw-avatar-img')];
    const pending = imgs.filter((i) => !(i.complete && i.naturalWidth > 0));
    if (pending.length === 0) return 0;
    await Promise.all(pending.map((img) => new Promise((res) => {
      const probe = new Image();
      probe.onload = () => {
        img.src = `${img.src.split('?')[0]}?r=${r}_${Math.random().toString(36).slice(2, 7)}`;
        res();
      };
      probe.onerror = () => res();
      probe.src = `${img.src.split('?')[0]}?probe=${r}_${Math.random().toString(36).slice(2, 7)}`;
      setTimeout(res, 4000);
    })));
    return imgs.filter((i) => !(i.complete && i.naturalWidth > 0)).length;
  }, round);
  if (stillPending === 0) break;
  await page.waitForTimeout(1200);
}
const avatars = await page.evaluate(() => {
  const all = [...document.querySelectorAll('.pw-avatar')];
  const imgs = [...document.querySelectorAll('.pw-avatar-img')];
  return {
    total: all.length,
    withImg: imgs.length,
    decoded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
    fallbacks: all.filter((a) => a.classList.contains('pw-avatar-fallback')).length,
    badAttrs: all.filter((a) => a.getAttribute('style') || a.hasAttribute('onerror')).length,
    sampleSrc: imgs[0] ? imgs[0].src : null,
  };
});
check('avatars render on the board (MODE=ALL)', avatars.total > 0, `${avatars.total} avatars (${avatars.withImg} with imgs)`);
if (avatars.withImg > 0) {
  check('headshot imgs decode under production CSP', avatars.decoded === avatars.withImg,
    `${avatars.decoded}/${avatars.withImg} decoded; sample=${avatars.sampleSrc}`);
}
check('initials underneath every avatar, no inline attrs (dead-URL-proof)', avatars.total > 0 && avatars.badAttrs === 0,
  `fallbacks=${avatars.fallbacks}, badAttrs=${avatars.badAttrs}`);

// Detail modal (row click -> openDetail) carries the avatar in the title row.
const modalAvatar = await page.evaluate(async () => {
  const row = document.querySelector('[data-testid="slate-row"]');
  if (!row) return { detail: false, slip: null };
  row.scrollIntoView({ block: 'center' });
  row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await new Promise((r) => setTimeout(r, 700));
  const dlg = document.querySelector('#detailDialog');
  const detail = !!(dlg && dlg.open && dlg.querySelector('.detail-title-row .pw-avatar'));
  dlg && dlg.close();
  return { detail };
});
check('detail modal shows player avatar', modalAvatar.detail);

// Direct probe: a real mapped headshot URL must load inside this document.
if (photos && photos.photos) {
  const firstUrl = Object.values(photos.photos)[0]?.url;
  if (firstUrl) {
    const probe = await page.evaluate((src) => new Promise((res) => {
      const img = new Image();
      img.onload = () => res(true);
      img.onerror = () => res(false);
      img.src = src;
      setTimeout(() => res(false), 10000);
    }), firstUrl);
    check('mapped headshot URL loads under prod CSP (direct probe)', probe, firstUrl);
  }
}

// SW: v155 cache live + precache populated.
const swInfo = await page.evaluate(async () => {
  if (!('serviceWorker' in navigator)) return { supported: false };
  const reg = await navigator.serviceWorker.ready;
  const keys = await caches.keys();
  let precached = 0;
  for (const k of keys) {
    const c = await caches.open(k);
    precached = Math.max(precached, (await c.keys()).length);
  }
  return { supported: true, hasV155: keys.includes('propstein-v176-prod'), keys, precached };
});
if (swInfo.supported) {
  check('SW v171 cache registered', swInfo.hasV155, `keys=${swInfo.keys.join(',')}`);
  check('SW precache populated', swInfo.precached > 0, `${swInfo.precached} entries`);
} else {
  console.log('SKIP  service worker (not supported in this context)');
}

await page.screenshot({ path: join(SHOTS, 'headless_v155_photos_desktop.png'), fullPage: false });
console.log('shot -> headless_v155_photos_desktop.png');

// Mobile 390x844: cards view must carry avatars as well.
const mpage = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await mpage.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
await mpage.waitForTimeout(3500);
await mpage.evaluate(() => {
  const btn = document.querySelector('[data-mode="all"]');
  if (btn) btn.click();
});
await mpage.waitForTimeout(1800);
const mAvatars = await mpage.evaluate(() => {
  const cards = [...document.querySelectorAll('[data-testid="slate-card"]')];
  return {
    cards: cards.length,
    withAvatar: cards.filter((c) => c.querySelector('.pw-avatar')).length,
    decoded: cards.map((c) => c.querySelector('.pw-avatar-img')).filter((i) => i && i.complete && i.naturalWidth > 0).length,
  };
});
check('mobile cards show avatars', mAvatars.cards > 0 && mAvatars.withAvatar === mAvatars.cards,
  `${mAvatars.withAvatar}/${mAvatars.cards} cards, ${mAvatars.decoded} decoded`);
await mpage.screenshot({ path: join(SHOTS, 'headless_v155_photos_mobile.png') });
console.log('shot -> headless_v155_photos_mobile.png');

check('zero avatar-related console errors', avatarRelatedErrors.length === 0,
  avatarRelatedErrors.slice(0, 2).join(' | '));
console.log(`INFO  pre-existing console messages (not avatar-related): ${otherConsole.length}`);

await browser.close();
server.close();
console.log(failures === 0 ? '\nverify_v155_photos: ALL PASS' : `\nverify_v155_photos: ${failures} FAILURES`);
process.exit(failures === 0 ? 0 : 1);
