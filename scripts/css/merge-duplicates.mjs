#!/usr/bin/env node
// Merge duplicate CSS rules (same selector list, same @media context) without changing
// which declaration wins anywhere.
//
//   node scripts/css/merge-duplicates.mjs [cssFile] [--apply] [--only <selector-substring>]
//
// For each group of identical rules, earlier copies' declarations move forward into the
// LAST copy (placed before its own declarations, preserving their relative order). A
// declaration moves only if no rule between its old and new position, with any selector
// and in any context, sets a related property; otherwise it stays where it is. Moving past
// rules that don't touch the property cannot change the cascade, because specificity and
// importance travel with the declaration and only order relative to rules that set the
// same property matters.
//
// Conservative: "related" covers shorthands and their longhands, logical/physical pairs,
// font and line-height, inset and top/right/bottom/left, `all`, and vendor prefixes. Rules
// whose block contains a comment are never edited. Repeated properties inside one rule are
// kept (often deliberate fallbacks), except exact repeats with the same value.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const args = process.argv.slice(2);
const APPLY = args.includes('--apply');
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;
const cssFile = path.resolve(ROOT, args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1] === '--only')) || 'viewer/style.css');
const css = fs.readFileSync(cssFile, 'utf8');

// ---- parser (comments, strings, nested @media/@supports) ----------------------
function parse(src, from = 0, to = src.length, ctx = '') {
  const out = []; let i = from;
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
    if (/^@(media|supports)\b/i.test(prelude)) out.push(...parse(src, open + 1, close, `${ctx}${prelude.replace(/\s+/g, ' ')} | `));
    else if (!prelude.startsWith('@')) out.push({ start, end: i, open, close, prelude, ctx });
  }
  return out;
}
function splitTop(s, sep) {
  const out = []; let depth = 0; let q = null; let cur = '';
  for (let k = 0; k < s.length; k++) { const c = s[k];
    if (q) { cur += c; if (c === '\\') { cur += s[++k] ?? ''; } else if (c === q) q = null; continue; }
    if (c === '"' || c === "'") { q = c; cur += c; continue; }
    if (c === '(' || c === '[') depth++; else if (c === ')' || c === ']') depth--;
    if (c === sep && depth === 0) { out.push(cur); cur = ''; } else cur += c; }
  out.push(cur); return out;
}
const parseDecls = (body) => splitTop(body, ';').map((x) => x.trim()).filter(Boolean).map((text) => {
  const c = text.indexOf(':'); const prop = text.slice(0, c).trim().toLowerCase(); let value = text.slice(c + 1).trim();
  const important = /!\s*important\s*$/i.test(value); value = value.replace(/\s*!\s*important\s*$/i, '');
  return { prop, value, important, text };
});

// ---- property relations -----------------------------------------------------------
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
const related = (a, b) => { const fa = family(a); const fb = family(b); return fa === '*' || fb === '*' || fa === fb; };

