import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('deployment config ships baseline browser security headers', async () => {
  const config = JSON.parse(await read('../vercel.json'));
  const headers = config.headers.flatMap((rule) => rule.headers || []);
  const names = new Set(headers.map((header) => header.key.toLowerCase()));

  for (const required of [
    'content-security-policy',
    'permissions-policy',
    'referrer-policy',
    'strict-transport-security',
    'x-content-type-options',
    'x-frame-options'
  ]) {
    assert.ok(names.has(required), `missing ${required}`);
  }
});

// Vercel applies every matching header rule in order; for the same key the later rule wins.
function cacheControlFor(config, pathname) {
  let value;
  for (const rule of config.headers) {
    const re = new RegExp(`^${rule.source}$`);
    if (!re.test(pathname)) continue;
    const header = rule.headers.find((h) => h.key.toLowerCase() === 'cache-control');
    if (header) value = header.value;
  }
  return value;
}

test('market data is never cached by the deployment or service worker', async () => {
  const config = JSON.parse(await read('../vercel.json'));
  const dataRule = config.headers.find((rule) => rule.source.includes('json|csv'));
  assert.ok(dataRule, 'missing JSON/CSV cache rule');
  assert.match(dataRule.headers[0].value, /no-store/);
  for (const live of ['/live_odds_feed.json', '/live_odds_feed.manifest.json', '/current_picks.json',
    '/live_picks_2026_w10.json', '/current_picks_2026_w10.json', '/clv_audit_report.json',
    '/circuit_breaker_config.json', '/snapshots_2026_w8.manifest.json', '/feeds/slate-index.json',
    '/slate_projections.csv']) {
    assert.match(cacheControlFor(config, live) || '', /no-store/, `${live} must be no-store`);
  }

  const serviceWorker = await read('../viewer/sw.js');
  assert.match(serviceWorker, /json\|csv/);
  assert.match(serviceWorker, /cache:\s*revalidate \? 'no-cache' : 'no-store'/);
  assert.doesNotMatch(serviceWorker, /cache\.put\(event\.request[\s\S]*json/i);

  const app = await read('../viewer/app.js');
  assert.match(app, /cache: revalidate \? 'no-cache' : 'no-store'/);
  assert.match(app, /revalidate \? path : `\$\{path\}\?v=\$\{Date\.now\(\)\}`/, 'non-slate data keeps a unique URL');
});

test('per-slate artifacts always revalidate and are never served stale', async () => {
  const config = JSON.parse(await read('../vercel.json'));
  for (const slate of ['/slate_projections.json', '/slate_2026_w10.json', '/snapshots_2026_w8.json']) {
    const value = cacheControlFor(config, slate) || '';
    assert.match(value, /no-cache/, `${slate} must revalidate on every use`);
    assert.match(value, /must-revalidate/);
    assert.doesNotMatch(value, /no-store/, `${slate} must be storable so the browser can send If-None-Match`);
    assert.doesNotMatch(value, /max-age=[1-9]|stale-while-revalidate|immutable/, `${slate} must never be served from cache without revalidation`);
  }
});

test('the service worker script is never cached by the generic .js rule', async () => {
  const config = JSON.parse(await read('../vercel.json'));
  const sources = config.headers.map((rule) => rule.source);
  const jsRule = sources.findIndex((src) => src.includes('js|css'));
  const swRule = sources.indexOf('/sw.js');
  assert.ok(jsRule >= 0 && swRule > jsRule, '/sw.js must come after the .js rule so it wins');
  assert.match(cacheControlFor(config, '/sw.js'), /no-store/);
  assert.match(cacheControlFor(config, '/app.js'), /max-age=300/);
  assert.match(cacheControlFor(config, '/propstein-logo.webp'), /max-age=/);
});

test('production HTML and service worker use the same release asset version', async () => {
  const [html, serviceWorker] = await Promise.all([
    read('../viewer/index.html'),
    read('../viewer/sw.js')
  ]);
  const htmlVersion = html.match(/style\.css\?v=(2026_v\d+)/)?.[1];
  assert.ok(htmlVersion, 'HTML asset version is missing');
  assert.match(html, new RegExp(`app\\.js\\?v=${htmlVersion}`));
  assert.match(serviceWorker, new RegExp(`style\\.css\\?v=${htmlVersion}`));
  assert.match(serviceWorker, new RegExp(`app\\.js\\?v=${htmlVersion}`));
});

test('backend entitlement fails closed and CORS is allowlisted', async () => {
  const api = await read('../api/main.py');
  assert.match(api, /raise HTTPException\(503, "entitlement verification is unavailable"\)/);
  assert.doesNotMatch(api, /allow_origins=\["\*"\]/);
  assert.match(api, /PROPWIRE_ALLOW_DEV_AUTH_BYPASS/);
  assert.doesNotMatch(api, /admin_token:\s*Optional\[str\]\s*=\s*Query/);
});

test('slate labels guard optional week metadata', async () => {
  const app = await read('../viewer/app.js');
  // Merge resolution 2026-10-27: the NBA slate-label fix (slateCfg.week
  // != null guard + shortLabel passthrough for date-keyed slates)
  // superseded the earlier Number.isFinite(Number(slate.week)) form.
  // Intent unchanged: no "Wundefined" labels ever render, and non-week
  // slates keep their own label instead of a week-derived one.
  assert.match(app, /if \(slateCfg\.week != null\)/);
  assert.doesNotMatch(app, /W\$\{SLATES\[state\.slateKey\]\.week\}/);
});

test('paid access cannot be activated by URL or local storage', () => {
  const { sandbox } = buildSandbox({ seedLocalStorage: { 'propwire-user-tier': 'pro' } });
  sandbox.window.location.search = '?tier=pro&checkout=success&session_id=cs_forged';
  sandbox.window.location.href = 'https://propstein.test/?tier=pro&checkout=success&session_id=cs_forged';
  const app = loadApp(sandbox);
  assert.equal(app.state.userTier, 'free');
});

test('all public pricing panels keep paid access closed without checkout controls', async () => {
  for (const page of ['../viewer/index.html', '../viewer/audit.html', '../viewer/ledger.html', '../viewer/ledger/index.html']) {
    const html = await read(page);
    const panel = html.match(/<dialog class="detail-dialog pricing-dialog"[\s\S]*?<\/dialog>/)?.[0];
    assert.ok(panel, `pricing panel missing in ${page}`);
    assert.match(panel, /Paid signups frozen/, `${page}: paid access must read as closed`);
    assert.doesNotMatch(panel, /data-checkout-tier|data-switch-tier|Sub-minute priority ingestion/);
  }
});

test('the homepage pricing panel presents the free public terminal', async () => {
  const html = await read('../viewer/index.html');
  const panel = html.match(/<dialog class="detail-dialog pricing-dialog"[\s\S]*?<\/dialog>/)?.[0];
  assert.ok(panel, 'pricing panel missing in index.html');
  assert.match(panel, /research terminal is free and open/i);
  assert.match(panel, /without an account/i);
  assert.match(panel, /every 4 hours/i, 'free access must still disclose the real refresh cadence');
  assert.doesNotMatch(panel, /data-checkout-tier|data-switch-tier|checkout\.stripe\.com/);
});
