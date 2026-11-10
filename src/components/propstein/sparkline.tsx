'use client';

/**
 * PropStein — inline sparkline for daily model probability series.
 *
 * Pure SVG, no dependencies. Null points (withheld numbers on prior days)
 * create a gap in the line rather than being silently dropped: the point is
 * rendered as a hollow marker at the last known level.
 */

import { cn } from '@/lib/utils';

export interface SparkPoint {
  run_date: string;
  p: number | null;
}

export function Sparkline({
  points,
  width = 96,
  height = 26,
  tone = 'auto',
  className,
  ariaLabel,
}: {
  points: SparkPoint[];
  width?: number;
  height?: number;
  tone?: 'auto' | 'emerald' | 'rose' | 'indigo';
  className?: string;
  ariaLabel?: string;
}) {
  const known = points.filter((pt) => pt.p !== null) as { run_date: string; p: number }[];
  if (known.length === 0) {
    return (
      <svg width={width} height={height} className={cn('opacity-30', className)} aria-hidden="true">
        <line x1={2} y1={height / 2} x2={width - 2} y2={height / 2} stroke="currentColor" strokeWidth={1} strokeDasharray="2 3" />
      </svg>
    );
  }

  const values = known.map((pt) => pt.p);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 0.08; // flat series still renders visibly separated
  const pad = (0.35 * span) / 1.7; // vertical breathing room, keeps stroke inside
  const lo = min - pad;
  const hi = max + pad;

  const xStep = points.length > 1 ? (width - 6) / (points.length - 1) : 0;
  const xAt = (i: number) => 3 + i * xStep;
  const yAt = (p: number) => height - 3 - ((p - lo) / (hi - lo)) * (height - 6);

  // Build path segments; a null point breaks the line into a gap.
  const segments: string[] = [];
  let current: string[] = [];
  points.forEach((pt, i) => {
    if (pt.p === null) {
      if (current.length > 0) {
        segments.push(current.join(' '));
        current = [];
      }
      return;
    }
    current.push(`${current.length === 0 ? 'M' : 'L'}${xAt(i).toFixed(1)},${yAt(pt.p).toFixed(1)}`);
  });
  if (current.length > 0) segments.push(current.join(' '));

  const lastIdx = points.length - 1;
  const lastPoint = points[lastIdx];
  const lastKnown = lastPoint?.p ?? values[values.length - 1];
  const rising = values.length > 1 ? lastKnown >= values[0] : true;

  const stroke =
    tone === 'emerald'
      ? '#10B981'
      : tone === 'rose'
        ? '#EF4444'
        : tone === 'indigo'
          ? '#6366F1'
          : rising
            ? '#10B981'
            : '#EF4444';

  return (
    <svg
      width={width}
      height={height}
      className={cn('shrink-0', className)}
      role="img"
      aria-label={ariaLabel ?? 'Daily model probability series'}
    >
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke={stroke} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" opacity={0.9} />
      ))}
      {/* markers for withheld points (gap dots) */}
      {points.map((pt, i) =>
        pt.p === null ? (
          <circle key={`gap-${i}`} cx={xAt(i)} cy={height / 2} r={1.6} fill="none" stroke="#8B90A0" strokeWidth={1} opacity={0.6} />
        ) : null,
      )}
      {lastPoint?.p !== null && lastPoint?.p !== undefined ? (
        <circle cx={xAt(lastIdx)} cy={yAt(lastPoint.p)} r={2.1} fill={stroke} />
      ) : null}
    </svg>
  );
}
