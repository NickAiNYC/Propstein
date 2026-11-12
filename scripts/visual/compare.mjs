#!/usr/bin/env node
// Pixel-compare two capture directories.
//
//   node scripts/visual/compare.mjs <baselineDir> <actualDir> [diffDir] [--tolerance 8] [--max-pixels 0]
//
// A pixel "differs" when any RGBA channel differs by more than --tolerance (0-255).
// A screenshot fails when more than --max-pixels pixels differ, or its size changed.
// Diff images (changed pixels in red over a dimmed actual) are written for failures.
// Exit code 1 if anything fails or a screenshot is missing.
import fs from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';

const args = process.argv.slice(2);
const flag = (n, d) => (args.includes(n) ? Number(args[args.indexOf(n) + 1]) : d);
const [baseDir, actualDir, diffDir = '.visual/diff'] = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
const TOL = flag('--tolerance', 8);
const MAX = flag('--max-pixels', 0);

const raw = async (file) => {
  const { data, info } = await sharp(file).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  return { data, w: info.width, h: info.height };
};

fs.rmSync(diffDir, { recursive: true, force: true });
fs.mkdirSync(diffDir, { recursive: true });
const names = new Set([...fs.readdirSync(baseDir), ...fs.readdirSync(actualDir)].filter((f) => f.endsWith('.png')));
let failed = 0;
for (const name of [...names].sort()) {
  const b = path.join(baseDir, name); const a = path.join(actualDir, name);
  if (!fs.existsSync(b) || !fs.existsSync(a)) { console.log(`MISSING  ${name} (${fs.existsSync(b) ? 'no actual' : 'no baseline'})`); failed += 1; continue; }
  const [B, A] = await Promise.all([raw(b), raw(a)]);
  if (B.w !== A.w || B.h !== A.h) { console.log(`SIZE     ${name}: ${B.w}x${B.h} -> ${A.w}x${A.h}`); failed += 1; continue; }
  const out = Buffer.alloc(A.data.length);
  let diff = 0;
  for (let i = 0; i < A.data.length; i += 4) {
    const d = Math.max(Math.abs(A.data[i] - B.data[i]), Math.abs(A.data[i + 1] - B.data[i + 1]),
      Math.abs(A.data[i + 2] - B.data[i + 2]), Math.abs(A.data[i + 3] - B.data[i + 3]));
    if (d > TOL) { diff += 1; out[i] = 255; out[i + 1] = 0; out[i + 2] = 0; out[i + 3] = 255; }
    else { out[i] = A.data[i] >> 2; out[i + 1] = A.data[i + 1] >> 2; out[i + 2] = A.data[i + 2] >> 2; out[i + 3] = 255; }
  }
  const pct = ((diff / (A.w * A.h)) * 100).toFixed(3);
  if (diff > MAX) {
    failed += 1;
    await sharp(out, { raw: { width: A.w, height: A.h, channels: 4 } }).png().toFile(path.join(diffDir, name));
    console.log(`DIFF     ${name}: ${diff} px (${pct}%) -> ${path.join(diffDir, name)}`);
  } else {
    console.log(`ok       ${name}${diff ? ` (${diff} px within --max-pixels)` : ''}`);
  }
}
// Computed-style dumps (capture --styles): element-by-element, property-by-property.
const styleNames = [...new Set([...fs.readdirSync(baseDir), ...fs.readdirSync(actualDir)].filter((f) => f.endsWith('.styles.json')))].sort();
let styleFailed = 0;
for (const name of styleNames) {
  const b = path.join(baseDir, name); const a = path.join(actualDir, name);
  if (!fs.existsSync(b) || !fs.existsSync(a)) { console.log(`MISSING  ${name}`); styleFailed += 1; continue; }
  const B = JSON.parse(fs.readFileSync(b, 'utf8')); const A = JSON.parse(fs.readFileSync(a, 'utf8'));
  const props = (dump, id) => (id < 0 ? new Map() : new Map(dump.styles[id].split(';').map((kv) => { const i = kv.indexOf(':'); return [kv.slice(0, i), kv.slice(i + 1)]; })));
  if (A.elements.length !== B.elements.length) { console.log(`STYLES   ${name}: element count ${B.elements.length} -> ${A.elements.length}`); styleFailed += 1; continue; }
  const diffs = [];
  for (let i = 0; i < A.elements.length; i += 1) {
    const [pb, ...sb] = B.elements[i]; const [pa, ...sa] = A.elements[i];
    if (pb !== pa) { diffs.push(`DOM differs at ${pb} vs ${pa}`); break; }
    ['', '::before', '::after'].forEach((pseudo, k) => {
      const strB = sb[k] < 0 ? '' : B.styles[sb[k]]; const strA = sa[k] < 0 ? '' : A.styles[sa[k]];
      if (strB === strA) return; // ids index each dump's own table, so compare the strings
      const mb = props(B, sb[k]); const ma = props(A, sa[k]);
      for (const key of new Set([...mb.keys(), ...ma.keys()])) if (mb.get(key) !== ma.get(key)) diffs.push(`${pa}${pseudo} ${key}: ${mb.get(key)} -> ${ma.get(key)}`);
    });
  }
  if (diffs.length) { styleFailed += 1; console.log(`STYLES   ${name}: ${diffs.length} computed values differ\n    ${diffs.slice(0, 8).join('\n    ')}`); }
  else console.log(`ok       ${name} (${A.elements.length} elements)`);
}
failed += styleFailed;
console.log(failed ? `\n${failed} of ${names.size + styleNames.length} checks changed.` : `\nAll ${names.size} screenshots${styleNames.length ? ` and ${styleNames.length} computed-style dumps` : ''} match.`);
process.exit(failed ? 1 : 0);
