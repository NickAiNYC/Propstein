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
console.log(failed ? `\n${failed} of ${names.size} screenshots changed.` : `\nAll ${names.size} screenshots match.`);
process.exit(failed ? 1 : 0);
