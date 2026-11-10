'use client';

/**
 * PropStein — Live Telemetry Header.
 *
 * Top status bar: exact timestamp of the last daily model run, active model
 * versions, records analyzed today, prediction count, and a live pipeline
 * pulse. Fail-closed: without telemetry the bar renders an explicit
 * UNAVAILABLE state, never an assumed-healthy pulse.
 */

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { fmtEt } from '@/components/propstein/shared';

export interface TelemetryData {
  health: 'healthy' | 'degraded' | 'down';
  healthReason: string;
  pipelineHealthy: boolean;
  updatedAtUtc: string;
  runCount: number;
  lastRunDate: string | null;
  lastRun: {
    runId: string;
    runDate: string;
    generatedAtUtc: string;
    pipelineVersion: string;
    source: string;
    oddsProvider: string;
    seed: number;
    recordsAnalyzed: number;
    predictions: number;
    events: number;
    activeModelVersions: string[];
    allModelVersions: string[];
    selfScoring: { brier: number | null; hitRate: number | null; medianBandPp: number | null };
    movement: { n_compared: number; n_new: number; n_dropped: number; mean_abs_delta_pp: number | null };
    coverageMix: { calibrated: number; uncalibrated: number; none: number };
    executionMs: number;
    integrityHash: string | null;
  } | null;
  recentRuns: { runDate: string; predictions: number; records: number; durationMs: number; source: string }[];
}

export type TelemetryState =
  | { status: 'loading' }
  | { status: 'ok'; data: TelemetryData }
  | { status: 'unavailable'; reason: string };

export function useTelemetry(): TelemetryState {
  const [state, setState] = useState<TelemetryState>({ status: 'loading' });
  useEffect(() => {
    let cancelled = false;
    fetch('/api/pipeline/telemetry')
      .then(async (r) => {
        const json = await r.json();
        if (cancelled) return;
        if (json?.ok && json.telemetry) setState({ status: 'ok', data: json.telemetry as TelemetryData });
        else setState({ status: 'unavailable', reason: json?.detail ?? 'Telemetry endpoint did not return a usable state.' });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'unavailable', reason: 'The telemetry endpoint could not be reached.' });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

export function TelemetryHeader({ state }: { state: TelemetryState }) {
  return (
    <div className="border-b border-white/[0.07] bg-[#0D0F16]">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5 h-9 text-[11.5px]">
          {/* Pipeline pulse */}
          {state.status === 'loading' ? (
            <span className="flex items-center gap-2 text-zinc-500">
              <PulseDot color="#8B90A0" animate={false} />
              <span className="pst-label">pipeline</span>
              <span>connecting…</span>
            </span>
          ) : state.status === 'ok' && state.data.pipelineHealthy ? (
            <span className="flex items-center gap-2 text-emerald-300">
              <PulseDot color="#10B981" animate />
              <span className="pst-label text-emerald-300/80">pipeline healthy</span>
            </span>
          ) : state.status === 'ok' ? (
            <span className="flex items-center gap-2 text-amber-300">
              <PulseDot color="#F59E0B" animate />
              <span className="pst-label text-amber-300/80">pipeline {state.data.health}</span>
              <span className="text-zinc-500 hidden md:inline">{state.data.healthReason}</span>
            </span>
          ) : (
            <span className="flex items-center gap-2 text-rose-300">
              <PulseDot color="#EF4444" animate={false} />
              <span className="pst-label text-rose-300/80">pipeline output unavailable</span>
              <span className="text-zinc-500 hidden md:inline truncate max-w-[46ch]">{state.reason}</span>
            </span>
          )}

          {state.status === 'ok' && state.data.lastRun && (
            <>
              <TelemetryItem label="last daily run" mono>
                {fmtEt(state.data.lastRun.generatedAtUtc)}
              </TelemetryItem>
              <TelemetryItem label="run id" mono>
                {state.data.lastRun.runId}
              </TelemetryItem>
              <TelemetryItem label="models" mono>
                {state.data.lastRun.activeModelVersions.join(' / ')}
              </TelemetryItem>
              <TelemetryItem label="records today" mono>
                {state.data.lastRun.recordsAnalyzed.toLocaleString('en-US')}
              </TelemetryItem>
              <TelemetryItem label="predictions" mono>
                {state.data.lastRun.predictions.toLocaleString('en-US')}
              </TelemetryItem>
              {state.data.lastRun.selfScoring.brier !== null && (
                <TelemetryItem label="brier (14d)" mono>
                  {state.data.lastRun.selfScoring.brier.toFixed(4)}
                </TelemetryItem>
              )}
              <span className="hidden xl:inline text-zinc-600 pst-num">
                src: {state.data.lastRun.source} · seed {state.data.lastRun.seed}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function TelemetryItem({ label, children, mono = false }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="pst-label">{label}</span>
      <span className={cn('text-zinc-300', mono && 'pst-num')}>{children}</span>
    </span>
  );
}

function PulseDot({ color, animate }: { color: string; animate: boolean }) {
  return (
    <span className="relative inline-flex h-1.5 w-1.5" aria-hidden="true">
      <span
        className={cn('absolute inset-0 rounded-full', animate && 'pst-pulse')}
        style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}66` }}
      />
    </span>
  );
}
