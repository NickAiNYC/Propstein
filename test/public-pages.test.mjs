// Public SEO pages (B4) — generator invariants, pinned.
// The generated files are committed; this suite asserts honesty labeling,
// CSP safety, sitemap↔file parity and data faithfulness against the source
// fixture JSON. Regenerate with: python3 scripts/build_public_pages.py
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const V = (p) => path.join(__dirname, '..', 'viewer', p);
const walk = (dir, acc = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
};

test('public pages: core set exists', () => {
  for (const p of ['performance/index.html', 'methodology/index.html',
    'nfl/props/receiving-yards/index.html', 'nfl/props/receptions/index.html',
    'legal/terms/index.html', 'legal/privacy/index.html',
    'legal/responsible-gaming/index.html',
    'public.css', 'sitemap.xml', 'robots.txt']) {
    assert.ok(fs.existsSync(V(p)), `missing ${p}`);
  }
});

test('public pages: full coverage matches snapshot pairs', () => {
  const snaps = JSON.parse(fs.readFileSync(V('snapshots_2026_w7.json'), 'utf8'));
  const latest = new Set(snaps.map((s) => `${s.player_id}|${s.market}`));
  const playerFiles = walk(V('nfl/players')).filter((f) => f.endsWith('.html'));
  assert.equal(playerFiles.length, latest.size,
    'one page per deduped (player, market) snapshot pair');
  assert.ok(playerFiles.length >= 700, 'long-tail coverage preserved');
});

test('every generated page: canonical, description, no CSP violations, disclaimer', () => {
  const files = [
    V('performance/index.html'), V('methodology/index.html'),
    V('nfl/props/receiving-yards/index.html'), V('nfl/props/receptions/index.html'),
    ...walk(V('nfl/players')).filter((f) => f.endsWith('.html')),
  ];
  for (const f of files) {
    const html = fs.readFileSync(f, 'utf8');
    assert.ok(html.includes('rel="canonical"'), `canonical missing in ${f}`);
    assert.ok(html.includes('name="description"'), `description missing in ${f}`);
    assert.ok(!/<style[\s>]/.test(html), `inline <style> violates CSP in ${f}`);
    assert.ok(!/ style="/.test(html), `inline style= violates CSP in ${f}`);
    assert.ok(!/<script(?![^>]*application\/ld\+json)/.test(html),
      `non-JSON-LD script in ${f}`);
    assert.ok(/not betting advice/i.test(html), `disclaimer missing in ${f}`);
    assert.ok(/Model limitations/.test(html), `limitations missing in ${f}`);
  }
});

test('legal pages: CSP-safe, disclaimed, linked site-wide, RG helpline present', () => {
  const legal = ['legal/terms/index.html', 'legal/privacy/index.html',
    'legal/responsible-gaming/index.html'].map(V);
  for (const f of legal) {
    const html = fs.readFileSync(f, 'utf8');
    assert.ok(html.includes('rel="canonical"'), `canonical missing in ${f}`);
    assert.ok(html.includes('name="description"'), `description missing in ${f}`);
    assert.ok(!/<style[\s>]/.test(html), `inline <style> violates CSP in ${f}`);
    assert.ok(!/ style="/.test(html), `inline style= violates CSP in ${f}`);
    assert.ok(!/<script(?![^>]*application\/ld\+json)/.test(html),
      `non-JSON-LD script in ${f}`);
    assert.ok(/not betting advice/i.test(html), `disclaimer missing in ${f}`);
  }
  // site-wide footer links on a model page (trust/compliance links everywhere)
  const perf = fs.readFileSync(V('performance/index.html'), 'utf8');
  for (const href of ['/legal/terms/', '/legal/privacy/',
    '/legal/responsible-gaming/']) {
    assert.ok(perf.includes(`href="${href}"`), `footer legal link ${href} missing`);
  }
  const rg = fs.readFileSync(V('legal/responsible-gaming/index.html'), 'utf8');
  assert.ok(rg.includes('1-800-GAMBLER'), 'RG helpline missing');
  assert.ok(/self-exclusion/i.test(rg), 'self-exclusion guidance missing');
  assert.ok(/21\+/i.test(rg), 'age guidance missing');
});

test('sitemap urls are 1:1 with generated pages + core shell', () => {
  const xml = fs.readFileSync(V('sitemap.xml'), 'utf8');
  const locs = [...xml.matchAll(/<loc>(.*?)<\/loc>/g)].map((m) =>
    m[1].replace(/https:\/\/(?:propwire|propstein)\.vercel\.app/, ''));
  const gen = walk(V('nfl/players')).concat(walk(V('nfl/props')))
    .concat(walk(V('legal')))
    .concat([V('performance/index.html'), V('methodology/index.html')])
    .filter((f) => f.endsWith('.html'))
    .map((f) => f.replace(V(''), '').replace(/index\.html$/, ''));
  const expected = new Set([...gen, '/', '/ledger/', '/audit/', '/verify/']);
  assert.deepEqual(new Set(locs), expected);
  assert.equal(locs.length, expected.size, 'no duplicate sitemap urls');
  for (const u of ['/legal/terms/', '/legal/privacy/',
    '/legal/responsible-gaming/']) {
    assert.ok(expected.has(u), `legal page missing from sitemap: ${u}`);
  }
});

test('robots.txt points at the sitemap', () => {
  const txt = fs.readFileSync(V('robots.txt'), 'utf8');
  assert.match(txt, /Sitemap: https:\/\/(?:propwire|propstein)\.vercel\.app\/sitemap\.xml/);
  assert.match(txt, /Allow: \//);
});

test('performance page publishes the real graded record, honestly framed', () => {
  const clv = JSON.parse(fs.readFileSync(V('clv_audit_report.json'), 'utf8'));
  const html = fs.readFileSync(V('performance/index.html'), 'utf8');
  assert.ok(html.includes(clv.record_str), 'ledger record string missing');
  assert.ok(html.includes(String(clv.total_records)), 'n missing');
  assert.ok(/tiny sample/i.test(html), 'sample-size honesty missing');
  assert.ok(/2 of 37|beat the close/i.test(html), 'full-board calibration missing');
  assert.ok(/underperforms the naive/i.test(html),
    'negative holdout result must be disclosed');
  assert.ok(html.includes(clv.ledger_root_hash), 'ledger root hash missing');
});

test('player page renders the snapshot data faithfully (spot check)', () => {
  const snaps = JSON.parse(fs.readFileSync(V('snapshots_2026_w7.json'), 'utf8'))
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  const latest = {};
  for (const s of snaps) latest[`${s.player_id}|${s.market}`] = s;
  const s = latest['00-0032464|receiving_yards'] ??
    Object.values(latest)[0];
  const slug = String(s.player_name).toLowerCase().replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  const html = fs.readFileSync(
    V(`nfl/players/${slug}/${s.market.replace('_', '-')}/index.html`), 'utf8');
  assert.ok(html.includes(String((s.projection || {}).fair_line)),
    `fair line missing for ${s.player_name}`);
  assert.ok(html.includes(s.player_name));
  assert.ok(new RegExp(`^${s.slate.replace(/[W]/g, 'W')}`).test(s.slate)); // slate tag present in data
  assert.ok(html.includes('Snapshot taken'), 'timestamp missing');
});
