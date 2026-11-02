import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { buildSandbox, loadApp, VIEWER } from './helpers/sandbox.mjs';

const CONFIG_PATH = path.join(VIEWER, 'circuit_breaker_config.json');
const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
const config = JSON.parse(raw);

test('breaker config: versioned with the mandated YYYY.MM.DD-N format', () => {
  assert.match(config.config_version, /^\d{4}\.\d{2}\.\d{2}-\d+$/, 'config_version must match YYYY.MM.DD-N');
});

test('breaker config: per-sport structure with every sport declaring calibration status', () => {
  assert.ok(config.sports, 'config must namespace by sport');
  for (const [sportId, block] of Object.entries(config.sports)) {
    if (block.calibrated === true) continue;
    // Any sport WITHOUT backtest evidence must be explicitly marked
    // uncalibrated (spec item 5) — the UI shows a research-only badge.
    assert.equal(
      block.calibration, 'uncalibrated_tuning_parameters',
      `sport "${sportId}" must carry calibrated:true or the explicit uncalibrated marker`,
    );
  }
});

test('breaker config: NFL block is calibrated and keeps exact pre-refactor values', () => {
  const nfl = config.sports.nfl;
  assert.equal(nfl.calibrated, true);
  assert.equal(nfl.thresholds.drift_pct_hurdle, 0.12);
  assert.equal(nfl.thresholds.high_edge_caution_hurdle, 0.15);
  assert.equal(nfl.thresholds.cooldown_minutes, 15);
  assert.equal(nfl.thresholds.deadman_switch_max_age_seconds, 300);
  assert.equal(nfl.markets.receiving_yards.drift_hurdle, 5.0);
  assert.equal(nfl.markets.receiving_yards.beneficiary_max_drift, 8.5);
  assert.equal(nfl.markets.receptions.drift_hurdle, 1.0);
  assert.equal(nfl.markets.receptions.beneficiary_max_drift, 2.0);
  // Legacy quirk preserved: anytime_td inherited reception-scale bounds.
  assert.equal(nfl.markets.anytime_td.drift_hurdle, 1.0);
  assert.equal(nfl.markets.anytime_td.beneficiary_max_drift, 2.0);
});

test('breaker config: NFL messaging strings preserved verbatim', () => {
  const messaging = config.sports.nfl.messaging;
  for (const key of ['line_moved_label', 'stale_baseline_warning', 'beneficiary_oversteam_warning', 'high_edge_warning', 'stale_feed_warning']) {
    assert.ok(messaging[key] && messaging[key].length > 10, `messaging.${key} missing`);
  }
});

test('viewer resolves breaker parameters from config with fallback', async () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  await P.loadSlate('2026_w7');

  assert.ok(P.state.breakerConfig, 'breaker config must be fetched at slate load');
  const yards = P.breakerFor('receiving_yards');
  assert.equal(yards.source, 'config');
  assert.equal(yards.driftHurdle, 5.0);
  assert.equal(yards.beneficiaryMax, 8.5);
  assert.equal(yards.pctHurdle, 0.12);
  assert.equal(yards.highEdge, 0.15);
  assert.equal(yards.calibrated, true);
  // 2026.11.02-1 adds the banner-layer news_feed_stale_max_age_seconds (24h
  // display window). The 300s dead-man dispatch latch is untouched and stays
  // pinned above — only the version pin moves with the announced change.
  assert.equal(yards.configVersion, '2026.11.02-1');

  const td = P.breakerFor('anytime_td');
  assert.equal(td.driftHurdle, 1.0);
  assert.equal(td.beneficiaryMax, 2.0);
});

test('viewer falls back to adapter breaker values when config fetch fails', async () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  // Simulate config fetch failure.
  P.state.breakerConfig = null;
  const yards = P.breakerFor('receiving_yards');
  assert.equal(yards.source, 'adapter-fallback');
  assert.equal(yards.driftHurdle, 5.0);
  assert.equal(yards.beneficiaryMax, 8.5);
  assert.equal(yards.highEdge, 0.15);
});

test('sniper_cron.py reads the per-sport config shape (and legacy fallback)', () => {
  const cronSrc = fs.readFileSync(path.join(VIEWER, '..', 'scripts', 'sniper_cron.py'), 'utf8');
  assert.ok(cronSrc.includes('sports").get("nfl"') || cronSrc.includes('.get("sports")'), 'cron reader must consult sports.nfl');
  assert.ok(cronSrc.includes('drift_hurdle'), 'cron reader must read per-market drift_hurdle');
  assert.ok(cronSrc.includes('cb_cfg.get("thresholds", {})') || cronSrc.includes('cb_cfg.get("thresholds"'), 'cron reader must keep a legacy flat-shape fallback');
});
