#!/usr/bin/env node
// Find (and optionally remove) CSS rules whose selectors can never match.
//
//   node scripts/css/dead-selectors.mjs [cssFile] [--apply] [--json report.json]
//
// A selector is DEAD when it requires a class or id that appears nowhere in the code
// that can put it in the DOM. A rule is removed only when EVERY selector in its list is
// dead. Partially dead selector lists are reported, not changed.
//
// Conservative by design (a wrong "used" only keeps a dead rule; a wrong "dead" would
// delete live styling):
// - "used" = the token appears as a whole word anywhere in viewer/ HTML/JS/SVG/small JSON
//   or in the page builders under scripts/ and src/ (CSS files themselves don't count).
// - Dynamic class names: a token like status-lean counts as used if "status-" appears as
//   a word (e.g. `status-${x}` or 'status-' + x).
// - Only tokens in the REQUIRED part of a selector are checked: anything inside :not(),
//   :is(), :where(), :has() or [attr] is ignored.
// - @keyframes and other non-rule at-rules are never touched; @media blocks left empty
//   are removed.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const args = process.argv.slice(2);
const cssFile = path.resolve(ROOT, args.find((a) => !a.startsWith('--') && !args[args.indexOf(a) - 1]?.startsWith('--json')) || 'viewer/style.css');
const APPLY = args.includes('--apply');
const jsonOut = args.includes('--json') ? args[args.indexOf('--json') + 1] : null;

// ---- usage corpus -----------------------------------------------------------
const SKIP_DIRS = new Set(['node_modules', '.git', '.visual']);
function walk(dir, exts, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, exts, out);
    else if (exts.some((x) => e.name.endsWith(x))) out.push(p);
  }
  return out;
}
const corpusFiles = [
  ...walk(path.join(ROOT, 'viewer'), ['.html', '.js', '.mjs', '.svg', '.webmanifest', '.json'])
    .filter((f) => !f.endsWith('.json') || fs.statSync(f).size < 150_000),
  ...walk(path.join(ROOT, 'scripts'), ['.py', '.mjs', '.js']).filter((f) => !f.includes(`${path.sep}css${path.sep}`)),
  ...walk(path.join(ROOT, 'src'), ['.py']),
];
const words = new Set();
for (const f of corpusFiles) for (const w of fs.readFileSync(f, 'utf8').match(/[A-Za-z0-9_-]+/g) || []) words.add(w);
const isUsed = (tok) => {
  if (words.has(tok)) return true;
  for (let i = tok.indexOf('-'); i > 0; i = tok.indexOf('-', i + 1)) if (words.has(tok.slice(0, i + 1))) return true;
  return false;
};

// ---- minimal CSS parser (comments, strings, nested @media/@supports) ---------
function parse(css, from = 0, to = css.length) {
  const nodes = []; let i = from; let start = from;
  const skipWs = () => { while (i < to) { if (/\s/.test(css[i])) i++; else if (css.startsWith('/*', i)) { const e = css.indexOf('*/', i + 2); i = e < 0 ? to : e + 2; } else break; } };
  while (i < to) {
    skipWs(); start = i; if (i >= to) break;
    // read prelude up to { or ;
    let depth = 0; let q = null;
    while (i < to) {
      const c = css[i];
      if (q) { if (c === '\\') i++; else if (c === q) q = null; i++; continue; }
      if (c === '"' || c === "'") { q = c; i++; continue; }
      if (css.startsWith('/*', i)) { const e = css.indexOf('*/', i + 2); i = e < 0 ? to : e + 2; continue; }
      if (c === '(') depth++; else if (c === ')') depth--;
      else if (depth === 0 && (c === '{' || c === ';')) break;
      i++;
    }
    const prelude = css.slice(start, i).trim();
    if (css[i] === ';') { nodes.push({ type: 'stmt', start, end: i + 1, prelude }); i++; continue; }
    const open = i; let d = 0; let q2 = null;
    for (; i < to; i++) {
      const c = css[i];
      if (q2) { if (c === '\\') i++; else if (c === q2) q2 = null; continue; }
      if (c === '"' || c === "'") { q2 = c; continue; }
      if (css.startsWith('/*', i)) { const e = css.indexOf('*/', i + 2); i = (e < 0 ? to : e + 2) - 1; continue; }
      if (c === '{') d++; else if (c === '}' && --d === 0) break;
    }
    const close = i; i++;
    const node = { start, end: i, prelude, open, close };
    if (/^@(media|supports|container|layer|document)\b/i.test(prelude)) { node.type = 'group'; node.children = parse(css, open + 1, close); }
    else if (prelude.startsWith('@')) node.type = 'at'; else node.type = 'rule';
    nodes.push(node);
  }
  return nodes;
}

