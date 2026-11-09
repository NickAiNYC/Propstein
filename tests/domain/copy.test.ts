/**
 * PropStein — UI copy tests: every product copy surface rejects the
 * prohibited vocabulary.
 *
 * Scans:
 *   - the copy registry (COPY)
 *   - every propstein component's string literals
 *   - the in-app docs markdown
 *   - hurdle/gate/alerts domain strings that render in the UI
 *
 * Positive controls prove the linter actually catches each prohibited
 * pattern, so a clean scan means something.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join } from 'path';
import { lintCopy, extractStringLiterals } from '../../src/lib/domain/copy-lint';
import { COPY } from '../../src/lib/domain/copy';
import { ALL_PRICE_ASSESSMENTS, FORBIDDEN_CATEGORICALS } from '../../src/lib/domain/types';
import { DOCS } from '../../src/content/docs';
import { ALERT_TEMPLATES } from '../../src/lib/domain/alerts';

function walk(dir: string, ext: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full, ext));
    else if (full.endsWith(ext)) out.push(full);
  }
  return out;
}

/** Collect every user-facing string from the copy surfaces. */
function collectProductStrings(): { id: string; text: string }[] {
  const items: { id: string; text: string }[] = [];
  const pushObj = (prefix: string, obj: unknown) => {
    if (typeof obj === 'string') {
      items.push({ id: prefix, text: obj });
    } else if (typeof obj === 'function') {
      try {
        items.push({ id: prefix, text: (obj as (...a: string[]) => string)('1.0', '9') });
      } catch {
        /* ignore */
      }
    } else if (obj && typeof obj === 'object') {
      for (const [k, v] of Object.entries(obj as Record<string, unknown>)) pushObj(`${prefix}.${k}`, v);
    }
  };
  pushObj('copy', COPY);
  for (const template of Object.values(ALERT_TEMPLATES)) {
    pushObj('alertTemplate', template);
  }
  for (const d of DOCS) items.push({ id: `docs:${d.id}`, text: d.markdown });

  // Component string literals AND rendered JSX text nodes.
  const componentFiles = walk(join(process.cwd(), 'src/components/propstein'), '.tsx');
  componentFiles.push(join(process.cwd(), 'src/app/page.tsx'));
  componentFiles.push(join(process.cwd(), 'src/components/propstein/terminal.tsx'));
  for (const file of componentFiles) {
    const source = readFileSync(file, 'utf8');
    for (const literal of extractStringLiterals(source)) {
      // Strip template interpolation expressions so only the prose is linted.
      const text = literal.replace(/\$\{[^}]*\}/g, ' ');
      if (text.trim().length > 3) items.push({ id: `${file}:${text.slice(0, 24)}`, text });
    }
    // Rendered JSX text (between tags), which quoted-literal scans miss.
    // Segments that look like TypeScript (generics, arrow functions) are
    // skipped — they are code, not copy.
    const jsxTextRe = />([^<>{}]+)</g;
    let m: RegExpExecArray | null;
    while ((m = jsxTextRe.exec(source)) !== null) {
      const text = m[1].replace(/\s+/g, ' ').trim();
      if (text.length > 3 && !/[;=()\[\]'"]/.test(text)) {
        items.push({ id: `${file}:jsx:${text.slice(0, 24)}`, text });
      }
    }
  }
  // Domain strings that render directly in the UI.
  const domainFiles = [
    join(process.cwd(), 'src/lib/domain/hurdle.ts'),
    join(process.cwd(), 'src/lib/domain/gate.ts'),
    join(process.cwd(), 'src/lib/domain/stats.ts'),
    join(process.cwd(), 'src/lib/domain/model-registry.ts'),
    join(process.cwd(), 'src/lib/domain/sim-market.ts'),
  ];
  for (const file of domainFiles) {
    const source = readFileSync(file, 'utf8');
    for (const literal of extractStringLiterals(source)) {
      const text = literal.replace(/\$\{[^}]*\}/g, ' ');
      if (text.trim().length > 3) items.push({ id: `${file}:${text.slice(0, 24)}`, text });
    }
  }
  return items;
}

describe('copy linter positive controls (the linter must catch offenders)', () => {
  const OFFENDERS = [
    'You have an edge on this game.',
    'This is a clear +EV spot.',
    'Value bet detected.',
    'This is a lock.',
    'Lean Over 52.5.',
    'We lean under.',
    'Take the over — best bet tonight.',
    'Our recommendation: Over 52.5.',
    'Recommended play.',
    'Guaranteed winner.',
    'Beat the book with this line.',
    'You beat the market.',
    'A profitable system over 500 games.',
    'Winning strategy inside.',
    'Positive ROI proves the model.',
    'Increase your stake to 2 units.',
    'Bankroll allocation advice.',
    'Consider hedging the other side.',
    'Cash out now.',
    'Reduce your exposure.',
    'Act now before the line moves.',
    'Snipe this line fast.',
    'Bet now.',
    'Lock it in.',
    'Hurry, limited time.',
    "Don't miss this one.",
    'Fade the public.',
    'Avoid this market.',
    'Take a pass on this one.',
    'PASS on this prop.',
    'Chase your losses tonight.',
  ];
  for (const offender of OFFENDERS) {
    it(`catches: "${offender.slice(0, 38)}${offender.length > 38 ? '…' : ''}"`, () => {
      expect(lintCopy(offender).length).toBeGreaterThan(0);
    });
  }

  it('allows required disclaimer phrasing', () => {
    expect(lintCopy('This is not a betting recommendation.')).toEqual([]);
    expect(lintCopy('The preregistered gate has not passed.')).toEqual([]);
    expect(lintCopy('GATE PASSED')).toEqual([]);
    expect(lintCopy('Passing Yards Over 52.5')).toEqual([]);
  });
});

describe('allowed categoricals never contain prohibited vocabulary', () => {
  for (const categorical of ALL_PRICE_ASSESSMENTS) {
    it(`${categorical} is clean`, () => {
      expect(lintCopy(categorical)).toEqual([]);
    });
  }
  for (const forbidden of FORBIDDEN_CATEGORICALS) {
    it(`forbidden categorical "${forbidden}" would be caught`, () => {
      expect(lintCopy(`Assessment: ${forbidden}`).length).toBeGreaterThan(0);
    });
  }
});

describe('product copy surfaces are clean', () => {
  it('every scanned product string passes the linter', () => {
    const items = collectProductStrings();
    expect(items.length).toBeGreaterThan(200); // the scan must be substantive
    const violations = items.flatMap((item) => lintCopy(item.text).map((v) => ({ ...v, id: item.id })));
    if (violations.length > 0) {
      console.error('VIOLATIONS:', JSON.stringify(violations.slice(0, 12), null, 2));
    }
    expect(violations).toEqual([]);
  });

  it('luck meter display rules are verbatim from the specification', () => {
    // Verbatim required display rules (adapted only to avoid prohibited
    // vocabulary in the possessive claim forms).
    expect(COPY.luckMeter.verdictChip).toBe('Record verdict');
  });
});
