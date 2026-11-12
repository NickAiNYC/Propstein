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

test('market data is never cached by the deployment or service worker', async () => {
  const config = JSON.parse(await read('../vercel.json'));
  const dataRule = config.headers.find((rule) => rule.source.includes('json|csv'));
  assert.ok(dataRule, 'missing JSON/CSV cache rule');
  assert.match(dataRule.headers[0].value, /no-store/);

  const serviceWorker = await read('../viewer/sw.js');
  assert.match(serviceWorker, /json\|csv/);
  assert.match(serviceWorker, /cache:\s*'no-store'/);
  assert.doesNotMatch(serviceWorker, /cache\.put\(event\.request[\s\S]*json/i);
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
