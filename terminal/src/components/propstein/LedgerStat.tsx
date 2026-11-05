"use client";

/* ============================================================
   PropStein — LedgerStat & PerBookCoverageBanner
   Strict sample-size & confidence interval visualization.
   On small samples, the CI interval bar carries the visual weight.
   No number appears without its sample size (n) and confidence interval.
   ============================================================ */

import React from "react";
import { cn } from "@/lib/utils";

export interface LedgerStatProps {
  label: string;
  value: number;
  ci: [number, number];
  n: number;
  nEvents?: number;
  threshold?: number;
  status?: string;
  format?: (v: number) => string;
  className?: string;
}

export function LedgerStat({
  label,
  value,
  ci,
  n,
  nEvents,
  threshold = 0,
  status,
  format = (v: number) => (v > 0 ? `+${v.toFixed(4)}` : v.toFixed(4)),
  className,
}: LedgerStatProps) {
  const [ciMin, ciMax] = ci;
  const spansThreshold = ciMin <= threshold && threshold <= ciMax;

  // Domain mapping for visual CI bar:
  // center roughly around threshold with comfortable margin
  const span = Math.max(Math.abs(ciMax - threshold), Math.abs(ciMin - threshold), 0.05);
  const domainMin = threshold - span * 1.3;
  const domainMax = threshold + span * 1.3;
  const totalDomain = domainMax - domainMin;

  const toPct = (x: number) => Math.max(0, Math.min(100, ((x - domainMin) / totalDomain) * 100));

  const ciLeftPct = toPct(ciMin);
  const ciRightPct = toPct(ciMax);
  const valPct = toPct(value);
  const threshPct = toPct(threshold);

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-[2px] border border-border bg-surface/50 p-3.5",
        className
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
          {label}
        </span>
        {status ? (
          <span
            className={cn(
              "font-mono text-[10px] tracking-wide",
              spansThreshold ? "text-caution" : "text-signal"
            )}
          >
            [{status}]
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-mono text-base font-semibold text-text">
          {format(value)}
        </span>
        <span className="text-xs text-text-muted">·</span>
        <span className="font-mono text-xs text-text-muted">
          95% CI [{format(ciMin)}, {format(ciMax)}]
        </span>
        <span className="text-xs text-text-muted">·</span>
        <span className="font-mono text-xs text-text-muted">
          n={n}
          {nEvents !== undefined ? ` across ${nEvents} events` : ""}
        </span>
      </div>

      {/* Visual CI interval bar */}
      <div className="relative mt-2 h-7 w-full select-none pt-1">
        {/* Track baseline */}
        <div className="absolute top-2.5 h-[1px] w-full bg-border" />

        {/* Zero / threshold marker line */}
        <div
          className="absolute top-1 bottom-1 w-[1px] bg-border-strong"
          style={{ left: `${threshPct}%` }}
        />

        {/* CI Interval Span Bar */}
        <div
          className={cn(
            "absolute top-2 h-1.5 rounded-[1px]",
            spansThreshold ? "bg-caution/50" : "bg-signal/60"
          )}
          style={{
            left: `${ciLeftPct}%`,
            width: `${Math.max(2, ciRightPct - ciLeftPct)}%`,
          }}
          title={`95% CI: [${ciMin.toFixed(4)}, ${ciMax.toFixed(4)}]`}
        />

        {/* Point estimate dot */}
        <div
          className="absolute top-1.5 h-2.5 w-2.5 -translate-x-1/2 rounded-full border border-surface bg-text"
          style={{ left: `${valPct}%` }}
          title={`Point estimate: ${value.toFixed(4)}`}
        />

        {/* Threshold label indicator */}
        <div
          className="absolute top-4 -translate-x-1/2 font-mono text-[9px] text-text-muted"
          style={{ left: `${threshPct}%` }}
        >
          {threshold}
        </div>

        {/* Spans zero disclosure annotation */}
        {spansThreshold && (
          <div className="absolute top-4 right-0 text-right font-mono text-[9px] text-caution">
            &larr; spans zero. No edge proven.
          </div>
        )}
      </div>
    </div>
  );
}

export interface BookCoverageItem {
  book: string;
  total: number;
  settled: number;
  pending: number;
  excluded: number;
}

export interface PerBookCoverageBannerProps {
  books?: BookCoverageItem[];
  verifiedSourcesCount?: number;
  totalSourcesCount?: number;
  lastAnchored?: string;
  ledgerRoot?: string;
  onVerifyClick?: () => void;
  className?: string;
}

export const DEFAULT_BOOK_COVERAGE: BookCoverageItem[] = [
  { book: "DraftKings", total: 84, settled: 42, pending: 38, excluded: 4 },
  { book: "FanDuel", total: 71, settled: 36, pending: 33, excluded: 2 },
  { book: "BetMGM", total: 42, settled: 19, pending: 22, excluded: 1 },
  { book: "Caesars", total: 38, settled: 18, pending: 19, excluded: 1 },
  { book: "PointsBet", total: 24, settled: 11, pending: 13, excluded: 0 },
  { book: "Pinnacle", total: 44, settled: 0, pending: 44, excluded: 0 },
];

export function PerBookCoverageBanner({
  books = DEFAULT_BOOK_COVERAGE,
  verifiedSourcesCount = 6,
  totalSourcesCount = 6,
  lastAnchored = "2026-11-03 00:00 UTC",
  ledgerRoot = "178e29974bf8748c",
  onVerifyClick,
  className,
}: PerBookCoverageBannerProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-[2px] border border-border bg-surface p-4 font-mono text-xs",
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-2">
        <span className="font-sans text-[11px] font-semibold uppercase tracking-wider text-text">
          Ledger Coverage Disclosure
        </span>
        <span className="text-[11px] text-text-muted">
          Per-Book Population Funnel
        </span>
      </div>

      <div className="divide-y divide-border/40">
        {books.map((b) => {
          const rate = b.settled + b.pending > 0 ? (b.settled / (b.settled + b.pending)) * 100 : 0;
          return (
            <div
              key={b.book}
              className="flex flex-wrap items-center justify-between py-1.5 text-text"
            >
              <div className="flex items-center gap-2 w-32">
                <span className="font-sans font-medium">{b.book}</span>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-text-muted">
                <span>{b.total} records</span>
                <span>·</span>
                <span className="text-text">{b.settled} settled</span>
                <span>·</span>
                <span>{b.pending} pending</span>
                <span>·</span>
                <span>{b.excluded} excluded</span>
                <span>·</span>
                <span className="font-semibold text-text-muted">
                  {rate.toFixed(0)}% settled
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between border-t border-border pt-2 text-[11px] text-text-muted">
        <div>
          Verified sources: {verifiedSourcesCount} of {totalSourcesCount} · Last anchored:{" "}
          <span className="text-text">{lastAnchored}</span>
        </div>
        <div className="flex items-center gap-2">
          <span>Ledger root: #{ledgerRoot}</span>
          <button
            type="button"
            onClick={onVerifyClick}
            className="rounded-[2px] border border-border px-1.5 py-0.5 text-xs text-text hover:bg-workspace"
          >
            [ verify ]
          </button>
        </div>
      </div>
    </div>
  );
}

