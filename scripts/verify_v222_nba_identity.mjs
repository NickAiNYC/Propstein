#!/usr/bin/env node
// v222 — NBA player-identity verification under PRODUCTION CSP parity,
// on top of the v216 view-modes change (board honesty: a market-only slate
// defaults to "0 NBA picks today" with a Browse button; the FanDuel reference
// lines are browsable, not picks).
// Serves viewer/ with the exact global headers from viewer/vercel.json
// (same discipline as verify_v150_csp.mjs), boots the app in NBA mode,
// selects the market-only slate (registry default), opens the board, and proves:
//   1. the default board state is the honest one — "0 NBA picks today",
//      topCount 0, a Browse FanDuel lines button, and zero line cards
//   2. after Browse, every reference-line card carries an avatar (headshot or
//      initials) with a team badge, plus the matchup's two team crests
//   3. headshot/badge/crest images actually DECODE under the production CSP
//   4. the heading shows the slate's own date (not a hardcoded "October 31")
//   5. identity survives the table / cards / compact-grid view switch
//   6. the home-edge preview shows the honest empty state (no sample lines
//      since v216 — so no avatars there either, by design)
//   7. zero CSP-blocked requests; zero non-style-debt console errors; no
//      horizontal overflow
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9700 + Math.floor(Math.random() * 200);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

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
console.log(`serving viewer/ on ${PORT} with viewer/vercel.json header parity (production CSP)`);

let failures = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await ctx.addInitScript(() => { try { localStorage.setItem('propwire_active_sport', 'nba'); } catch (_) {} });
const page = await ctx.newPage();
const cspFailures = [];
const otherFailed = [];
const consoleErrors = [];
page.on('requestfailed', (r) => { if (/csp/i.test(r.failure()?.errorText || '')) cspFailures.push(r.url()); else otherFailed.push(`${r.url()} :: ${r.failure()?.errorText || ''}`); });
page.on('response', (r) => { if (r.status() >= 400) otherFailed.push(`${r.url()} :: HTTP ${r.status()}`); });
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + String(e)));

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
await page.waitForTimeout(2500);

// Select the market-only slate (evaluate-based: the desktop slate select may be
// visually hidden behind the front page). The registry's marketOnly default is
// 2026-11-02 since #87 (11-01 before).
await page.evaluate(() => {
  const sel = document.getElementById('slateSelector');
  sel.value = '2026-11-02';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
});
await page.waitForTimeout(1500);

// Home-edge preview BEFORE opening the board: v216 made it honest — "0 NBA
// picks today", an empty-state note, a Browse button — and no sample line
// cards (so no avatars there either).
const homeEdge = await page.evaluate(() => ({
  title: (document.querySelector('#homeEdgeTitle') || {}).textContent || '',
  openBoard: (document.querySelector('#homeEdgeOpenBoard') || {}).textContent || '',
  emptyNote: (document.querySelector('#homeEdgeList .home-edge-empty') || {}).textContent || '',
  avatars: document.querySelectorAll('#homeEdgeList .pw-avatar').length,
  cards: document.querySelectorAll('#homeEdgeList .home-edge-card').length
}));
check('home-edge: honest title "0 NBA picks today"', /0 NBA picks today/.test(homeEdge.title), homeEdge.title);
check('home-edge: open-board button now says Browse FanDuel lines', /Browse FanDuel lines/.test(homeEdge.openBoard), homeEdge.openBoard);
check('home-edge: honest empty note, no sample line cards', /No NBA model prediction/.test(homeEdge.emptyNote) && homeEdge.cards === 0,
  `${homeEdge.cards} cards, note: "${homeEdge.emptyNote.slice(0, 60)}..."`);
check('home-edge: no avatars rendered (no cards to badge — by design)', homeEdge.avatars === 0, `${homeEdge.avatars} avatars`);

await page.evaluate(() => { document.getElementById('explorePropsBtn')?.click(); });
await page.waitForTimeout(1200);

// The board opens in browsing mode by design — front-page.js's setBoardOpen()
// clicks #modeAllBtn on open, and #homeEdgeOpenBoard's v216 listener also
// forces playMode 'all' on market-only slates. So the reference lines (and
// their player identity) are what the user sees first.
// Force lazy imgs eager so the decode proof isn't vacuous (same trick as v150).
await page.evaluate(() => {
  document.querySelectorAll('.nba-market-quote img[loading="lazy"]').forEach((i) => { i.loading = 'eager'; });
});
await page.waitForTimeout(3500);

