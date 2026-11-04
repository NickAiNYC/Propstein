import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');

test('evidence integrity: no seeded generators or synthetic cohorts in required evidence modules', () => {
  const requiredEvidenceFiles = [
    path.join(ROOT, 'terminal/src/components/propstein/PerformancePage.tsx'),
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

  for (const file of requiredEvidenceFiles) {
    assert.ok(
      fs.existsSync(file),
      `FAIL CLOSED: Required evidence file missing: ${path.relative(ROOT, file)}`
    );
    const content = fs.readFileSync(file, 'utf8');
    for (const { pattern, desc } of BANNED_PATTERNS) {
      assert.ok(
        !pattern.test(content),
        `FAIL CLOSED: Evidence integrity violation in ${path.relative(ROOT, file)}: found banned ${desc}`
      );
    }
  }

  // If archive.ts exists, verify it contains zero synthetic patterns
  const archivePath = path.join(ROOT, 'terminal/src/lib/propstein/archive.ts');
  if (fs.existsSync(archivePath)) {
    const archiveContent = fs.readFileSync(archivePath, 'utf8');
    for (const { pattern, desc } of BANNED_PATTERNS) {
      assert.ok(
        !pattern.test(archiveContent),
        `FAIL CLOSED: Evidence integrity violation in archive.ts: found banned ${desc}`
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
    assert.ok(
      fs.existsSync(file),
      `FAIL CLOSED: Board file missing: ${path.relative(ROOT, file)}`
    );
    const content = fs.readFileSync(file, 'utf8');
    assert.ok(
      content.includes("s.captured_at < s.event_start_at"),
      `${path.relative(ROOT, file)} must enforce pre-kickoff registration timing (captured_at < event_start_at) in evaluable counter`
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

test('evidence integrity: behavioral evaluability filter against mock fixture', () => {
  // Evaluability filter logic identical to the Postgres query in EVALUABLE_COUNT_SQL
  function isSignalEvaluable(signal, closing, withdrawals, settlements) {
    if (signal.amendment_id !== 'AMEND-001') return false;
    if (!(new Date(signal.captured_at) < new Date(signal.event_start_at))) return false;
    if (!closing || closing.match_status !== 'MATCHED' || closing.reason_code !== null || !closing.settlement_rules) return false;
    if (withdrawals.some(w => w.signal_id === signal.id)) return false;
    if (settlements.some(s => s.signal_id === signal.id && ['push', 'void', 'dnp', 'cancelled'].includes(s.result))) return false;
    return true;
  }

  const baseStart = "2026-11-08T18:00:00Z";
  const fixtureSignals = [
    { id: 'sig-1', captured_at: "2026-11-08T16:00:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // valid
    { id: 'sig-2', captured_at: "2026-11-08T18:05:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // post-kickoff
    { id: 'sig-3', captured_at: "2026-11-08T15:00:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // withdrawn
    { id: 'sig-4', captured_at: "2026-11-08T15:00:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // push
    { id: 'sig-5', captured_at: "2026-11-08T15:00:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // void
    { id: 'sig-6', captured_at: "2026-11-08T15:00:00Z", event_start_at: baseStart, amendment_id: 'AMEND-001' }, // unmatched close
  ];

  const closingMap = {
    'sig-1': { match_status: 'MATCHED', reason_code: null, settlement_rules: 'standard' },
    'sig-2': { match_status: 'MATCHED', reason_code: null, settlement_rules: 'standard' },
    'sig-3': { match_status: 'MATCHED', reason_code: null, settlement_rules: 'standard' },
    'sig-4': { match_status: 'MATCHED', reason_code: null, settlement_rules: 'standard' },
    'sig-5': { match_status: 'MATCHED', reason_code: null, settlement_rules: 'standard' },
    'sig-6': { match_status: 'UNMATCHED', reason_code: 'LINE_CHANGED', settlement_rules: 'standard' },
  };

  const withdrawals = [{ signal_id: 'sig-3' }];
  const settlements = [
    { signal_id: 'sig-1', result: 'win' },
    { signal_id: 'sig-4', result: 'push' },
    { signal_id: 'sig-5', result: 'void' },
  ];

  const evaluable = fixtureSignals.filter(s =>
    isSignalEvaluable(s, closingMap[s.id], withdrawals, settlements)
  );

  assert.equal(evaluable.length, 1);
  assert.equal(evaluable[0].id, 'sig-1');
});

test('evidence integrity: copy lint bans promotional tout copy in public views', () => {
  const publicFiles = [
    path.join(ROOT, 'viewer/app.js'),
    path.join(ROOT, 'viewer/index.html'),
    path.join(ROOT, 'viewer/ledger.html'),
    path.join(ROOT, 'viewer/audit.html'),
    path.join(ROOT, 'viewer/performance/index.html'),
    path.join(ROOT, 'terminal/src/components/propstein/PerformancePage.tsx'),
  ];

  const TOUT_PATTERNS = [
    { pattern: /\b(value bet|best bet|lean over|lean under|beat the book|act now|before the line moves)\b/i, desc: 'tout betting CTA' },
    { pattern: /\b(guaranteed\s+(return|profit|win)|guaranteed\s+edge)\b/i, desc: 'guaranteed edge tout claim' },
    { pattern: /\b(positive\s+ev\s+picks|lock\s+of\s+the\s+day)\b/i, desc: 'tout pick label' },
  ];

  for (const file of publicFiles) {
    assert.ok(
      fs.existsSync(file),
      `FAIL CLOSED: Public file missing: ${path.relative(ROOT, file)}`
    );
    const content = fs.readFileSync(file, 'utf8');
    for (const { pattern, desc } of TOUT_PATTERNS) {
      assert.ok(
        !pattern.test(content),
        `FAIL CLOSED: Tout copy violation in ${path.relative(ROOT, file)}: found ${desc}`
      );
    }
  }

  // Verify performance page explicit disclaimers
  const perfContent = fs.readFileSync(path.join(ROOT, 'viewer/performance/index.html'), 'utf8');
  assert.ok(
    perfContent.includes("Descriptive record only. No performance, profitability, or predictive-advantage claim is implied."),
    "viewer/performance/index.html must display the descriptive-only research disclaimer"
  );
  assert.ok(
    perfContent.includes("0 / 600 Prospective Signals (0.0%)"),
    "viewer/performance/index.html banner must state 0 / 600 Prospective Signals"
  );

  // Verify no bankroll inputs remain in any public HTML files
  for (const htmlFile of ['viewer/index.html', 'viewer/ledger.html', 'viewer/audit.html']) {
    const htmlContent = fs.readFileSync(path.join(ROOT, htmlFile), 'utf8');
    assert.ok(
      !htmlContent.includes("settingsBankrollInput"),
      `FAIL CLOSED: ${htmlFile} contains residual settingsBankrollInput`
    );
    assert.ok(
      !htmlContent.includes("Bankroll Sizing"),
      `FAIL CLOSED: ${htmlFile} contains residual Bankroll Sizing section`
    );
    assert.ok(
      !htmlContent.includes("modalGateMinus"),
      `FAIL CLOSED: ${htmlFile} contains residual interactive modalGateMinus button`
    );
  }
});
