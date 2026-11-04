/**
 * PropStein — copy compliance linter.
 *
 * Enforces the product charter's language standards over every user-facing
 * string. The linter runs:
 *   - at test time over the copy registry and all UI component string
 *     literals, and
 *   - at runtime over the in-app copy compliance report surface.
 *
 * Safe contexts (explicitly allowlisted before patterns run):
 *   - "GATE PASSED" / "GATE PASS" / "passed" — the preregistered gate
 *     verdict vocabulary, never a pick.
 *   - "This is not a betting recommendation" and other negated disclaimer
 *     forms — required copy.
 */

export interface CopyViolation {
  pattern: string;
  text: string;
  context: string;
}

/**
 * Safe spans are masked before pattern matching. Order matters: longest first.
 */
const SAFE_MASKS: { re: RegExp; mask: string }[] = [
  { re: /GATE\s+PASSED/gi, mask: '▚GATE▚' },
  { re: /GATE\s+PASS\b/gi, mask: '▚GATE▚' },
  { re: /\bpassed\b/gi, mask: '▚ok▚' },
  { re: /\bnot\s+a\s+betting\s+recommendation\b/gi, mask: '▚ok▚' },
  { re: /\bnot\s+a\s+recommendation\b/gi, mask: '▚ok▚' },
  { re: /\bno\s+recommendation\b/gi, mask: '▚ok▚' },
  { re: /\bnever\s+a\s+recommendation\b/gi, mask: '▚ok▚' },
  // Bare status tokens (gate verdict enums used as code constants and chip
  // keys): never sentences, never pick categorical output. The pick form
  // ("Assessment: PASS") is still caught because the sentence context is not
  // masked — only the exact standalone token is.
  { re: /^\s*(PASS|FAIL|PENDING|RETIRED|IN_PROGRESS|INTERIM|INCONCLUSIVE)\s*$/, mask: '▚status▚' },
  // Model version identifiers for the passing-yards model (PASS-V2), never
  // pick categorical output.
  { re: /\bPASS-V\d+\b/g, mask: '▚model-version▚' },
];

interface LintPattern {
  name: string;
  re: RegExp;
}

const PATTERNS: LintPattern[] = [
  // Picks & actionable categoricals
  { name: 'lean', re: /\blean(s|ing)?\s+(over|under)\b/i },
  { name: 'lean', re: /\blean\b/i },
  { name: 'fade', re: /\bfade(s|d|ing)?\b/i },
  { name: 'pass-pick', re: /\bpass\b/i },
  { name: 'PASS-pick', re: /\bPASS\b/ },
  { name: 'avoid', re: /\bavoid\b/i },
  // Unproven advantage language
  { name: 'edge', re: /\bedge\b/i },
  { name: 'ev', re: /\+ev\b|\bev\b/i },
  { name: 'value', re: /\bvalue\b/i },
  { name: 'lock', re: /\block(ed|s)?\b/i },
  { name: 'best-bet', re: /\bbest\s+bet(s)?\b/i },
  { name: 'recommend', re: /\brecommend(s|ed|ation|ations)?\b/i },
  { name: 'guarantee', re: /\bguarantee(d|s)?\b/i },
  { name: 'beat-the-book', re: /\bbeat\s+the\s+book/i },
  { name: 'beat-the-market', re: /\byou\s+beat\s+the\s+market/i },
  { name: 'profitable', re: /\bprofitable\b/i },
  { name: 'winning-strategy', re: /\bwinning\s+strategy\b/i },
  { name: 'positive-roi', re: /\bpositive\s+roi\b/i },
  // Stake / exposure advice
  { name: 'stake', re: /\bstake(s|d)?\b/i },
  { name: 'bankroll', re: /\bbankroll\b/i },
  { name: 'hedge', re: /\bhedg(e|es|ed|ing)\b/i },
  { name: 'cash-out', re: /\bcash\s+out\b/i },
  { name: 'exposure', re: /\bexposure\b/i },
  // Urgency
  { name: 'act-now', re: /\bact\s+now\b/i },
  { name: 'line-moving', re: /\bbefore\s+the\s+line\s+moves\b/i },
  { name: 'snipe', re: /\bsnipe\b/i },
  { name: 'bet-now', re: /\bbet\s+now\b/i },
  { name: 'lock-it-in', re: /\block\s+it\s+in\b/i },
  { name: 'hurry', re: /\bhurry\b/i },
  { name: 'limited-time', re: /\blimited\s+time\b/i },
  { name: 'dont-miss', re: /\bdon'?t\s+miss\b/i },
  { name: 'chase', re: /\bchase\b/i },
];

/** Lint one string. Returns violations (empty array = clean). */
export function lintCopy(text: string): CopyViolation[] {
  if (!text) return [];
  let masked = text;
  for (const m of SAFE_MASKS) {
    masked = masked.replace(m.re, m.mask);
  }
  const violations: CopyViolation[] = [];
  for (const p of PATTERNS) {
    const match = p.re.exec(masked);
    if (match) {
      violations.push({ pattern: p.name, text: match[0], context: text.slice(0, 160) });
    }
  }
  return violations;
}

/** Lint a batch of strings; returns all violations found. */
export function lintCopyBatch(items: { id: string; text: string }[]): (CopyViolation & { id: string })[] {
  const out: (CopyViolation & { id: string })[] = [];
  for (const item of items) {
    for (const v of lintCopy(item.text)) {
      out.push({ ...v, id: item.id });
    }
  }
  return out;
}

/**
 * Extract string literals from source for lint scanning.
 *
 * Single- and double-quoted literals are matched within a single line (an
 * apostrophe inside a comment must not swallow code as a fake string).
 * Template literals may span lines; their interpolation expressions are the
 * caller's responsibility to strip.
 */
export function extractStringLiterals(source: string): string[] {
  const out: string[] = [];
  const single = /'([^'\\\n]*)'/g;
  const double = /"([^"\\\n]*)"/g;
  const tick = /`([^`\\]*)`/g;
  for (const re of [single, double, tick]) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(source)) !== null) {
      out.push(m[1]);
    }
  }
  return out;
}
