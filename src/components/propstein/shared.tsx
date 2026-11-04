/**
 * PropStein — shared UI primitives: formatting, chips, labels.
 * All user-facing strings here are part of the lint-scanned copy surface.
 */

import { cn } from '@/lib/utils';
import type { PriceAssessment } from '@/lib/domain/types';

export function fmtEt(isoUtc: string | null | undefined): string {
  if (!isoUtc) return '—';
  const d = new Date(isoUtc);
  if (Number.isNaN(d.getTime())) return '—';
  return (
    new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(d) + ' ET'
  );
}

export function fmtPp(pp: number | null | undefined, digits = 2): string {
  if (pp === null || pp === undefined || !Number.isFinite(pp)) return '—';
  return `${pp >= 0 ? '+' : ''}${pp.toFixed(digits)} pp`;
}

export function fmtPct(p: number | null | undefined, digits = 1): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return '—';
  return `${(p * 100).toFixed(digits)}%`;
}

export function fmtSignedPct(p: number | null | undefined, digits = 1): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return '—';
  const v = p * 100;
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

export function fmtAmerican(odds: number | null | undefined): string {
  if (odds === null || odds === undefined || !Number.isFinite(odds)) return '—';
  return odds > 0 ? `+${Math.round(odds)}` : `${Math.round(odds)}`;
}

export function fmtAge(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return 'unknown';
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'}`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'}`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? '' : 's'}`;
}

// ---------------------------------------------------------------------------
// Status chips for the 9 categorical price assessments
// ---------------------------------------------------------------------------

const CHIP_STYLES: Record<string, string> = {
  'PRICE ABOVE MARKET HURDLE': 'border-teal-800/40 bg-teal-800/5 text-teal-900',
  'PRICE AT MARKET HURDLE': 'border-zinc-500/40 bg-zinc-500/5 text-zinc-700',
  'PRICE BELOW MARKET HURDLE': 'border-amber-900/40 bg-amber-900/5 text-amber-900',
  'INSUFFICIENT MARKET DATA': 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
  'STALE QUOTE': 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
  'UNVERIFIED CONTEXT': 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
  'NO MODEL COVERAGE': 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
  'MODEL UNAVAILABLE': 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
  SETTLED: 'border-zinc-700/50 bg-zinc-800 text-zinc-50',
};

export function AssessmentChip({
  assessment,
  className,
  size = 'md',
}: {
  assessment: PriceAssessment | string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const style = CHIP_STYLES[assessment] ?? 'border-zinc-500/40 bg-zinc-500/5 text-zinc-700';
  return (
    <span
      role="status"
      aria-label={`Price assessment: ${assessment}`}
      className={cn(
        'inline-flex items-center rounded-sm border px-2 py-0.5 font-medium tracking-wide',
        size === 'lg' ? 'text-sm px-3 py-1' : size === 'sm' ? 'text-[11px]' : 'text-xs',
        style,
        className,
      )}
    >
      {assessment}
    </span>
  );
}

export function QualityChip({ quality }: { quality: string }) {
  const map: Record<string, string> = {
    fresh: 'border-teal-800/40 bg-teal-800/5 text-teal-900',
    stale: 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
    missing: 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
    conflicting: 'border-amber-700/50 bg-amber-700/5 text-amber-800 border-dashed',
    pending: 'border-zinc-500/40 bg-zinc-500/5 text-zinc-600',
    settled: 'border-zinc-700/50 bg-zinc-800 text-zinc-50',
    push: 'border-zinc-500/40 bg-zinc-500/5 text-zinc-600',
    void: 'border-zinc-500/40 bg-zinc-500/5 text-zinc-600',
    canceled: 'border-zinc-500/40 bg-zinc-500/5 text-zinc-600',
    dnp: 'border-zinc-500/40 bg-zinc-500/5 text-zinc-600',
    win: 'border-zinc-600/50 bg-zinc-100 text-zinc-800',
    loss: 'border-zinc-600/50 bg-zinc-100 text-zinc-800',
  };
  return (
    <span className={cn('inline-flex items-center rounded-sm border px-2 py-0.5 text-[11px] font-medium tracking-wide', map[quality] ?? map.pending)}>
      {quality.toUpperCase()}
    </span>
  );
}

export function SectionLabel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('pst-label font-medium', className)}>{children}</div>;
}

export function MetaRow({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 border-b border-zinc-100 last:border-b-0">
      <span className="pst-label shrink-0">{label}</span>
      <span className={cn('text-right text-[13px] text-zinc-800', mono && 'pst-num')}>{children}</span>
    </div>
  );
}

export function Note({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'warn' | 'teal' }) {
  return (
    <p
      className={cn(
        'text-[12px] leading-relaxed',
        tone === 'warn' ? 'text-amber-800' : tone === 'teal' ? 'text-teal-900' : 'text-zinc-500',
      )}
    >
      {children}
    </p>
  );
}

export const MARKET_LABELS: Record<string, string> = {
  player_reception_yds: 'Receiving Yards',
  player_passing_yds: 'Passing Yards',
  player_rushing_yds: 'Rushing Yards',
  player_points: 'Points',
  player_rebounds: 'Rebounds',
  player_assists: 'Assists',
  fighter_prize_money: 'Prize Money',
};

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] ?? market;
}

export function selectionLabel(selection: string): string {
  return selection === 'over' ? 'Over' : 'Under';
}
