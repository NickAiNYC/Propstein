#!/usr/bin/env node
// Quick mobile probe: measure footer geometry + card avatar size at 390px.
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const REPO = process.cwd();
const PORT = 9950 + Math.floor(Math.random() * 40);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
const vercel = JSON.parse(readFileSync(join(REPO, 'vercel.json'), 'utf8'));
const prodHeaders = Object.fromEntries(vercel.headers.find((h) => h.source === '/(.*)').headers.map((h) => [h.key, h.value]));
const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  const file = join(ROOT, rel);
  if (!existsSync(file)) { res.writeHead(404, prodHeaders); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream', ...prodHeaders });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, r));

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => window.__PROP_WIRE_READY__ === true, null, { timeout: 25000 });
  await page.waitForTimeout(800);

  const probe = await page.evaluate(() => {
    const out = { vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth };
    for (const sel of ['.terminal-compliance-footer', '.pw-institutional-footer', '.pw-footer-inner', '.compliance-pills']) {
      const el = document.querySelector(sel);
      if (!el) { out[sel] = 'MISSING'; continue; }
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      out[sel] = {
        left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
        textAlign: cs.textAlign, margin: cs.margin, padding: cs.padding, maxWidth: cs.maxWidth,
        display: cs.display, justify: cs.justifyContent
      };
    }
    const avatar = document.querySelector('.card-id-block .pw-avatar');
    if (avatar) {
      const r = avatar.getBoundingClientRect();
      out.avatar = { w: Math.round(r.width), h: Math.round(r.height) };
    }
    // body / main containers that might shift the footer
    for (const sel of ['body', '.execution-shell', 'main', '#tableView', '#cardView']) {
      const el = document.querySelector(sel);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      out[sel] = { left: Math.round(r.left), width: Math.round(r.width), ml: cs.marginLeft, mr: cs.marginRight, overflowX: cs.overflowX };
    }
    return out;
  });
  console.log(JSON.stringify(probe, null, 1));
  // scroll to the very bottom and capture the footer region
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(600);
  const bottom = await page.evaluate(() => {
    const out = {};
    for (const sel of ['.terminal-compliance-footer', '.pw-institutional-footer', '.pw-footer-inner', '.compliance-pills', '.compliance-research-nav', '.compliance-disclaimer']) {
      const el = document.querySelector(sel);
      if (!el) { out[sel] = 'MISSING'; continue; }
      const r = el.getBoundingClientRect();
      out[sel] = { left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), top: Math.round(r.top) };
    }
    const av = document.querySelector('.card-id-block .pw-avatar');
    if (av) {
      const cs = getComputedStyle(av);
      out.avatarCS = { w: cs.width, h: cs.height, minW: cs.minWidth, minH: cs.minHeight, radius: cs.borderRadius, aspectBox: cs.aspectRatio };
    }
    const nav = document.querySelector('.mobile-bottom-nav');
    if (nav) {
      const r = nav.getBoundingClientRect();
      const cs = getComputedStyle(nav);
      out.bottomNav = { left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), bottom: Math.round(r.bottom), pos: cs.position, gridCols: cs.gridTemplateColumns, ml: cs.marginLeft };
    }
    // find horizontal overflow culprits
    out.overflowEls = Array.from(document.querySelectorAll('body *')).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.right > 391.5 || r.left < -1.5;
    }).slice(0, 8).map((el) => ({ tag: el.tagName, cls: String(el.className).slice(0, 60), right: Math.round(el.getBoundingClientRect().right), left: Math.round(el.getBoundingClientRect().left) }));
    const nav2 = document.querySelector('.mobile-bottom-nav');
    if (nav2) {
      out.navChain = [];
      let el = nav2.parentElement;
      while (el && el !== document.documentElement) {
        const cs = getComputedStyle(el);
        out.navChain.push({ tag: el.tagName, cls: String(el.className).slice(0, 40), w: Math.round(el.getBoundingClientRect().width), transform: cs.transform !== 'none' ? cs.transform.slice(0, 24) : '', bf: cs.backdropFilter !== 'none' ? cs.backdropFilter.slice(0, 24) : '', filter: cs.filter !== 'none' ? cs.filter.slice(0, 24) : '', willChange: cs.willChange });
        el = el.parentElement;
      }
      const ncs = getComputedStyle(nav2);
      out.navCS = { left: ncs.left, transform: ncs.transform, width: ncs.width, bottom: ncs.bottom };
    }
    out.scrollX = window.scrollX;
    return out;
  });
  console.log('BOTTOM:', JSON.stringify(bottom, null, 1));
  await page.screenshot({ path: '/home/z/my-project/download/probe_footer_bottom.png', fullPage: false });
} finally {
  await browser.close();
  server.close();
}
