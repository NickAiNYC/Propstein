#!/usr/bin/env node
// Remove !important where it provably changes nothing.
//
//   node scripts/css/strip-important.mjs [cssFile] [--apply]
//
// Dropping !important from a declaration D changes the cascade only if D was winning
// BECAUSE of it, i.e. against a declaration D' of the same or a related property that would
// beat plain D. D is stripped only if every such D' would still lose to plain D:
//   - D' is not !important (anywhere), and
//   - D' has strictly lower specificity than D, or equal specificity and comes earlier in
//     the same file (cascade order across files differs per page, so other files need
//     strictly lower). D is compared at its weakest selector, D' at its strongest;
//     :where() counts 0, :is()/:not()/:has() count their strongest argument.
// Blocked outright when the property (or a related one) is
//   - set inline anywhere (HTML style="", JS el.style.x, cssText): inline beats plain D
//     but not D!important;
//   - animated by any @keyframes: animations beat plain D but not D!important.
// "Related" = shorthand/longhand, logical/physical, font/line-height, inset, all, prefixes.
// Competing stylesheets: every viewer/*.css loaded by a page that loads style.css.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const VIEWER = path.join(ROOT, 'viewer');
const args = process.argv.slice(2);
const APPLY = args.includes('--apply');
const target = path.resolve(ROOT, args.find((a) => !a.startsWith('--')) || 'viewer/style.css');

// ---- which stylesheets share pages with the target ---------------------------
const pages = ['index.html', 'ledger.html', 'audit.html', 'verify.html', 'ledger/index.html'].map((p) => path.join(VIEWER, p));
const sheets = new Set();
for (const p of pages) {
  const hrefs = [...fs.readFileSync(p, 'utf8').matchAll(/href="\/([^"?]+\.css)/g)].map((m) => path.join(VIEWER, m[1]));
  if (hrefs.includes(target)) hrefs.forEach((h) => sheets.add(h));
}

// ---- parser ------------------------------------------------------------------------
function parse(src, from = 0, to = src.length, ctx = '', out = { rules: [], keyframeProps: new Set() }) {
  let i = from;
  const skip = () => { while (i < to) { if (/\s/.test(src[i])) i++; else if (src.startsWith('/*', i)) { const e = src.indexOf('*/', i + 2); i = e < 0 ? to : e + 2; } else break; } };
  while (i < to) {
    skip(); if (i >= to) break; const start = i; let depth = 0; let q = null;
    while (i < to) { const c = src[i];
      if (q) { if (c === '\\') i++; else if (c === q) q = null; i++; continue; }
      if (c === '"' || c === "'") { q = c; i++; continue; }
      if (src.startsWith('/*', i)) { const e = src.indexOf('*/', i + 2); i = e < 0 ? to : e + 2; continue; }
      if (c === '(') depth++; else if (c === ')') depth--; else if (depth === 0 && (c === '{' || c === ';')) break; i++; }
    const prelude = src.slice(start, i).trim();
    if (src[i] === ';') { i++; continue; }
    const open = i; let d = 0; let q2 = null;
    for (; i < to; i++) { const c = src[i];
      if (q2) { if (c === '\\') i++; else if (c === q2) q2 = null; continue; }
      if (c === '"' || c === "'") { q2 = c; continue; }
      if (src.startsWith('/*', i)) { const e = src.indexOf('*/', i + 2); i = (e < 0 ? to : e + 2) - 1; continue; }
      if (c === '{') d++; else if (c === '}' && --d === 0) break; }
    const close = i; i++;
    if (/^@(media|supports)\b/i.test(prelude)) parse(src, open + 1, close, `${ctx}${prelude} | `, out);
    else if (/^@(-webkit-)?keyframes\b/i.test(prelude)) {
      for (const m of src.slice(open + 1, close).matchAll(/([-a-zA-Z]+)\s*:/g)) out.keyframeProps.add(m[1].toLowerCase());
    } else if (!prelude.startsWith('@')) out.rules.push({ start, open, close, prelude, ctx });
  }
  return out;
}
function splitTop(s, sep) {
  const out = []; let depth = 0; let q = null; let cur = '';
  for (let k = 0; k < s.length; k++) { const c = s[k];
    if (q) { cur += c; if (c === '\\') cur += s[++k] ?? ''; else if (c === q) q = null; continue; }
    if (c === '"' || c === "'") { q = c; cur += c; continue; }
    if (c === '(' || c === '[') depth++; else if (c === ')' || c === ']') depth--;
    if (c === sep && depth === 0) { out.push(cur); cur = ''; } else cur += c; }
  out.push(cur); return out;
}

