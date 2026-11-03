#!/usr/bin/env node
// Diagnostic probe: where does the brand "P" get clipped?
// Serves viewer/ on a random port (SW-cache trap discipline), loads index.html
// at every breakpoint, walks clipping ancestors of .pw-brand-img, computes the
// visible sub-rect of the img, and screenshots the topbar per width.
// Also inlines the raw SVG document and getBBox()es the P-mark group vs viewBox.
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const OUT = '/home/z/my-project/download';
const PORT = 9400 + Math.floor(Math.random() * 300);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json' };

const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  const f = join(ROOT, rel);
  if (!existsSync(f)) { res.writeHead(404); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(f)] || 'application/octet-stream' });
  res.end(readFileSync(f));
});
await new Promise((r) => server.listen(PORT, r));
console.log('serving on port', PORT);

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });

const WIDTHS = [1600, 1366, 1280, 1100, 1024, 900, 820, 768, 640, 480, 390];

for (const w of WIDTHS) {
  await page.setViewportSize({ width: w, height: 900 });
  try { await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded', timeout: 15000 }); } catch {}
  await page.waitForTimeout(1100);
  const m = await page.evaluate(() => {
    const img = document.querySelector('.pw-brand-img.pw-brand-dark-only') || document.querySelector('.pw-brand-img');
    if (!img) return { err: 'no brand img in DOM' };
    const ir = img.getBoundingClientRect();
    const cs = getComputedStyle(img);
    const clips = [];
    let el = img.parentElement;
    while (el && el !== document.documentElement) {
      const s = getComputedStyle(el);
      const clipped = [s.overflow, s.overflowX, s.overflowY].some((v) => v && v !== 'visible');
      const fixedH = s.height !== 'auto' && parseFloat(s.height) < ir.height;
      if (clipped || fixedH) {
        const r = el.getBoundingClientRect();
        const cls = (typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal) || '').split(' ').filter(Boolean).slice(0, 2).join('.');
        clips.push({ sel: el.tagName.toLowerCase() + (cls ? '.' + cls : ''), t: +r.top.toFixed(1), b: +r.bottom.toFixed(1), l: +r.left.toFixed(1), r: +r.right.toFixed(1), h: s.height, ov: `${s.overflow}/${s.overflowX}/${s.overflowY}`, clipped, fixedH });
      }
      el = el.parentElement;
    }
    let vis = { t: ir.top, b: ir.bottom, l: ir.left, r: ir.right };
    for (const c of clips) { if (!c.clipped) continue; vis.t = Math.max(vis.t, c.t); vis.b = Math.min(vis.b, c.b); vis.l = Math.max(vis.l, c.l); vis.r = Math.min(vis.r, c.r); }
    const tb = document.querySelector('.pw-topbar');
    const tbr = tb ? tb.getBoundingClientRect() : null;
    const tbcs = tb ? getComputedStyle(tb) : null;
    return {
      vw: innerWidth,
      img: { w: +ir.width.toFixed(1), h: +ir.height.toFixed(1), t: +ir.top.toFixed(1), b: +ir.bottom.toFixed(1) },
      imgCss: { w: cs.width, h: cs.height, fit: cs.objectFit, pos: cs.objectPosition, maxW: cs.maxWidth },
      topbar: tbr ? { h: +tbr.height.toFixed(1), t: +tbr.top.toFixed(1), b: +tbr.bottom.toFixed(1), csH: tbcs.height, ov: tbcs.overflow } : null,
      clips,
      cutPx: { top: +Math.max(0, vis.t - ir.top).toFixed(1), bottom: +Math.max(0, ir.bottom - vis.b).toFixed(1), left: +Math.max(0, vis.l - ir.left).toFixed(1), right: +Math.max(0, ir.right - vis.r).toFixed(1) },
    };
  });
  console.log(JSON.stringify(m));
  const tb = await page.$('.pw-topbar');
  if (tb) await tb.screenshot({ path: join(OUT, `logo_probe_topbar_${w}.png`) }).catch((e) => console.log('shot fail', w, e.message));
}

// Raw SVG geometry: P-mark group bbox vs viewBox (user units)
const p2 = await browser.newPage({ viewport: { width: 900, height: 300 } });
await p2.goto(`http://127.0.0.1:${PORT}/propwire-logo.svg`, { waitUntil: 'load' });
const geo = await p2.evaluate(() => {
  const svg = document.documentElement;
  const vb = svg.viewBox.baseVal;
  const out = { viewBox: { x: vb.x, y: vb.y, w: vb.width, h: vb.height }, groups: [] };
  svg.querySelectorAll('g').forEach((g, i) => {
    const b = g.getBBox();
    const tf = g.transform && g.transform.baseVal.numberOfItems ? g.transform.baseVal.getItem(0) : null;
    out.groups.push({ i, bbox: { x: +b.x.toFixed(2), y: +b.y.toFixed(2), w: +b.width.toFixed(2), h: +b.height.toFixed(2) }, transform: tf ? `${tf.type}(${tf.matrix.a},${tf.matrix.d}) tx=${tf.matrix.e} ty=${tf.matrix.f}` : 'none' });
  });
  return out;
});
console.log('SVG-GEO', JSON.stringify(geo));

await browser.close();
server.close();
console.log('done');
