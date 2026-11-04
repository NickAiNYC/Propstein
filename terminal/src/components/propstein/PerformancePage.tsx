"use client";

/* ============================================================
   PropStein — Performance & Track Record (Phase 5)
   Full-board honesty: published Week 7 audit decisions (N = 37),
   Week 1 holdout Brier skill defect (-12.51%), and preregistered
   commercial gate status (0 / 600 evaluable signals).
   Zero synthetic data. No fabricated observations.
   ============================================================ */

import { useMemo } from "react";
import { useApp } from "@/lib/propstein/router";
import { ARCHIVE_COHORT, REAL_AUDIT_DECISIONS, VERSION_TIMELINE } from "@/lib/propstein/archive";
import { GOVERNANCE } from "@/lib/propstein/types";
import { fmtPct, fmtSigned, fmtOdds } from "@/lib/propstein/format";
import { Panel, SectionHeading } from "./primitives";
import { cn } from "@/lib/utils";
import { ShieldAlert, AlertTriangle, CheckCircle2, GitCommitHorizontal } from "lucide-react";

export function PerformancePage() {
  const decisions = REAL_AUDIT_DECISIONS;
  const gateProgress = ARCHIVE_COHORT.evaluable / GOVERNANCE.confirmatoryThreshold;

  return (
    <div className="flex flex-col gap-6">
      {/* header */}
      <header>
        <p className="label-micro">Published Track Record &amp; Cryptographic Evidence</p>
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text">
          Performance &amp; audit
        </h1>
        <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-text-muted">
          PropStein publishes its complete calibration record as-is, without cherry-picking.
          The historical 37-decision cohort reflects the frozen Week 7 audit. The preregistered
          commercial gate requires N &ge; 600 independently evaluable qualifying signals per sport;
          prospective candidate forecasts remain in pre-kickoff collection and have zero closing
          matches admitted yet.
        </p>
      </header>

      {/* governance banner */}
      <Panel className="flex flex-col gap-3 border-caution/40 bg-caution/[0.04] p-4 lg:flex-row lg:items-center lg:justify-between lg:p-5">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-caution" aria-hidden />
          <div>
            <p className="text-sm font-medium text-text">Commercial tiers remain frozen (0 / 600 signals)</p>
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
              The preregistered commercial gate requires <strong className="text-text">{GOVERNANCE.confirmatoryThreshold}</strong> independently
              evaluable qualifying signals per sport with mean price CLV &ge; +1.0pp and game-clustered confidence strictly above zero at &alpha; = 0.0125.
              Current evaluable confirmatory count: <span className="font-data text-text">0 / {GOVERNANCE.confirmatoryThreshold}</span> (
              {fmtPct(gateProgress, 0)}). The N = {GOVERNANCE.screenedThreshold} checkpoint is descriptive only, not an unlock.
              Decision confidence bounds span zero [-10.1%, +145.0%].
            </p>
          </div>
        </div>
        <div className="w-full max-w-xs shrink-0 lg:w-56">
          <div
            className="h-1.5 w-full overflow-hidden rounded-[2px] bg-workspace"
            role="progressbar"
            aria-valuenow={ARCHIVE_COHORT.evaluable}
            aria-valuemin={0}
            aria-valuemax={GOVERNANCE.confirmatoryThreshold}
            aria-label={`Confirmatory cohort progress: ${ARCHIVE_COHORT.evaluable} of ${GOVERNANCE.confirmatoryThreshold} signals`}
          >
            <span
              className="block h-full rounded-[2px] bg-caution"
              style={{ width: `${Math.min(100, gateProgress * 100)}%` }}
            />
          </div>
          <p className="mt-1 text-right font-data text-[10px] text-text-muted">
            0 / {GOVERNANCE.confirmatoryThreshold} evaluable
          </p>
        </div>
      </Panel>

      {/* cohort summary */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-hairline bg-hairline md:grid-cols-5">
        {[
          { label: "Graded decisions (Week 7)", value: "37", hint: "Published audit cohort", span: false },
          { label: "Beat the close", value: "2 of 37 (5.4%)", hint: "95% CI: [1.5%, 17.7%]", span: false },
          { label: "Tied the close", value: "34 of 37 (91.9%)", hint: "Line unchanged in yds", span: false },
          { label: "Closed worse", value: "1 of 37 (2.7%)", hint: "-1.0 yd line drift", span: false },
          { label: "Holdout Brier skill", value: "-12.51%", hint: "0.2813 vs naive 0.2500", span: true },
        ].map((s) => (
          <div key={s.label} className={cn("bg-workspace px-3.5 py-3", s.span && "col-span-2 md:col-span-1")}>
            <p className="label-micro">{s.label}</p>
            <p className="mt-1.5 font-data text-xl leading-none text-text">{s.value}</p>
            <p className="mt-1 text-[10px] text-text-muted">{s.hint}</p>
          </div>
        ))}
      </div>

      {/* Brier skill defect & Model levers */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel className="p-4 lg:p-5">
          <SectionHeading
            title="Week 1 Holdout Brier Skill Defect"
            subtitle="Honest empirical evaluation — model trails naive baseline"
          />
          <div className="mt-4 space-y-3 text-xs text-text-muted">
            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span>Model Brier Score</span>
              <span className="font-data font-semibold text-text">0.2813</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span>Naive Baseline (0.50 everywhere)</span>
              <span className="font-data font-semibold text-text">0.2500</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span>Brier Skill Score</span>
              <span className="font-data font-semibold text-caution">-12.51%</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span>Decision Cutoff Enforced</span>
              <span className="font-data text-text">2026-10-28T04:20:36Z</span>
            </div>
          </div>
          <p className="mt-4 text-[11px] leading-relaxed text-text-muted">
            Because holdout Brier skill is negative and decision confidence intervals span zero,
            model outputs are anchored to the devigged market closing consensus as prior with
            shrinkage toward w &asymp; 0.25 to prevent overconfidence.
          </p>
        </Panel>

        <Panel className="p-4 lg:p-5">
          <SectionHeading
            title="Evidence Disciplines in Effect"
            subtitle="Structural gates preventing cherry-picking or premature commercialization"
          />
          <ul className="mt-4 space-y-3 text-xs leading-relaxed text-text-muted">
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-sapphire" />
              <span><strong>Separate Audit Cohorts:</strong> The 37 Week 7 decisions are published as historical evidence; user records and prospective candidate forecasts are tracked separately and never count toward commercial gates.</span>
            </li>
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-sapphire" />
              <span><strong>Fail-Closed Odds Quotes:</strong> Sportsbook prices without SHA-256 integrity receipts fail closed as unverified. Zero simulated quotes are displayed as verified.</span>
            </li>
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-sapphire" />
              <span><strong>Zero Dollar Advice:</strong> No recommended bet sizes, no Kelly stakes, and no guaranteed locks. Purely distributional research.</span>
            </li>
          </ul>
        </Panel>
      </div>

      {/* Week 7 Published Graded Decisions Table */}
      <Panel className="p-4 lg:p-5">
        <SectionHeading
          title="Week 7 Published Graded Decision Ledger (N = 37)"
          subtitle="Every graded decision from viewer/clv_report_2026_w7.json · 100% reproducible via `make verify`"
        />
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-hairline text-[10px] uppercase tracking-wider text-text-muted">
                <th className="pb-2">Player</th>
                <th className="pb-2">Market</th>
                <th className="pb-2">Side</th>
                <th className="pb-2 text-right">Trigger Line</th>
                <th className="pb-2 text-right">Trigger Odds</th>
                <th className="pb-2 text-right">Close Line</th>
                <th className="pb-2 text-right">Line Movement</th>
                <th className="pb-2 text-right">CLV EV</th>
                <th className="pb-2 text-center">Status</th>
                <th className="pb-2">Book</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline font-data text-[11px]">
              {decisions.map((row) => (
                <tr key={row.id} className="hover:bg-workspace/50">
                  <td className="py-2 font-medium text-text">{row.playerName}</td>
                  <td className="py-2 text-text-muted">{row.market}</td>
                  <td className="py-2">
                    <span className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                      row.side === "OVER" ? "bg-sapphire/10 text-sapphire" : "bg-caution/10 text-caution"
                    )}>
                      {row.side}
                    </span>
                  </td>
                  <td className="py-2 text-right text-text">{row.fairLine}</td>
                  <td className="py-2 text-right text-text-muted">{fmtOdds(row.triggerOdds)}</td>
                  <td className="py-2 text-right text-text">{row.closeLine}</td>
                  <td className="py-2 text-right">
                    <span className={cn(
                      row.lineMovement > 0 ? "text-emerald-400" : row.lineMovement < 0 ? "text-rose-400" : "text-text-muted"
                    )}>
                      {fmtSigned(row.lineMovement, 1)}
                    </span>
                  </td>
                  <td className="py-2 text-right text-text">{fmtSigned(row.clvEv * 100, 2)}%</td>
                  <td className="py-2 text-center">
                    <span className={cn(
                      "rounded px-1.5 py-0.5 text-[9px] font-bold uppercase",
                      row.status === "BEAT_CLOSE" ? "bg-emerald-500/20 text-emerald-400" :
                      row.status === "FADED" ? "bg-rose-500/20 text-rose-400" :
                      "bg-hairline text-text-muted"
                    )}>
                      {row.status === "PUSH" ? "TIED" : row.status}
                    </span>
                  </td>
                  <td className="py-2 text-text-muted">{row.book}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* model version timeline */}
      <Panel className="p-4 lg:p-5">
        <SectionHeading
          title="Model version history"
          subtitle="All structural changes committed before affected slates are evaluated"
        />
        <ol className="mt-4 flex flex-col gap-3">
          {VERSION_TIMELINE.map((v) => (
            <li key={v.version} className="flex items-start gap-3 rounded-[4px] border border-hairline bg-workspace p-3">
              <GitCommitHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-sapphire" aria-hidden />
              <div className="flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-data text-xs font-semibold text-text">
                    {v.version} · {v.since} ({v.deployedAt})
                  </span>
                  <span className="rounded bg-sapphire/10 px-1.5 py-0.5 text-[9px] font-bold text-sapphire uppercase">
                    Current active
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-text-muted">{v.note}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}