// ---- specificity ---------------------------------------------------------------------
function specificity(sel) {
  let s = sel.replace(/\/\*[\s\S]*?\*\//g, '').trim(); let a = 0; let b = 0; let c = 0;
  // functional pseudo-classes: :where() = 0; :is/:not/:has/:matches = max of arguments
  for (;;) {
    const m = /:(where|is|not|has|matches|-webkit-any)\(/i.exec(s); if (!m) break;
    let d = 0; let k = m.index + m[0].length - 1;
    for (; k < s.length; k++) { if (s[k] === '(') d++; else if (s[k] === ')' && --d === 0) break; }
    const inner = s.slice(m.index + m[0].length, k);
    if (m[1].toLowerCase() !== 'where') {
      const best = splitTop(inner, ',').map((x) => specificity(x)).reduce((x, y) => (cmp(x, y) >= 0 ? x : y), [0, 0, 0]);
      a += best[0]; b += best[1]; c += best[2];
    }
    s = s.slice(0, m.index) + ' ' + s.slice(k + 1);
  }
  s = s.replace(/\[[^\]]*\]/g, () => { b++; return ' '; });
  s = s.replace(/::?(before|after|first-line|first-letter|placeholder|selection|marker|backdrop|-webkit-[a-z-]+|-moz-[a-z-]+)(?![\w-])/gi, () => { c++; return ' '; });
  s = s.replace(/:[a-zA-Z-]+(\([^)]*\))?/g, () => { b++; return ' '; });
  s = s.replace(/#[\w-]+/g, () => { a++; return ' '; });
  s = s.replace(/\.[\w-]+/g, () => { b++; return ' '; });
  for (const t of s.split(/[\s>+~]+/)) if (t && t !== '*' && /^[a-zA-Z][\w-]*$/.test(t)) c++;
  return [a, b, c];
}
function cmp(x, y) { for (let k = 0; k < 3; k++) if (x[k] !== y[k]) return x[k] - y[k]; return 0; }

// ---- property relations ---------------------------------------------------------------
function family(p) {
  if (p.startsWith('--')) return p;
  const q = p.replace(/^-(webkit|moz|ms|o)-/, '');
  if (q === 'all') return '*';
  if (['inset', 'top', 'right', 'bottom', 'left'].includes(q) || q.startsWith('inset-')) return 'inset';
  if (/^(width|height|inline-size|block-size|min-|max-|aspect-ratio)/.test(q)) return 'size';
  if (q === 'line-height' || q.startsWith('font')) return 'font';
  if (/^(gap|row-gap|column-gap|grid)/.test(q)) return 'grid';
  if (/^(place-|align-|justify-)/.test(q)) return 'align';
  if (q.startsWith('column')) return 'column';
  return q.split('-')[0];
}

// ---- collect declarations from every competing stylesheet ------------------------------
const decls = []; const keyframeFamilies = new Set();
const sources = {};
for (const file of sheets) {
  const src = fs.readFileSync(file, 'utf8'); sources[file] = src;
  const { rules, keyframeProps } = parse(src);
  keyframeProps.forEach((p) => keyframeFamilies.add(family(p)));
  for (const r of rules) {
    const sels = splitTop(r.prelude, ',').map((x) => x.trim()).filter(Boolean);
    const specs = sels.map(specificity);
    const minSpec = specs.reduce((x, y) => (cmp(x, y) <= 0 ? x : y));
    const maxSpec = specs.reduce((x, y) => (cmp(x, y) >= 0 ? x : y));
    // declarations with absolute offsets (block has no nested braces)
    let pos = r.open + 1; const body = src.slice(r.open + 1, r.close);
    for (const part of splitTop(body.replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length)), ';')) {
      const text = part; const startOff = pos; pos += part.length + 1;
      if (!text.trim() || !text.includes(':')) continue;
      const c = text.indexOf(':'); const prop = text.slice(0, c).trim().toLowerCase();
      const important = /!\s*important\s*$/i.test(text.trim());
      decls.push({ file, prop, fam: family(prop), important, minSpec, maxSpec, at: startOff, bangAt: important ? startOff + text.search(/\s*!\s*important\s*$/i) : -1, bangEnd: startOff + text.trimEnd().length });
    }
  }
}