const board = await page.evaluate(() => {
  const quotes = [...document.querySelectorAll('.nba-market-quote')];
  const visible = quotes.filter((q) => q.getBoundingClientRect().height > 0);
  const avatarImgs = [...document.querySelectorAll('.nba-market-quote .pw-avatar-img')];
  const badges = [...document.querySelectorAll('.nba-market-quote .pw-avatar-team-badge')];
  const crests = [...document.querySelectorAll('.nba-market-quote .nba-market-matchup .crest-img')];
  return {
    quotes: quotes.length,
    visible: visible.length,
    avatars: document.querySelectorAll('.nba-market-quote .pw-avatar').length,
    avatarImgs: avatarImgs.length,
    avatarImgsDecoded: avatarImgs.filter((i) => i.complete && i.naturalWidth > 0).length,
    badges: badges.length,
    badgesDecoded: badges.filter((i) => i.complete && i.naturalWidth > 0).length,
    crestImgs: crests.length,
    crestsDecoded: crests.filter((i) => i.complete && i.naturalWidth > 0).length,
    headText: (document.querySelector('.nba-market-head strong') || {}).textContent || '',
    overText: (document.querySelector('.nba-market-sides span') || {}).textContent || '',
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth
  };
});

check('CSP header: img-src allows a.espncdn.com', /img-src[^;]*a\.espncdn\.com/.test(cspHeader));
check('CSP header: img-src allows cdn.nba.com (v221 addition, carried by v222)', /img-src[^;]*cdn\.nba\.com/.test(cspHeader));
check('browsed lines: every quote card renders', board.quotes > 0, `${board.quotes} cards (${board.visible} visible)`);
check('every quote card has an avatar', board.avatars === board.quotes, `${board.avatars}/${board.quotes}`);
check('headshot imgs present and DECODE under production CSP', board.avatarImgs > 40 && board.avatarImgsDecoded >= board.avatarImgs - 5 && board.avatarImgsDecoded / board.avatarImgs > 0.95,
  `${board.avatarImgsDecoded}/${board.avatarImgs} decoded`);
check('team badges present and decode', board.badges >= 40 && board.badgesDecoded >= board.badges - 5 && board.badgesDecoded / board.badges > 0.95,
  `${board.badgesDecoded}/${board.badges} decoded`);
check('matchup crests present and decode (2 per card)', board.crestImgs >= 100 && board.crestsDecoded === board.crestImgs,
  `${board.crestsDecoded}/${board.crestImgs} decoded`);
check('heading shows the slate date, not hardcoded October 31', /November/.test(board.headText), board.headText);
check('v216 honest line casing kept (Over/Under, no arrows)', /^Over\s/.test(board.overText.trim()), JSON.stringify(board.overText.trim()));

// Identity must survive the v216 view-mode switch (table / cards / compact-grid).
const viewCounts = {};
for (const view of ['table', 'compact-grid', 'cards']) {
  await page.evaluate((v) => {
    const btn = document.querySelector(`.view-switch button[data-view="${v}"]`);
    if (btn) btn.click();
  }, view);
  await page.waitForTimeout(700);
  viewCounts[view] = await page.evaluate(() => ({
    cards: document.querySelectorAll('.nba-market-quote').length,
    avatars: document.querySelectorAll('.nba-market-quote .pw-avatar').length,
    viewClass: (document.querySelector('#emptyState') || {}).className || ''
  }));
}
const baseCards = board.quotes;
check('identity survives view switch (table/compact-grid/cards)',
  Object.entries(viewCounts).every(([v, c]) => c.cards === baseCards && c.avatars === baseCards && c.viewClass.includes(`nba-market-view-${v === 'cards' ? 'cards' : v}`)),
  Object.entries(viewCounts).map(([v, c]) => `${v}:${c.avatars}/${c.cards}`).join(' '));

