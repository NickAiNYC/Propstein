import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');

test('evidence integrity: no seeded generators or synthetic cohorts in evidence modules', () => {
  const evidenceFiles = [
    path.join(ROOT, 'terminal/src/components/propstein/PerformancePage.tsx'),
    path.join(ROOT, 'terminal/src/lib/propstein/archive.ts'),
    path.join(ROOT, 'terminal/src/lib/data/research-board.ts'),
    path.join(ROOT, 'terminal/lib/data/research-board.ts'),
    path.join(ROOT, 'viewer/clv_report_2026_w7.json'),
    path.join(ROOT, 'viewer/holdout_eval_2026_w1.json'),
  ];

  const BANNED_PATTERNS = [
    { pattern: /mulberry32/i, desc: 'mulberry32 seeded PRNG' },
    { pattern: /\b372\b/, desc: '372 synthetic simulated markets count' },
    { pattern: /hand-coded.*imperfection/i, desc: 'synthetic calibration imperfection' },
    { pattern: /seeded.*random/i, desc: 'seeded random generation' },
  ];

  for (const file of evidenceFiles) {
    if (!fs.existsSync(file)) continue;
    const content = fs.readFileSync(file, 'utf8');
    for (const { pattern, desc } of BANNED_PATTERNS) {
      assert.ok(
        !pattern.test(content),
        `FAIL CLOSED: Evidence integrity violation in ${path.relative(ROOT, file)}: found banned ${desc}`
      );
    }
  }
});

test('evidence integrity: gate counter requires independently evaluable qualifying signals', () => {
  const boardFiles = [
    path.join(ROOT, 'terminal/src/lib/data/research-board.ts'),
    path.join(ROOT, 'terminal/lib/data/research-board.ts'),
  ];

  for (const file of boardFiles) {
    if (!fs.existsSync(file)) continue;
    const content = fs.readFileSync(file, 'utf8');
    assert.ok(
      content.includes("s.decision_at < s.event_start_at"),
      `${path.relative(ROOT, file)} must enforce pre-kickoff registration timing in evaluable counter`
    );
    assert.ok(
      /NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+withdrawals/i.test(content),
      `${path.relative(ROOT, file)} must exclude withdrawals from evaluable counter`
    );
    assert.ok(
      /result\s+IN\s+\('push',\s*'void',\s*'dnp',\s*'cancelled'\)/i.test(content),
      `${path.relative(ROOT, file)} must exclude push/void/dnp/cancelled settlements from evaluable counter`
    );
  }
});