// ---- inline styles: HTML style="", JS el.style.x / cssText / style strings -------------
const inlineFamilies = new Set();
const kebab = (s) => s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? (e.name === 'node_modules' ? [] : walk(path.join(dir, e.name))) : [path.join(dir, e.name)]));
for (const f of walk(VIEWER).filter((f) => /\.(html|js|mjs)$/.test(f))) {
  const t = fs.readFileSync(f, 'utf8');
  for (const m of t.matchAll(/\.style\.([a-zA-Z]+)\s*=/g)) if (m[1] !== 'cssText') inlineFamilies.add(family(kebab(m[1])));
  for (const m of t.matchAll(/setProperty\(\s*['"`]([a-z-]+)/g)) inlineFamilies.add(family(m[1]));
  for (const m of t.matchAll(/(?:style\s*=\s*\\?["'`]|cssText\s*=\s*["'`])([^"'`]*)/g)) for (const p of m[1].matchAll(/([-a-zA-Z]+)\s*:/g)) inlineFamilies.add(family(p[1].toLowerCase()));
}

// ---- decide ----------------------------------------------------------------------------
const byFam = new Map();
for (const d of decls) { if (!byFam.has(d.fam)) byFam.set(d.fam, []); byFam.get(d.fam).push(d); }
const allFam = byFam.get('*') || [];
const reasons = { inline: 0, keyframes: 0, competingImportant: 0, competingSpecificity: 0 };
const strip = [];
for (const D of decls.filter((d) => d.file === target && d.important)) {
  if (D.fam === '*' || inlineFamilies.has(D.fam)) { reasons.inline++; continue; }
  if (keyframeFamilies.has(D.fam)) { reasons.keyframes++; continue; }
  let ok = true;
  for (const X of [...(byFam.get(D.fam) || []), ...allFam]) {
    if (X === D) continue;
    if (X.important) { ok = false; reasons.competingImportant++; break; }
    const c = cmp(X.maxSpec, D.minSpec);
    if (c < 0) continue;
    if (c === 0 && X.file === D.file && X.at < D.at) continue;
    ok = false; reasons.competingSpecificity++; break;
  }
  if (ok) strip.push(D);
}
const total = decls.filter((d) => d.file === target && d.important).length;
console.log(`stylesheets considered: ${[...sheets].map((f) => path.relative(VIEWER, f)).join(', ')}`);
console.log(`${path.relative(ROOT, target)}: ${total} !important declarations; removable: ${strip.length}`);
console.log(`kept because: property set inline ${reasons.inline}, animated by @keyframes ${reasons.keyframes}, a competing !important exists ${reasons.competingImportant}, a competitor could win on specificity/order ${reasons.competingSpecificity}`);

if (APPLY) {
  let out = sources[target];
  for (const D of [...strip].sort((a, b) => b.bangAt - a.bangAt)) out = out.slice(0, D.bangAt) + out.slice(D.bangEnd);
  fs.writeFileSync(target, out);
  console.log(`applied: removed ${strip.length} !important (${sources[target].length - out.length} bytes)`);
}