// ---- selector analysis ---------------------------------------------------------
function splitTopLevel(s, sep = ',') {
  const out = []; let depth = 0; let cur = '';
  for (const c of s) { if (c === '(' || c === '[') depth++; else if (c === ')' || c === ']') depth--; if (c === sep && depth === 0) { out.push(cur); cur = ''; } else cur += c; }
  out.push(cur); return out.map((x) => x.trim()).filter(Boolean);
}
function requiredTokens(sel) {
  let s = sel.replace(/\/\*[\s\S]*?\*\//g, '');
  // drop [attr...] and functional pseudo-classes with their (possibly nested) arguments
  let changed = true;
  while (changed) {
    const before = s;
    s = s.replace(/\[[^\[\]]*\]/g, '').replace(/:(?:not|is|where|has|matches|-webkit-any|nth-[a-z-]+|lang|dir)\([^()]*\)/gi, '');
    changed = s !== before;
  }
  const toks = [];
  for (const m of s.matchAll(/([.#])(-?[_a-zA-Z][\w-]*)/g)) toks.push(m[1] + m[2]);
  return toks;
}
const deadReason = (sel) => requiredTokens(sel).find((t) => !isUsed(t.slice(1))) || null;

// ---- run ----------------------------------------------------------------------
const css = fs.readFileSync(cssFile, 'utf8');
const tree = parse(css);
const removals = []; const partial = []; let rules = 0;
function visit(nodes, inGroup) {
  for (const n of nodes) {
    if (n.type === 'group') { visit(n.children, n); continue; }
    if (n.type !== 'rule') continue;
    rules++;
    const sels = splitTopLevel(n.prelude);
    const reasons = sels.map(deadReason);
    if (reasons.every(Boolean)) removals.push({ start: n.start, end: n.end, selector: n.prelude.replace(/\s+/g, ' ').slice(0, 140), because: [...new Set(reasons)].slice(0, 4), media: inGroup ? inGroup.prelude : null });
    else if (reasons.some(Boolean)) partial.push({ selector: n.prelude.replace(/\s+/g, ' ').slice(0, 140), dead: sels.filter((_, k) => reasons[k]).length, of: sels.length });
  }
}
visit(tree, null);

const line = (off) => css.slice(0, off).split('\n').length;
const bytes = removals.reduce((a, r) => a + (r.end - r.start), 0);
const deadTokens = new Map();
for (const r of removals) for (const t of r.because) deadTokens.set(t, (deadTokens.get(t) || 0) + 1);
console.log(`${path.relative(ROOT, cssFile)}: ${rules} rules, ${removals.length} fully dead (${(bytes / 1024).toFixed(1)} KB), ${partial.length} partially dead lists (not changed)`);
console.log(`corpus: ${corpusFiles.length} files, ${words.size} distinct words`);
console.log('most common dead tokens:', [...deadTokens].sort((a, b) => b[1] - a[1]).slice(0, 25).map(([t, n]) => `${t}(${n})`).join(' '));
if (jsonOut) fs.writeFileSync(jsonOut, JSON.stringify(removals.map((r) => ({ line: line(r.start), ...r })), null, 1));

if (APPLY) {
  // remove rules (with the whitespace/newline that preceded them), then drop emptied groups
  let out = css;
  for (const r of [...removals].sort((a, b) => b.start - a.start)) {
    let s = r.start; while (s > 0 && (out[s - 1] === ' ' || out[s - 1] === '\t')) s--;
    let e = r.end; if (out[e] === '\n') e++;
    out = out.slice(0, s) + out.slice(e);
  }
  let prev;
  do { prev = out; out = out.replace(/(^|\n)[ \t]*@(media|supports)[^{]*\{\s*\}[ \t]*\n?/g, '$1'); } while (out !== prev);
  out = out.replace(/\n{4,}/g, '\n\n\n');
  fs.writeFileSync(cssFile, out);
  console.log(`applied: ${css.length} -> ${out.length} bytes (-${((css.length - out.length) / 1024).toFixed(1)} KB)`);
}
