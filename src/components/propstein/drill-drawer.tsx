'use client';

/**
 * PropStein — drill-down drawer (slide-over inspector).
 *
 * Clicking any board row or card opens this inspector: the underlying model
 * features and their contributions, the daily probability series, historical
 * self-scoring for the board key, the raw provenance observations, and the
 * quote snapshot. Every panel states coverage, version, freshness, and
 * provenance — no naked numbers anywhere (charter rule 5).
 */

import { cn } from '@/lib/utils';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { AssessmentChip, fmtAmerican, fmtEt, fmtPct, fmtPp, SectionLabel, marketLabel } from '@/components/propstein/shared';
import { Sparkline } from '@/components/propstein/sparkline';
import type { BoardPrediction } from '@/components/propstein/pipeline-board';

export function DrillDrawer({
  prediction,
  open,
  onOpenChange,
}: {
  prediction: BoardPrediction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!prediction) {
    return (
      <Sheet open={false} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-full sm:max-w-md" />
      </Sheet>
    );
  }

  const p = prediction;
  const model = p.model;
  const hasNumbers = model.coverage === 'calibrated' && model.probability !== null && model.uncertainty !== null;
  const bandWidth = model.uncertainty ? (model.uncertainty.upper - model.uncertainty.lower) * 100 : null;
  const contribs = [...(model.features ?? [])].sort((a, b) => Math.abs(b.contribution_pp) - Math.abs(a.contribution_pp));
  const maxContrib = contribs.length > 0 ? Math.max(...contribs.map((c) => Math.abs(c.contribution_pp))) || 1 : 1;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg bg-[#0D0F16] border-l border-white/[0.07] pst-scroll overflow-y-auto">
        <SheetHeader className="pb-3 border-b border-white/[0.07]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <SheetTitle className="text-[17px] font-semibold text-zinc-100 tracking-tight truncate">{p.player_name}</SheetTitle>
              <SheetDescription className="text-[12px] text-zinc-500 mt-0.5">
                {p.event_label} · {p.league}
              </SheetDescription>
            </div>
            <AssessmentChip assessment={p.price_assessment} size="sm" />
          </div>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mt-2 text-[13px]">
            <span className="text-zinc-200">
              {marketLabel(p.market)} <span className="text-zinc-500">Over</span>{' '}
              <span className="pst-num text-zinc-100">{p.line.toFixed(1)}</span>
            </span>
            <span className="pst-num text-zinc-400">
              {fmtAmerican(p.quote.over_american_odds)} / {fmtAmerican(p.quote.under_american_odds)}
            </span>
            <span className="text-zinc-500">{fmtEt(p.commences_at_utc)}</span>
          </div>
        </SheetHeader>

        <div className="py-4 space-y-5">
          {/* Assessment detail */}
          <section aria-label="Assessment detail">
            <SectionLabel className="mb-1.5">Assessment</SectionLabel>
            <p className="text-[12.5px] leading-relaxed text-zinc-300">{p.assessment_detail}</p>
            <p className="text-[11px] text-zinc-600 pst-num mt-1">reason code: {p.reason_code}</p>
          </section>

          {/* Model panel */}
          <section aria-label="Model assessment">
            <SectionLabel className="mb-1.5">Model assessment</SectionLabel>
            {hasNumbers ? (
              <div className="rounded-md border border-white/[0.07] bg-[#12141C] p-4 pst-sheen">
                <div className="flex items-baseline justify-between">
                  <span className="text-[12px] text-zinc-400">
                    {model.model_name}
                    <span className="pst-num text-zinc-500 ml-2">{model.model_version}</span>
                  </span>
                  <span className="pst-label">calibrated</span>
                </div>
                <div className="flex items-baseline gap-2 mt-2">
                  <span className="pst-num text-[30px] leading-none text-zinc-100">{(model.probability! * 100).toFixed(1)}%</span>
                  <span className="text-[11.5px] text-zinc-500">model P(over)</span>
                </div>
                {/* 95% uncertainty band as a range bar on the probability scale */}
                <div className="mt-3" aria-label="95 percent uncertainty interval">
                  <div className="relative h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                    <div
                      className="absolute top-0 bottom-0 rounded-full bg-indigo-500/70"
                      style={{
                        left: `${model.uncertainty!.lower * 100}%`,
                        width: `${(model.uncertainty!.upper - model.uncertainty!.lower) * 100}%`,
                      }}
                    />
                    <div
                      className="absolute top-[-2px] bottom-[-2px] w-[2px] bg-zinc-100"
                      style={{ left: `${model.probability! * 100}%` }}
                      aria-hidden="true"
                    />
                  </div>
                  <div className="flex justify-between text-[10.5px] text-zinc-500 pst-num mt-1">
                    <span>{(model.uncertainty!.lower * 100).toFixed(1)}%</span>
                    <span>95% interval · width {bandWidth?.toFixed(1)} pp</span>
                    <span>{(model.uncertainty!.upper * 100).toFixed(1)}%</span>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 mt-4 text-[11.5px]">
                  <div>
                    <div className="pst-label mb-0.5">corpus</div>
                    <div className="pst-num text-zinc-200">{model.corpus_games ?? '—'} games</div>
                  </div>
                  <div>
                    <div className="pst-label mb-0.5">data freshness</div>
                    <div className="pst-num text-zinc-200">{fmtEt(model.data_freshness_utc)}</div>
                  </div>
                  <div>
                    <div className="pst-label mb-0.5">model − market</div>
                    <div
                      className={cn(
                        'pst-num',
                        p.model_minus_market_pp !== null && p.model_minus_market_pp > 0
                          ? 'text-emerald-300'
                          : p.model_minus_market_pp !== null && p.model_minus_market_pp < 0
                            ? 'text-rose-300'
                            : 'text-zinc-300',
                      )}
                    >
                      {fmtPp(p.model_minus_market_pp)}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-amber-500/30 bg-amber-500/[0.06] p-4">
                <p className="text-[12.5px] text-amber-300/90 leading-relaxed">
                  {model.coverage === 'uncalibrated'
                    ? 'Coverage exists but calibration is pending, so no model probability is displayed for this market.'
                    : 'No model coverage exists for this sport and market. Market numbers below are shown without a model panel.'}
                </p>
                {model.model_version && (
                  <p className="text-[11px] text-zinc-500 pst-num mt-1.5">
                    listed: {model.model_name} · {model.model_version}
                  </p>
                )}
              </div>
            )}
            {model.limitations.length > 0 && (
              <ul className="mt-2 space-y-1" aria-label="Model limitations">
                {model.limitations.map((lim, i) => (
                  <li key={i} className="text-[11.5px] text-zinc-500 leading-relaxed flex gap-1.5">
                    <span aria-hidden="true" className="text-amber-400/70">▪</span>
                    {lim}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Raw factors */}
          {contribs.length > 0 && (
            <section aria-label="Model features and contributions">
              <SectionLabel className="mb-2">Raw factors driving today&apos;s probability</SectionLabel>
              <div className="space-y-2">
                {contribs.map((f) => {
                  const pos = f.contribution_pp >= 0;
                  const widthPct = (Math.abs(f.contribution_pp) / maxContrib) * 50;
                  return (
                    <div key={f.name} className="text-[11.5px]">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-zinc-300 truncate">{f.label}</span>
                        <span className="pst-num text-zinc-500 shrink-0">{f.value.toFixed(3)}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <div className="relative h-1 flex-1 rounded-full bg-white/[0.05]">
                          <div className="absolute left-1/2 top-[-2px] bottom-[-2px] w-px bg-white/15" aria-hidden="true" />
                          <div
                            className={cn('absolute top-0 bottom-0 rounded-full', pos ? 'bg-emerald-500/80' : 'bg-rose-500/80')}
                            style={pos ? { left: '50%', width: `${widthPct}%` } : { right: '50%', width: `${widthPct}%` }}
                          />
                        </div>
                        <span
                          className={cn('pst-num w-[64px] text-right shrink-0', pos ? 'text-emerald-300' : 'text-rose-300')}
                        >
                          {fmtPp(f.contribution_pp, 2)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="text-[10.5px] text-zinc-600 mt-2">
                Marginal probability contribution per factor (removed-factor method). Contributions approximate the
                additive feature model; the residual is the per-event seeded signal.
              </p>
            </section>
          )}

          {/* Series */}
          <section aria-label="Daily probability series">
            <div className="flex items-center justify-between mb-2">
              <SectionLabel>Daily series (last runs)</SectionLabel>
              {p.delta_pp_vs_prev !== null && <DeltaBadge deltaPp={p.delta_pp_vs_prev} />}
            </div>
            {p.series.length > 0 ? (
              <div className="rounded-md border border-white/[0.07] bg-[#12141C] p-3 pst-sheen">
                <Sparkline
                  points={[...p.series, { run_date: p.run_date, p: model.probability }]}
                  width={440}
                  height={54}
                  tone={p.delta_pp_vs_prev !== null && p.delta_pp_vs_prev >= 0 ? 'emerald' : 'rose'}
                  className="w-full"
                  ariaLabel={`Model probability across ${p.series.length + 1} daily runs`}
                />
                <div className="flex justify-between text-[10.5px] text-zinc-600 pst-num mt-1.5">
                  <span>{p.series[0].run_date}</span>
                  <span>
                    {p.series.length + 1} runs · {p.is_new_today ? 'new today' : 'carried over'}
                  </span>
                  <span>{p.run_date}</span>
                </div>
              </div>
            ) : (
              <p className="text-[12px] text-zinc-500">
                First appearance of this board key today — no prior runs to chart yet.
              </p>
            )}
          </section>

          {/* Historical accuracy */}
          <section aria-label="Historical accuracy for this board key">
            <SectionLabel className="mb-2">Historical accuracy (this board key)</SectionLabel>
            <div className="grid grid-cols-4 gap-2">
              <StatCell label="settled" value={p.history.n_settled.toString()} />
              <StatCell label="excluded" value={p.history.n_excluded.toString()} />
              <StatCell label="brier" value={p.history.brier !== null ? p.history.brier.toFixed(4) : '—'} />
              <StatCell
                label="hit rate"
                value={p.history.hit_rate !== null ? `${(p.history.hit_rate * 100).toFixed(1)}%` : '—'}
              />
            </div>
            <p className="text-[10.5px] text-zinc-600 mt-2">
              Graded against a settlement source independent of the model. Push, void, DNP, and canceled outcomes are
              excluded with reason codes — never counted as losses.
            </p>
          </section>

          {/* Provenance */}
          <section aria-label="Provenance observations">
            <div className="flex items-center justify-between mb-2">
              <SectionLabel>Provenance (context inputs)</SectionLabel>
              <span
                className={cn(
                  'text-[10.5px] pst-num',
                  p.provenance_complete ? 'text-emerald-300/80' : 'text-amber-300/80',
                )}
              >
                {p.provenance_complete ? 'complete' : 'incomplete'}
              </span>
            </div>
            {p.unverified_reason && (
              <div className="rounded-md border border-dashed border-amber-500/30 bg-amber-500/[0.06] p-2.5 mb-2">
                <p className="text-[11.5px] text-amber-300/90">
                  {p.unverified_reason}. Required context must be observed before the pricing cutoff; the assessment
                  fails closed.
                </p>
              </div>
            )}
            <div className="rounded-md border border-white/[0.07] divide-y divide-white/[0.05]">
              {p.provenance.map((obs) => (
                <div key={obs.key} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[11.5px]">
                  <div className="min-w-0">
                    <div className="text-zinc-300">{obs.label}</div>
                    <div className="text-zinc-600 pst-num text-[10.5px] truncate">{obs.source_id}</div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="pst-num text-zinc-400">{fmtEt(obs.observed_at_utc)}</div>
                    <div className="text-zinc-600 text-[10.5px]">{obs.value ?? 'not observed'}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Quote snapshot */}
          <section aria-label="Quote snapshot">
            <SectionLabel className="mb-2">Quote snapshot</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <StatCell label="over odds" value={fmtAmerican(p.quote.over_american_odds)} />
              <StatCell label="under odds" value={fmtAmerican(p.quote.under_american_odds)} />
              <StatCell label="break-even P" value={fmtPct(p.market_implied_probability, 2)} />
              <StatCell label="market fair P" value={fmtPct(p.market_fair_probability, 2)} />
              <StatCell label="captured" value={fmtEt(p.quote.captured_at_utc)} />
              <StatCell
                label="snapshot age"
                value={`${p.freshness.age_seconds ?? '—'} s / ${p.freshness.threshold_seconds} s`}
              />
            </div>
            <p className="text-[10.5px] text-zinc-600 mt-2">
              Provider: <span className="pst-num">{p.quote.provider}</span> · licensed:{' '}
              <span className="pst-num">{p.quote.licensed ? 'yes' : 'no'}</span> · freshness state:{' '}
              <span className="pst-num">{p.freshness.state}</span>
            </p>
          </section>

          <p className="text-[11px] text-zinc-600 leading-relaxed border-t border-white/[0.07] pt-3">
            This inspector reports prices, probabilities, uncertainty, provenance, and grading history. It is not a
            betting recommendation and contains no instruction to take or decline any price.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function DeltaBadge({ deltaPp, compact = false }: { deltaPp: number; compact?: boolean }) {
  const positive = deltaPp > 0;
  const flat = Math.abs(deltaPp) < 0.005;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 pst-num rounded-sm border px-1.5 py-0.5 text-[11px] font-medium',
        compact && 'text-[10.5px] px-1 py-0',
        flat
          ? 'border-white/10 bg-white/[0.04] text-zinc-400'
          : positive
            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
            : 'border-rose-500/30 bg-rose-500/10 text-rose-300',
      )}
      title="Day-over-day model probability movement (percentage points)"
    >
      <span aria-hidden="true">{flat ? '±' : positive ? '▲' : '▼'}</span>
      {`${deltaPp >= 0 ? '+' : ''}${deltaPp.toFixed(1)} pp`}
    </span>
  );
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/[0.07] bg-[#12141C] px-3 py-2 pst-sheen">
      <div className="pst-label mb-0.5">{label}</div>
      <div className="pst-num text-[13px] text-zinc-200">{value}</div>
    </div>
  );
}
