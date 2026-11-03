#!/usr/bin/env node
// v149 — Regenerate the full iOS/PWA/favicon icon set from the committed
// brand mark (viewer/favicon.svg P geometry, #7dd3fc on dark).
//
// Fixes: previous set (generated from a user PNG with bad extract math)
// rendered the mark tiny in the top-left corner of an empty tile.
//
// Design rules:
//   - bg flat #0b0e14 (current v147/v148 terminal canvas — matches the
//     status-bar area in iOS standalone mode with black-translucent)
//   - apple-touch-*: full-bleed square, mark at ~62% (iOS applies its own
//     squircle mask; never pre-round corners)
//   - icon-192/512 (manifest "any maskable"): mark at ~55%, content stays
//     inside the 80% maskable safe circle
//   - favicons 32/16: mark at ~70% for legibility at tab size
//   - favicon.svg: same mark, bg gradient endpoint updated to #0b0e14
import { chromium } from 'playwright';
import { writeFileSync, readFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

const ROOT = process.cwd();
const VIEWER = join(ROOT, 'viewer');
mkdirSync(join(ROOT, 'tmp_icons'), { recursive: true });

// P-mark geometry lifted verbatim from viewer/favicon.svg (source space
// ~x 15.6..184.4, y 12..188 → center (100,100), height 176 units).
const MARK_PATHS = readFileSync(join(VIEWER, 'favicon.svg'), 'utf8')
  .match(/<g transform="[^"]*">([\s\S]*?)<\/g>/)[1];

const SRC_H = 176;      // mark height in source units
const SRC_CX = 100;     // mark center in source units
const SRC_CY = 100;

function iconSvg(size, frac, bg) {
  const s = (frac * size) / SRC_H;
  const tx = size / 2 - SRC_CX * s;
  const ty = size / 2 - SRC_CY * s;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" fill="none">
<rect width="${size}" height="${size}" fill="${bg}"/>
<g transform="translate(${tx.toFixed(3)},${ty.toFixed(3)}) scale(${s.toFixed(6)})">${MARK_PATHS}</g>
</svg>`;
}

// [filename, size, mark fraction, background]
const CANVAS = '#0b0e14';
const targets = [
  ['apple-touch-icon.png', 180, 0.62, CANVAS],
  ['apple-touch-icon-precomposed.png', 180, 0.62, CANVAS],
  ['apple-touch-icon-180x180.png', 180, 0.62, CANVAS],
  ['apple-touch-icon-180x180-precomposed.png', 180, 0.62, CANVAS],
  ['apple-touch-icon-152x152.png', 152, 0.62, CANVAS],
  ['apple-touch-icon-167x167.png', 167, 0.62, CANVAS],
  ['apple-touch-icon-120x120.png', 120, 0.62, CANVAS],
  ['icon-192.png', 192, 0.55, CANVAS],
  ['icon-512.png', 512, 0.55, CANVAS],
  ['favicon-32x32.png', 32, 0.70, CANVAS],
  ['favicon-16x16.png', 16, 0.70, CANVAS],
  ['favicon.png', 32, 0.70, CANVAS],
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 512, height: 512 }, deviceScaleFactor: 1 });

for (const [name, size, frac, bg] of targets) {
  const svgPath = join(ROOT, 'tmp_icons', `icon_${size}.svg`);
  writeFileSync(svgPath, iconSvg(size, frac, bg));
  await page.setViewportSize({ width: size, height: size });
  await page.goto(`file://${svgPath}`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: join(VIEWER, name), clip: { x: 0, y: 0, width: size, height: size } });
  console.log('wrote viewer/' + name, size + 'x' + size, 'frac', frac);
}

// favicon.svg — same mark, gradient endpoint synced to the v149 canvas.
const favSvg = `<svg width="32" height="32" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="favBg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1C2736"/>
      <stop offset="1" stop-color="#0B0E14"/>
    </linearGradient>
  </defs>
  <rect width="100" height="100" rx="22" fill="url(#favBg)" stroke="#ffffff" stroke-opacity="0.12" stroke-width="1.5"/>
  <g transform="translate(13, 13) scale(0.37)">${MARK_PATHS}</g>
</svg>`;
writeFileSync(join(VIEWER, 'favicon.svg'), favSvg);
console.log('wrote viewer/favicon.svg (bg endpoint #0B0E14)');

await browser.close();
console.log('v149 icon set complete: ' + (targets.length + 1) + ' files');
