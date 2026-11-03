import type { Metadata } from "next";
import Link from "next/link";

// Public performance record — the v1 track record, preserved verbatim.
// Continuity requirement from the 2026-11-03 review: archiving v1 keeps the
// files, but the record must stay reachable at the live site. This page
// carries the exact v1 /performance content (numbers unmodified) into 2.0.

export const metadata: Metadata = {
  title: "Propstein Track Record: Graded Decisions, CLV and Calibration",
  description:
    "Every graded Propstein decision published as-is: ledger record, full-board close calibration, holdout model evaluation including negative results, and the honest sample-size caveats.",
};

const LEDGER_ROWS: Array<{
  player: string;
  market: string;
  bet: string;
  odds: string;
  close: string;
  clv: string;
  outcome: "WIN" | "LOSS";
  net: string;
}> = [
  { player: "Amon-Ra St. Brown", market: "rec_yds", bet: "OVER 78.5", odds: "-115", close: "81.5 (-115)", clv: "3.0 yds / 4.97%", outcome: "WIN", net: "104.35" },
  { player: "Hunter Henry", market: "rec_yds", bet: "OVER 31.5", odds: "-115", close: "33.5 (-115)", clv: "2.0 yds / 3.32%", outcome: "WIN", net: "86.96" },
  { player: "DeMario Douglas", market: "rec_yds", bet: "OVER 34.5", odds: "-110", close: "36.5 (-115)", clv: "2.0 yds / 4.33%", outcome: "WIN", net: "90.91" },
  { player: "Jaxon Smith-Njigba", market: "rec_yds", bet: "OVER 100.5", odds: "170", close: "103.5 (160)", clv: "3.0 yds / 6.41%", outcome: "LOSS", net: "-80.0" },
  { player: "Chris Olave", market: "rec_yds", bet: "OVER 75.5", odds: "-115", close: "77.5 (-115)", clv: "2.0 yds / 3.32%", outcome: "WIN", net: "86.96" },
  { player: "A.J. Brown", market: "rec_yds", bet: "UNDER 69.5", odds: "-105", close: "67.5 (-115)", clv: "2.0 yds / 5.35%", outcome: "WIN", net: "95.24" },
  { player: "Colston Loveland", market: "rec_yds", bet: "OVER 44.5", odds: "-115", close: "46.5 (-115)", clv: "2.0 yds / 3.32%", outcome: "WIN", net: "86.96" },
  { player: "DK Metcalf", market: "rec_yds", bet: "UNDER 54.5", odds: "-115", close: "52.5 (-115)", clv: "2.0 yds / 3.32%", outcome: "WIN", net: "78.26" },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="glass space-y-3 rounded-lg p-5">
      <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.2em] text-zinc-300">{title}</h2>
      {children}
    </section>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-amber-900/40 bg-amber-950/20 p-3 font-mono text-[11px] leading-relaxed text-amber-200/90">
      {children}
    </p>
  );
}

