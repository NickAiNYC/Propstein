import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const readJson = (name) => JSON.parse(fs.readFileSync(`viewer/${name}`, 'utf8'));

test('public performance keeps the two cohorts separate and describes their value matches', () => {
  const board = readJson('clv_report_2026_w7.json').ledger;
  const ledger = readJson('clv_audit_report.json').records;
  const page = fs.readFileSync('viewer/performance/index.html', 'utf8');
  assert.equal(board.length, 37);
  assert.equal(ledger.length, 8);

  const marketName = { rec_yds: 'receiving_yards', rec: 'receptions' };
  const counts = { aligned: 0, differentClose: 0, unlinked: 0 };
  for (const record of ledger) {
    const candidates = board.filter((row) =>
      row.player_name === record.player && row.market === (marketName[record.market] ?? record.market) &&
      row.side === record.side && row.trigger_line === record.line && row.trigger_odds === record.odds);
    if (candidates.length !== 1) counts.unlinked++;
    else if (candidates[0].close_line === record.close_line && candidates[0].close_odds === record.close_odds) counts.aligned++;
    else counts.differentClose++;
  }

  assert.deepEqual(counts, { aligned: 1, differentClose: 2, unlinked: 5 });
  assert.match(page, /1 row whose entry and close values align/);
  assert.match(page, /2 whose entry values align but closing values differ/);
  assert.match(page, /5 with no matching Week 7 entry values/);
  assert.match(page, /do not establish that the eight entries\s+are a subset of the 37 decisions/);
});

test('public gate wording follows the preregistered commercial rule', () => {
  const gate = fs.readFileSync('docs/EDGE_GATE.md', 'utf8');
  const page = fs.readFileSync('viewer/performance/index.html', 'utf8');
  assert.match(gate, /N = 600 independently evaluable qualifying signals/);
  assert.match(page, /600 independently evaluable qualifying signals per sport/);
  assert.match(page, /N = 300 is a descriptive checkpoint, not an unlock/);
  assert.match(page, /Compliance approval is also required/);
  assert.doesNotMatch(page, /N &ge; 300 graded board decisions achieve positive CLV/);
});
