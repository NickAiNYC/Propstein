// components/slate/top-qualified-play.tsx
import type { QualifiedPlaySummary, GateClause } from "@/lib/types/slate";
import { deriveCardState, firstFailingHardClause } from "@/lib/types/slate";
import { VerificationBadge } from "@/components/primitives/verification-badge";
import { TabularNumber } from "@/components/primitives/tabular-number";

const STATE_STYLE = {
  QUALIFIED: { border: "border-semantic-verified/40", bg: "bg-semantic-verified/[0.03]", accent: "text-semantic-verified" },
  WATCH: { border: "border-semantic-observed/40", bg: "bg-semantic-observed/[0.03]", accent: "text-semantic-observed" },
  BLOCKED_DATA: { border: "border-semantic-stale/40", bg: "bg-semantic-stale/[0.05]", accent: "text-semantic-stale" },
  BLOCKED_GATE: { border: "border-semantic-stale/40", bg: "bg-semantic-stale/[0.05]", accent: "text-semantic-stale" },
} as const;

export function TopQualifiedPlay({ play }: { play: QualifiedPlaySummary | null }) {
  if (!play) {
    return (
      <section className="rounded border border-layer-3 bg-layer-1 p-4">
        <h2 className="text-[11px] uppercase tracking-wider text-text-secondary">Top Qualified Play</h2>
        <p className="mt-6 text-center text-xs text-text-tertiary">
          No qualifying plays this slate. Nothing to size.
        </p>
      </section>
    );
  }

  const state = deriveCardState(play);
  const s = STATE_STYLE[state];
  const failing = firstFailingHardClause(play);
  const locked = state.startsWith("BLOCKED");

  return (
    <section
      aria-labelledby="top-play-heading"
      className={`rounded border ${s.border} ${s.bg} p-4`}
    >
      {/* Header — player + bet, compact */}
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="top-play-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
            {state === "QUALIFIED" ? "Top Qualified Play" : "Top Research Line"}
          </h2>
          <p className="mt-1 truncate text-sm text-text-primary">
            <span className="font-medium">{play.player_name}</span>
            <span className="text-text-tertiary"> · </span>
            <span className="capitalize">{play.side}</span>{" "}
            <TabularNumber>{play.line}</TabularNumber>
            <span className="text-text-tertiary"> · </span>
            <span className="text-text-secondary">{play.market}</span>
            <span className="text-text-tertiary"> · </span>
            <span className="text-text-secondary">{play.book_id}</span>
          </p>
        </div>
        <VerificationBadge status={play.verification_status} />
      </header>

      {/* Primary metric — dominates */}
      <div className="mt-4 flex items-end justify-between gap-4">
        <div className="flex-1">
          {locked ? (
            <>
              <div className={`text-4xl font-semibold tracking-tight ${s.accent}`}>BLOCKED</div>
              <p className="mt-0.5 text-[11px] text-text-secondary">
                {state === "BLOCKED_DATA"
                  ? state === "BLOCKED_DATA" && play.verification_status === "OBSERVED"
                    ? "Quote not verified — action locked until an independent receipt and Python gate decision are available."
                    : `${play.verification_status.toLowerCase()} feed — action locked until quote is VERIFIED.`
                  : failing
                    ? `Gate failed: ${failing.label} (${failing.actual} ${failing.operator} ${failing.threshold})`
                    : "Gate reasoning unavailable from the Python model artifact. Action locked."}
              </p>
            </>
          ) : (
            <>
              <div className="text-[11px] uppercase tracking-wider text-text-secondary">
                {state === "WATCH" ? "Edge (below gate)" : "Edge"}
              </div>
              <div className="flex items-baseline gap-2">
                <TabularNumber className={`text-5xl font-semibold tracking-tight ${s.accent}`}>
                  {play.edge_pct === null ? "—" : `${play.edge_pct >= 0 ? "+" : ""}${play.edge_pct.toFixed(1)}%`}
                </TabularNumber>
                {state === "WATCH" && (
                  <span className="text-[10px] text-semantic-observed">watch only</span>
                )}
              </div>
            </>
          )}
        </div>

        {/* Secondary metrics — subordinate */}
        <dl className="grid grid-cols-1 gap-1.5 text-[10px] text-right">
          <div>
            <dt className="text-text-tertiary">Fair</dt>
            <dd><TabularNumber className="text-sm text-text-primary">{play.fair_line.toFixed(1)}</TabularNumber></dd>
          </div>
          <div>
            <dt className="text-text-tertiary">EV/u</dt>
            <dd><TabularNumber className="text-sm text-text-primary">
              {play.ev_per_unit === null ? "—" : `${play.ev_per_unit >= 0 ? "+" : ""}${play.ev_per_unit.toFixed(3)}`}
            </TabularNumber></dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Kelly</dt>
            <dd><TabularNumber className="text-sm text-text-primary">{play.kelly_fraction === null ? "—" : `${(play.kelly_fraction * 100).toFixed(1)}%`}</TabularNumber></dd>
          </div>
        </dl>
      </div>

      {/* Gate chips — secondary, but failing hard clauses are visually distinct */}
      <ul className="mt-3 flex flex-wrap gap-1" aria-label="Gate reasoning">
        {play.gate_reasoning.map((c) => (
          <GateChip key={c.clause_id} clause={c} />
        ))}
      </ul>

      <footer className="mt-3 flex items-center justify-between text-[10px] text-text-tertiary">
        <span>Quote age {play.quote_age_seconds === null ? "unknown" : `${play.quote_age_seconds}s`} · {play.source_id}</span>
        {locked && <span className={s.accent}>Action locked</span>}
      </footer>
    </section>
  );
}

function GateChip({ clause }: { clause: GateClause }) {
  const isHardFail = clause.severity === "hard" && !clause.passed;
  const isSoftFail = clause.severity === "soft" && !clause.passed;
  const cls = isHardFail
    ? "border-semantic-stale bg-semantic-stale/15 text-semantic-stale font-medium"
    : isSoftFail
      ? "border-semantic-observed/40 text-semantic-observed"
      : "border-semantic-verified/30 text-semantic-verified";
  return (
    <li
      className={`rounded border px-1.5 py-0.5 text-[10px] ${cls}`}
      title={`${clause.label}: ${clause.actual} ${clause.operator} ${clause.threshold} (${clause.severity})`}
    >
      {clause.passed ? "✓" : isHardFail ? "✕" : "!"} {clause.label}
    </li>
  );
}