export default function PerformancePage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="flex h-12 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/70 px-4 backdrop-blur">
        <Link href="/" className="flex items-center gap-2 font-mono text-sm font-bold tracking-tight text-zinc-100">
          <span className="flex h-7 w-7 items-center justify-center rounded-md border border-emerald-800/60 bg-emerald-950/40 font-mono text-sm font-bold text-emerald-400">
            P
          </span>
          propstein
        </Link>
        <Link
          href="/"
          className="rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1 font-mono text-[10px] text-zinc-300 transition-colors hover:border-zinc-600"
        >
          ← terminal
        </Link>
      </header>

      <main className="mx-auto max-w-3xl space-y-5 px-4 py-8 pb-16">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-zinc-600">track record · public</p>
          <h1 className="mt-1 font-mono text-2xl font-bold tracking-tight text-zinc-100">
            Propstein Track Record &amp; Evidence
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-zinc-400">
            Headline performance is full-board CLV — every decision graded against closing line value with
            confidence intervals, not a cherry-picked ledger subset. Everything graded so far is published as-is,
            including the small sample, the losing weeks and the model defects.
          </p>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-zinc-600">
            Preserved verbatim from the v1 record (frozen at tag v1.0.0). The 2.0 terminal continues to publish
            against the same ledger discipline — new graded weeks append to this page, they never replace it.
          </p>
        </div>

        <Section title="Full-board close calibration (Week 07)">
          <p className="text-sm leading-relaxed text-zinc-300">
            Headline metric: every graded board decision (N = <strong>37</strong>):
            <br />• <strong>2 of 37 beat the close</strong> (5.4%, 95% Wilson CI: [0.7%, 18.2%])
            <br />• <strong>34 of 37 tied the close</strong> (91.9%, line unchanged)
            <br />• <strong>1 of 37 closed worse</strong> (2.7%, -1.0 yd drift)
            <br />
            Average line delta: <strong>+0.05 yds</strong> (95% CI: [-0.23, +0.33] yds). Average CLV EV: 0.82%.
          </p>
          <Note>
            <strong>Headline honesty:</strong> Across the full board only 2 of 37 decisions beat the close that
            week. That is what an honest calibration record looks like early. We publish full-board calibration
            first so there is zero cherry-picking.
          </Note>
        </Section>

        <Section title="Graded ledger (preliminary sample, n = 8)">
          <p className="text-sm leading-relaxed text-zinc-300">
            <strong>7-1-0</strong> over <strong>8</strong> graded records — win rate 87.5% (95% Wilson CI:
            [52.9%, 97.8%]), beat-close rate 100.0%, average close beating value 4.29% of implied probability,
            net P&amp;L 549.64 on 790.0 staked (ROI 69.57%). Ledger root hash{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-emerald-400">
              178e29974bf8748c
            </code>
            .
          </p>
          <Note>
            <strong>Read this honestly:</strong> 8 records is a tiny sample. None of these rates are meaningful
            evidence of edge yet. We publish them below the full board so the methodology is auditable from day
            one, and so there is no incentive to quietly drop bad weeks.
          </Note>
          <div className="overflow-x-auto rounded-md border border-zinc-800">
            <table className="w-full min-w-[680px] font-mono text-[11px]">
              <thead className="bg-zinc-950/95 text-left text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-3 py-2 font-medium">player</th>
                  <th className="px-3 py-2 font-medium">market</th>
                  <th className="px-3 py-2 font-medium">bet</th>
                  <th className="px-3 py-2 text-right font-medium">odds</th>
                  <th className="px-3 py-2 font-medium">close</th>
                  <th className="px-3 py-2 font-medium">clv</th>
                  <th className="px-3 py-2 font-medium">outcome</th>
                  <th className="px-3 py-2 text-right font-medium">net</th>
                </tr>
              </thead>
              <tbody>
                {LEDGER_ROWS.map((r) => (
                  <tr key={r.player} className="border-t border-zinc-800/50 hover:bg-zinc-900/50">
                    <td className="px-3 py-1.5 text-zinc-200">{r.player}</td>
                    <td className="px-3 py-1.5 text-zinc-400">{r.market}</td>
                    <td className="px-3 py-1.5 text-zinc-300">{r.bet}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">{r.odds}</td>
                    <td className="px-3 py-1.5 text-zinc-400">{r.close}</td>
                    <td className="px-3 py-1.5 tabular-nums text-zinc-400">{r.clv}</td>
                    <td className="px-3 py-1.5">
                      <span
                        className={
                          r.outcome === "WIN"
                            ? "rounded-sm border border-emerald-800/60 bg-emerald-950/40 px-1.5 py-0.5 text-emerald-400"
                            : "rounded-sm border border-rose-800/60 bg-rose-950/40 px-1.5 py-0.5 text-rose-400"
                        }
                      >
                        {r.outcome}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">{r.net}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Published model evaluation (holdout)">
          <p className="text-sm leading-relaxed text-zinc-300">
            Decision cutoff enforced: <strong>yes</strong>; 862 snapshots evaluated, 0 future snapshots excluded
            to prevent leakage.
          </p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {[
              ["Brier score (model)", "0.2813"],
              ["Brier score (naive baseline)", "0.25"],
              ["Brier skill", "-12.51%"],
              ["Log loss (model)", "0.758"],
              ["Log loss (baseline)", "0.6931"],
            ].map(([k, v]) => (
              <div key={k} className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2.5">
                <dt className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">{k}</dt>
                <dd className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-zinc-200">{v}</dd>
              </div>
            ))}
          </dl>
          <Note>
            <strong>The model currently underperforms the naive baseline on this holdout.</strong> We publish
            that because it is true. Recalibration is an active workstream; roles and thresholds carry
            provisional labels everywhere in the product until the skill score turns positive.
          </Note>
        </Section>

        <Section title="Market-Model Edge Fit & Guarantee Status (Phase 2 & 3)">
          <p className="text-sm font-semibold leading-relaxed text-zinc-200">
            Model has no edge over market closing lines at this time. All projections should be treated as
            informational.
          </p>
          <p className="text-sm leading-relaxed text-zinc-300">
            Chronological regression fitting{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-emerald-400">
              p = w · p_model + (1 - w) · p_market
            </code>{" "}
            on active trigger decisions yields:
            <br />• <strong>ŵ = 0.6742</strong> (Standard Error: 0.3957, <strong>95% CI: [-0.1013, +1.4497]</strong>, N = 37)
            <br />
            Because the 95% confidence interval spans zero, there is no statistically significant evidence of
            closing line alpha over the market consensus.
          </p>
          <Note>
            <strong>Public actions in effect:</strong>
            <br />• <strong>Beat-Close Guarantee Suspended:</strong> Beating or tying a close on a small sample
            guarantees nothing about win rate or expected value. The marketing guarantee is publicly withdrawn.
            <br />• <strong>Paid Signups Frozen &amp; Quant Tier Waitlisted:</strong> Commercial paid upgrades
            remain suspended until N ≥ 300 graded board decisions achieve positive CLV bounded strictly above
            zero with 95% confidence.
            <br />• <strong>Uncensored Research Access:</strong> Projections and live pricing calculations are
            made available without paywalls in observer research mode.
          </Note>
        </Section>

        <Section title="What we publish as the sample grows">
          <p className="text-sm leading-relaxed text-zinc-300">
            Calibration by predicted-probability bucket; win rate with sample size; ROI with a confidence
            interval; maximum drawdown; splits by sport, market and model version; and losing weeks next to
            winning weeks, every week. The commitment is the record, not the highlight reel.
          </p>
        </Section>

        <Section title="Model limitations">
          <p className="text-sm leading-relaxed text-zinc-300">
            Propstein publishes model limitations alongside every page. Roles and thresholds are provisional
            pending chronological holdout validation. In our published week-1 holdout evaluation the model&apos;s
            Brier score trailed the naive baseline; we treat that as an open defect, not a marketing problem,
            and we publish recalibration results as they land. Snapshots are taken pre-kickoff; quotes age and
            lines move, so every number here carries a timestamp and a verification state. Route-participation
            and late-scratch information are not fully modeled. Nothing on this site is betting advice.
          </p>
        </Section>
      </main>

      <footer className="border-t border-zinc-800/80 bg-zinc-950/80 px-4 py-4 backdrop-blur">
        <div className="mx-auto max-w-3xl space-y-2">
          <p className="font-mono text-[10px] leading-relaxed text-zinc-600">
            Propstein is quantitative research, not betting advice. No wager should be placed based on any
            content on this site. 21+ where applicable. If gambling stops being fun, call 1-800-GAMBLER.
          </p>
          <nav className="flex flex-wrap gap-3 font-mono text-[10px] text-zinc-500">
            <Link href="/performance" className="text-zinc-400">
              Track Record
            </Link>
            <Link href="/" className="hover:text-zinc-300">
              Terminal
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
