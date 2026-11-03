import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * FETCH_NBA SCRIPT GATE — Phase 2, commit 6.
 *
 * The ingest script must fail closed: without BALLDONTLIE_API_KEY nothing
 * is fetched or written, and the committed fixtures remain the viewer's
 * data. Offline pure-function checks run via --selftest (zero network,
 * zero new dependencies — stdlib urllib + zoneinfo only).
 */

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPT = path.join(ROOT, 'scripts', 'fetch_nba.py');

test('fetch_nba.py --selftest: ET date keying (DST) + normalization + provenance', () => {
  const stdout = execFileSync('python3', [SCRIPT, '--selftest'], { encoding: 'utf8' });
  assert.match(stdout, /selftest OK/);
  assert.match(stdout, /DST/);
});

test('fetch_nba.py --selftest: stats tier-gate classification (401 unified gateway, 402/403 legacy)', () => {
  // The unified balldontlie gateway answers 401 for plan-gated /v1/stats
  // (verified live 2026-11-03 with a games-valid key). The script must
  // classify that as a tier block (exit 3), not a network error (exit 5).
  const stdout = execFileSync('python3', [SCRIPT, '--selftest'], { encoding: 'utf8' });
  assert.match(stdout, /tier-gate/);
  assert.match(stdout, /401\/402\/403/);
});

test('fetch_nba.py without BALLDONTLIE_API_KEY: exits 2, writes nothing, names the gate', () => {
  const result = spawnSync('python3', [SCRIPT], {
    encoding: 'utf8',
    env: { ...process.env, BALLDONTLIE_API_KEY: '' },
  });
  assert.equal(result.status, 2, 'missing key must exit 2');
  assert.match(result.stdout, /BALLDONTLIE_API_KEY is not set/);
  assert.match(result.stdout, /nothing fetched, nothing written/);
  assert.match(result.stdout, /_fixture: true/, 'points at the committed fixtures it preserves');
});

test('fetch_nba.py uses only the Python standard library', () => {
  const src = fs.readFileSync(SCRIPT, 'utf8');
  assert.ok(!/\bimport\s+(requests|httpx|aiohttp|pandas)\b/.test(src), 'no third-party imports');
  assert.match(src, /import urllib\.request/, 'stdlib HTTP layer');
});
