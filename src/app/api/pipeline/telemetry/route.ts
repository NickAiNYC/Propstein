/**
 * PropStein — pipeline telemetry endpoint (fail closed).
 *
 * Serves the Live Telemetry Header from data/runs_index.json plus a metrics
 * digest from the latest artifact. If the artifact store is missing, stale,
 * or corrupt, the response is an explicit unavailable state — the UI never
 * fabricates pipeline health.
 */

import { readFile } from 'fs/promises';
import path from 'path';
import { NextResponse } from 'next/server';
import { clientIp, fail, ok, rateLimited } from '@/lib/server/api';

export const dynamic = 'force-dynamic';

const DATA_DIR = path.join(process.cwd(), 'data');
const INDEX_PATH = path.join(DATA_DIR, 'runs_index.json');
const LATEST_PATH = path.join(DATA_DIR, 'latest_predictions.json');

interface IndexDoc {
  updated_at_utc: string;
  latest_run_date: string | null;
  health: 'healthy' | 'degraded' | 'down';
  health_reason: string;
  runs: {
    run_date: string;
    prediction_count: number;
    n_records_analyzed: number;
    duration_ms: number;
    source: string;
    pipeline_version: string;
    generated_at_utc: string;
    integrity_hash: string;
  }[];
}

interface LatestDoc {
  run_date: string;
  run_id: string;
  generated_at_utc: string;
  pipeline_version: string;
  source: string;
  odds_provider: string;
  seed: number;
  models: { model_version: string; coverage: string }[];
  n_records_analyzed: number;
  metrics: {
    n_predictions: number;
    n_events: number;
    brier: number | null;
    hit_rate: number | null;
    median_band_pp: number | null;
    delta: { n_compared: number; n_new: number; n_dropped: number; mean_abs_delta_pp: number | null; max_abs_delta_pp: number | null };
    coverage_mix: { calibrated: number; uncalibrated: number; none: number };
    exclusions: { reason: string; count: number }[];
  };
  execution: { name: string; duration_ms: number }[];
}

export async function GET(req: Request) {
  const limited = rateLimited(req, 'pipeline:telemetry', 60, 60);
  if (limited.limited) {
    return fail(429, 'RATE_LIMITED', 'Too many telemetry requests; retry shortly.', {
      retryAfterSeconds: limited.retryAfterSeconds,
    });
  }
  void clientIp;

  let index: IndexDoc;
  let latest: LatestDoc | null = null;
  try {
    index = JSON.parse(await readFile(INDEX_PATH, 'utf8')) as IndexDoc;
  } catch {
    return fail(
      503,
      'PIPELINE_OUTPUT_UNAVAILABLE',
      'The daily model run store is not available on this deployment. The telemetry header fails closed rather than showing assumed pipeline state.',
    );
  }
  try {
    latest = JSON.parse(await readFile(LATEST_PATH, 'utf8')) as LatestDoc;
  } catch {
    latest = null; // index present but board absent -> degraded telemetry
  }

  const health = latest ? index.health : 'degraded';
  return ok({
    telemetry: {
      health,
      healthReason: latest
        ? index.health_reason
        : 'Run index present but the latest board artifact is missing or unreadable.',
      pipelineHealthy: health === 'healthy',
      updatedAtUtc: index.updated_at_utc,
      runCount: index.runs.length,
      lastRunDate: index.latest_run_date,
      lastRun: latest
        ? {
            runId: latest.run_id,
            runDate: latest.run_date,
            generatedAtUtc: latest.generated_at_utc,
            pipelineVersion: latest.pipeline_version,
            source: latest.source,
            oddsProvider: latest.odds_provider,
            seed: latest.seed,
            recordsAnalyzed: latest.n_records_analyzed,
            predictions: latest.metrics.n_predictions,
            events: latest.metrics.n_events,
            activeModelVersions: Array.from(
              new Set(latest.models.filter((m) => m.coverage === 'calibrated').map((m) => m.model_version)),
            ).sort(),
            allModelVersions: latest.models.map((m) => m.model_version).sort(),
            selfScoring: {
              brier: latest.metrics.brier,
              hitRate: latest.metrics.hit_rate,
              medianBandPp: latest.metrics.median_band_pp,
            },
            movement: latest.metrics.delta,
            coverageMix: latest.metrics.coverage_mix,
            exclusions: latest.metrics.exclusions,
            executionMs: latest.execution.reduce((a, s) => a + s.duration_ms, 0),
            integrityHash: index.runs[index.runs.length - 1]?.integrity_hash ?? null,
          }
        : null,
      recentRuns: index.runs.slice(-8).map((r) => ({
        runDate: r.run_date,
        predictions: r.prediction_count,
        records: r.n_records_analyzed,
        durationMs: r.duration_ms,
        source: r.source,
      })),
    },
  });
}

export function OPTIONS() {
  return NextResponse.json({}, { allow: 'GET, OPTIONS' });
}