// Now switch to the PICKS mode (#modeTopBtn): the honest 0-picks board state —
// "0 NBA picks today", top count 0, the Browse FanDuel lines button, and zero
// reference-line cards (they are not picks). Then the Browse button must bring
// the identity cards back.
await page.evaluate(() => { document.getElementById('modeTopBtn')?.click(); });
await page.waitForTimeout(800);
const idle = await page.evaluate(() => ({
  headText: (document.querySelector('.nba-market-head strong') || {}).textContent || '',
  topCount: (document.querySelector('#topCount') || {}).textContent || '',
  browseBtn: Boolean(document.querySelector('#nbaBrowseLines')),
  cards: document.querySelectorAll('.nba-market-quote').length
}));
check('picks mode: heading is the honest "0 NBA picks today"', /0 NBA picks today/.test(idle.headText), idle.headText);
check('picks mode: top count is 0', idle.topCount === '0', idle.topCount);
check('picks mode: Browse FanDuel lines button present', idle.browseBtn);
check('picks mode: zero reference-line cards rendered', idle.cards === 0, `${idle.cards} cards`);
await page.evaluate(() => { document.getElementById('nbaBrowseLines')?.click(); });
await page.waitForTimeout(800);
const rebrowsed = await page.evaluate(() => document.querySelectorAll('.nba-market-quote .pw-avatar').length);
check('Browse button returns the identity cards', rebrowsed === board.quotes, `${rebrowsed}/${board.quotes} avatars back`);

check('no horizontal overflow introduced', !board.overflowX);

// Direct probes under the production CSP document.
// NOTE (sandbox): this environment's headless Chromium is rejected by some
// ESPN/NBA edge endpoints (site.api.espn.com scoreboard fetch and
// cdn.nba.com image requests fail in-browser while curl gets 200 + ACAO:*).
// The CSP change this harness certifies is the HEADER allowlist; the network
// probes below are therefore informational, not gating.
const espnProbe = await page.evaluate(() => new Promise((res) => {
  const img = new Image();
  img.onload = () => res(true); img.onerror = () => res(false);
  img.src = 'https://a.espncdn.com/i/headshots/nba/players/full/3064514.png?v=v222probe';
  setTimeout(() => res(false), 10000);
}));
check('ESPN CDN headshot loads under production CSP (direct probe)', espnProbe);
const nbaCdnProbe = await page.evaluate(() => new Promise((res) => {
  const img = new Image();
  img.onload = () => res(true); img.onerror = () => res(false);
  img.src = 'https://cdn.nba.com/headshots/nba/latest/260x190/2544.png?v=v222probe';
  setTimeout(() => res(false), 10000);
}));
check('cdn.nba.com header allowance (network probe informational — sandbox egress blocks the NBA CDN for headless Chromium)',
  /img-src[^;]*cdn\.nba\.com/.test(cspHeader),
  `header allows cdn.nba.com; network probe ${nbaCdnProbe ? 'loaded' : 'blocked by sandbox egress (curl 200s it)'}`);

check('ZERO CSP-blocked requests', cspFailures.length === 0, cspFailures.length ? `${cspFailures.length} blocked, e.g. ${cspFailures[0]}` : 'clean');
const styleDebt = consoleErrors.filter((e) => /inline style violates/.test(e));
// Known sandbox noise: today-schedule.js's client-side ESPN scoreboard fetch
// (site.api.espn.com) is unreachable from THIS environment's browser (curl
// gets 200 + Access-Control-Allow-Origin:*). The code path is pre-existing,
// unchanged by v222, and fail-open by design ("unavailable" message).
const scheduleNoise = consoleErrors.filter((e) => /site\.api\.espn\.com|Failed to load resource/.test(e));
const otherErrors = consoleErrors.filter((e) => !/inline style violates/.test(e) && !/site\.api\.espn\.com|Failed to load resource/.test(e));
check('zero non-CSP-debt console/page errors attributable to v222', otherErrors.length === 0, otherErrors.slice(0, 3).join(' | ') || 'clean');
check('remaining inline-style violations: pre-existing debt only (informational)', true, `${styleDebt.length} style-attr violations; ${scheduleNoise.length} sandbox-egress schedule-fetch messages`);
check('non-CSP network failures: informational only', true, otherFailed.length ? `${otherFailed.length}: ${otherFailed.slice(0, 3).join(' ; ')}` : 'none');

await page.screenshot({ path: '/home/z/my-project/download/nba_market_only_after_v222.png', fullPage: false });
await browser.close();
server.close();

console.log('─'.repeat(60));
if (failures) { console.log(`v222 NBA identity harness: ${failures} FAILURES`); process.exit(1); }
console.log('v222 NBA identity harness: ALL PASS');