// ---- plan -----------------------------------------------------------------------
const rules = parse(css).map((r, idx) => {
  const body = css.slice(r.open + 1, r.close);
  return { ...r, idx, body, hasComment: body.includes('/*'), key: `${r.ctx}${splitTop(r.prelude, ',').map((s) => s.trim().replace(/\s+/g, ' ')).join(', ')}`, decls: body.includes('/*') ? null : parseDecls(body) };
});
const groups = new Map();
for (const r of rules) if (!r.hasComment && r.decls) { if (!groups.has(r.key)) groups.set(r.key, []); groups.get(r.key).push(r); }
// prefix index for "does any rule in (i, j) set a property related to p" queries
const famRules = new Map(); // family -> sorted rule indexes that set it
for (const r of rules) {
  const decls = r.decls || parseDecls(r.body.replace(/\/\*[\s\S]*?\*\//g, ''));
  for (const f of new Set(decls.map((d) => family(d.prop)))) { if (!famRules.has(f)) famRules.set(f, []); famRules.get(f).push(r.idx); }
}
const conflictBetween = (prop, i, j) => {
  const fams = [family(prop), '*'];
  if (family(prop) === '*') return true;
  return fams.some((f) => (famRules.get(f) || []).some((k) => k > i && k < j));
};

// ---- pass 1: shadowed declarations ---------------------------------------------
// An earlier .x { color: red } can never win against a later .x { color: blue } when the
// later rule applies at least as broadly (top level, or the same @media): same selector,
// same specificity, later in the file. Unless the earlier one is !important and the later
// one is not. Skip when the later value uses newer CSS the earlier one may be a fallback for.
// A later declaration only beats an earlier one if the browser accepts it: an invalid or
// unsupported value is dropped, and then the earlier one applies. Ask Chromium.
const { chromium } = await import('playwright-core');
const allPairs = [...new Set(rules.flatMap((r) => (r.decls || []).map((d) => JSON.stringify([d.prop, d.value]))))];
const browser = await chromium.launch({ channel: 'chromium' });
const page = await browser.newPage();
const supportedList = await page.evaluate((pairs) => pairs.filter((p) => { const [k, v] = JSON.parse(p); return k.startsWith('--') || CSS.supports(k, v); }), allPairs);
await browser.close();
const SUPPORTED = new Set(supportedList);
const valid = (t) => SUPPORTED.has(JSON.stringify([t.prop, t.value]));
console.log(`declarations Chromium rejects (never used to shadow): ${allPairs.length - SUPPORTED.size}`);
const RISKY = /(dvh|svh|lvh|dvw|svw|lvw|color-mix|oklch|oklab|\blch\(|\blab\(|light-dark|anchor|@)/i;
const bySelector = new Map();
for (const r of rules) if (r.decls) { const sel = r.key.slice(r.ctx.length); if (!bySelector.has(sel)) bySelector.set(sel, []); bySelector.get(sel).push(r); }
let shadowed = 0;
for (const list of bySelector.values()) {
  for (let a = 0; a < list.length; a++) {
    const E = list[a];
    if (only && !E.key.includes(only)) continue;
    E.decls = E.decls.filter((d) => {
      const beaten = list.slice(a + 1).some((T) => (T.ctx === '' || T.ctx === E.ctx) && T.decls.some((t) => t.prop === d.prop && (t.important || !d.important) && !RISKY.test(t.value) && valid(t)));
      if (beaten) shadowed++;
      return !beaten;
    });
  }
}

const edits = new Map(); // rule idx -> { keep: decls[] } | { replace: decls[] }
let moved = 0; let stayed = 0; let removedRules = 0; let mergedGroups = 0;
for (const [key, list] of groups) {
  if (list.length < 2 || (only && !key.includes(only))) continue;
  const target = list[list.length - 1]; const prepend = [];
  for (const src of list.slice(0, -1)) {
    const keep = [];
    for (const d of src.decls) { if (conflictBetween(d.prop, src.idx, target.idx)) { keep.push(d); stayed++; } else { prepend.push(d); moved++; } }
    if (keep.length !== src.decls.length) edits.set(src.idx, { keep });
    if (!keep.length) removedRules++;
  }
  if (prepend.length) {
    // drop exact repeats (same prop, value, importance) where a later identical one exists
    const all = [...prepend, ...target.decls]; const seen = new Set(); const deduped = [];
    for (let k = all.length - 1; k >= 0; k--) { const sig = `${all[k].prop}|${all[k].value}|${all[k].important}`; if (seen.has(sig)) continue; seen.add(sig); deduped.unshift(all[k]); }
    edits.set(target.idx, { replace: deduped });
    mergedGroups++;
  }
}

for (const r of rules) if (r.decls && !edits.has(r.idx) && r.decls.length !== parseDecls(r.body).length) edits.set(r.idx, { keep: r.decls });
const dup = [...groups.values()].filter((l) => l.length > 1);
console.log(`${path.relative(ROOT, cssFile)}: ${rules.length} rules, ${dup.length} duplicate groups (${dup.reduce((a, l) => a + l.length, 0)} rules)`);
console.log(`shadowed declarations removed: ${shadowed}`);
console.log(`plan: ${mergedGroups} groups merged, ${moved} declarations moved, ${stayed} kept in place (a related property is set in between), ${removedRules} rules emptied and removed`);
const topbar = dup.filter((l) => l[0].key.endsWith('.pw-topbar'));
if (topbar.length) console.log(`.pw-topbar: ${topbar.map((l) => `${l.length} copies in "${l[0].ctx || 'top level'}"`).join('; ')}`);

if (APPLY) {
  let out = css;
  const indentOf = (r) => (r.body.match(/\n([ \t]+)\S/) || [, '  '])[1];
  for (const r of [...rules].sort((a, b) => b.start - a.start)) {
    const e = edits.get(r.idx); if (!e) continue;
    if (e.keep && !e.keep.length) {
      let s = r.start; while (s > 0 && (out[s - 1] === ' ' || out[s - 1] === '\t')) s--;
      let t = r.end; if (out[t] === '\n') t++;
      out = out.slice(0, s) + out.slice(t); continue;
    }
    const decls = e.keep || e.replace; const multi = r.body.includes('\n'); const ind = indentOf(r);
    const closeInd = (out.slice(0, r.close).match(/\n([ \t]*)$/) || [, ''])[1];
    const block = multi ? `\n${decls.map((d) => `${ind}${d.text};`).join('\n')}\n${closeInd}` : ` ${decls.map((d) => `${d.text};`).join(' ')} `;
    out = out.slice(0, r.open + 1) + block + out.slice(r.close);
  }
  fs.writeFileSync(cssFile, out);
  console.log(`applied: ${css.length} -> ${out.length} bytes (${((out.length - css.length) / 1024).toFixed(1)} KB)`);
}
