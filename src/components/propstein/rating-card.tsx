'use client';

/**
 * PropStein — Rating Card (deliverable 4).
 *
 * Every state of a price assessment, exactly as specified:
 *   - 9 categorical chips, never a pick.
 *   - Required fields: entered price, break-even probability, market
 *     comparison, price difference, snapshot time, data freshness, model
 *     coverage, uncertainty interval, model version, provenance summary.
 *   - Empty states (loading, unconfirmed) and error states (entitlement,
 *     kill switch, service failure) fail closed with explicit copy.
 *   - Accessibility: role=status, aria-live, labelled sections, full keyboard
 *     access, sr-only context line.
 */

import { AssessmentChip, MetaRow, Note, SectionLabel, fmtAmerican, fmtAge, fmtEt, fmtPct, fmtPp, marketLabel, selectionLabel } from './shared';
import type { ModelAssessment, ProvenanceRecord, HurdleResult, ComparisonQuote } from '@/lib/domain/types';
import { cn } from '@/lib/utils';

export interface RatingCardProps {
  slip: {
    playerName: string;
    market: string;
    selection: string;
    line: number;
    enteredAmericanOdds: number;
    book: string;
    capturedAtUtc: string;
    eventLabel?: string;
    sport: string;
  };
  hurdle: HurdleResult;
  model: ModelAssessment;
  provenance: ProvenanceRecord;
  comparison: ComparisonQuote | null;
  computedAtUtc?: string;
  state?: 'ready' | 'loading' | 'unconfirmed' | 'entitlement' | 'killswitch' | 'service';
  compact?: boolean;
}

export function RatingCard(props: RatingCardProps) {
  const { slip, hurdle, model, provenance, comparison, computedAtUtc } = props;

  if (props.state && props.state !== 'ready') {
    return <RatingCardUnavailable state={props.state} />;
  }

  const freshness = hurdle.freshness;
  const unavailableFamily = ['INSUFFICIENT MARKET DATA', 'STALE QUOTE', 'UNVERIFIED CONTEXT', 'NO MODEL COVERAGE', 'MODEL UNAVAILABLE'].includes(
    hurdle.assessment,
  );

  return (
    <article
      aria-labelledby="rc-title"
      className="pst-card rounded-md overflow-hidden"
    >
      <span className="sr-only" aria-live="polite">
        Price assessment {hurdle.assessment}. This is not a betting recommendation.
      </span>

      {/* Header */}
      <header className="px-4 pt-4 pb-3 border-b border-white/[0.07]/70 bg-white/60">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="pst-label">Recorded for review</div>
            <h3 id="rc-title" className="text-[15px] font-semibold text-zinc-100 leading-tight mt-0.5">
              {slip.playerName} — {marketLabel(slip.market)} {selectionLabel(slip.selection)} {slip.line}
            </h3>
            <div className="text-[12px] text-zinc-500 mt-0.5">
              {slip.sport} · {slip.eventLabel ?? slip.book} · book: {slip.book}
            </div>
          </div>
          <AssessmentChip assessment={hurdle.assessment} size="lg" />
        </div>
      </header>

      <div className={cn('grid gap-0', props.compact ? '' : 'md:grid-cols-2 divide-x divide-white/[0.07]/70')}>
        {/* Price & market comparison */}
        <section aria-label="Entered price and break-even probability" className="px-4 py-3">
          <SectionLabel>Entered price · Break-even probability</SectionLabel>
          <div className="mt-2 flex items-baseline gap-3">
            <span className="pst-num text-2xl font-semibold text-zinc-100">{fmtAmerican(slip.enteredAmericanOdds)}</span>
            <span className="pst-num text-lg text-zinc-300">{fmtPct(hurdle.breakEvenProbability)}</span>
          </div>
          <div className="mt-3 space-y-0">
            <MetaRow label="Market comparison" mono>
              {comparison && comparison.licensed
                ? `${selectionLabel(slip.selection)} ${slip.line} at ${fmtAmerican(slip.selection === 'over' ? comparison.overAmericanOdds : comparison.underAmericanOdds)} · ${comparison.provider}`
                : 'unavailable'}
            </MetaRow>
            <MetaRow label="Comparison implied probability" mono>
              {hurdle.comparisonImpliedProbability !== null ? fmtPct(hurdle.comparisonImpliedProbability) : '—'}
            </MetaRow>
            <MetaRow label="Price difference" mono>
              {hurdle.priceDeltaPp !== null ? (
                <span>
                  {hurdle.deltaVerdict === 'better'
                    ? `entered is ${Math.abs(hurdle.priceDeltaPp).toFixed(1)} pp better than comparison`
                    : hurdle.deltaVerdict === 'worse'
                      ? `entered is ${Math.abs(hurdle.priceDeltaPp).toFixed(1)} pp worse than comparison`
                      : `at comparison within ±0.25 pp (${fmtPp(hurdle.priceDeltaPp)})`}
                </span>
              ) : (
                '—'
              )}
            </MetaRow>
            <MetaRow label="Snapshot time" mono>
              {comparison ? fmtEt(comparison.capturedAtUtc) : fmtEt(slip.capturedAtUtc)}
            </MetaRow>
            <MetaRow label="Data freshness" mono>
              {freshness
                ? `${fmtAge(freshness.ageSeconds)} · ${freshness.state === 'fresh' ? 'fresh' : freshness.state === 'stale' ? 'stale' : 'unknown'} (threshold ${freshness.thresholdSeconds}s)`
                : 'unknown'}
            </MetaRow>
          </div>
          <div className="mt-3">
            <Note tone={unavailableFamily ? 'warn' : 'neutral'}>
              This is a market comparison, not a model assessment, and not a betting recommendation.
              {computedAtUtc ? ` Computed ${fmtEt(computedAtUtc)}.` : ''}
            </Note>
          </div>
        </section>

        {/* Model coverage */}
        <section aria-label="Model coverage and uncertainty interval" className="px-4 py-3">
          <SectionLabel>Model coverage</SectionLabel>
          <div className="mt-2 space-y-0">
            {model.coverage === 'calibrated' ? (
              <>
                <MetaRow label="Model" mono>{`${model.modelName} · ${model.modelVersion}`}</MetaRow>
                <MetaRow label="Model probability" mono>{fmtPct(model.probability)}</MetaRow>
                <MetaRow label="Uncertainty interval (95%)" mono>
                  {model.uncertainty ? `${fmtPct(model.uncertainty.lower)} – ${fmtPct(model.uncertainty.upper)}` : '—'}
                </MetaRow>
                <MetaRow label="Calibration status" mono>calibrated · corpus {model.corpusGames} games</MetaRow>
                <MetaRow label="Data freshness" mono>{fmtEt(model.dataFreshnessUtc)}</MetaRow>
              </>
            ) : model.coverage === 'uncalibrated' ? (
              <>
                <MetaRow label="Model" mono>{`${model.modelName} · ${model.modelVersion}`}</MetaRow>
                <MetaRow label="Calibration status" mono>uncalibrated — corpus below preregistered minimum</MetaRow>
              </>
            ) : model.coverage === 'unavailable' ? (
              <MetaRow label="Model surface" mono>unavailable — fail closed</MetaRow>
            ) : (
              <MetaRow label="Model surface" mono>none for this market</MetaRow>
            )}
          </div>
          <div className="mt-3">
            {model.coverage === 'calibrated' ? (
              <details className="text-[12px] text-zinc-500">
                <summary className="cursor-pointer select-none text-zinc-400">Known model limitations</summary>
                <ul className="list-disc pl-4 mt-1 space-y-0.5">
                  {model.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </details>
            ) : (
              <Note tone="warn">
                No calibrated coverage. This is not an instruction to take or decline the price. Insufficient evidence for a
                model statement here.
              </Note>
            )}
          </div>
        </section>
      </div>

      {/* Provenance strip */}
      <section aria-label="Provenance summary" className="px-4 py-3 border-t border-white/[0.07]/70 bg-[#0D0F16]/60">
        <SectionLabel>Provenance (context known before the pricing cutoff)</SectionLabel>
        <div className="mt-1.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-1">
          {provenance.inputs.map((input) => {
            const ok =
              input.observedAtUtc !== null && Date.parse(input.observedAtUtc) <= Date.parse(provenance.pricingCutoffUtc);
            const required = ['spread', 'total', 'weather'].includes(input.key) && ['NFL'].includes(slip.sport);
            return (
              <div key={input.key} className="flex items-baseline gap-1.5 text-[12px]">
                <span
                  aria-label={ok ? `${input.label} observed before cutoff` : `${input.label} not verified before cutoff`}
                  className={cn('shrink-0 font-mono text-[11px]', ok ? 'text-emerald-300' : required ? 'text-amber-300/80' : 'text-zinc-400')}
                >
                  {ok ? '●' : required ? '▲' : '○'}
                </span>
                <span className="text-zinc-400 truncate">
                  {input.label}
                  <span className="pst-num text-zinc-400 ml-1.5">{input.observedAtUtc ? fmtEt(input.observedAtUtc) : 'not observed'}</span>
                </span>
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <Note>
            Pricing cutoff {fmtEt(provenance.pricingCutoffUtc)} · snapshot hash{' '}
            <span className="pst-num">{provenance.snapshotHash.slice(0, 12)}…</span>
          </Note>
          <Note>Fail closed when provenance, freshness, entitlement, or coverage is missing.</Note>
        </div>
      </section>

      {hurdle.detail && (
        <footer className="px-4 py-3 border-t border-white/[0.07]/70">
          <p className={cn('text-[12.5px] leading-relaxed', unavailableFamily ? 'text-amber-300/90' : 'text-zinc-400')}>
            {hurdle.detail}
          </p>
        </footer>
      )}
    </article>
  );
}

function RatingCardUnavailable({ state }: { state: 'loading' | 'unconfirmed' | 'entitlement' | 'killswitch' | 'service' }) {
  const copy: Record<string, { title: string; body: string }> = {
    loading: {
      title: 'Assessment computing…',
      body: 'The Hurdle Router is deriving the categorical price assessment from the confirmed fields.',
    },
    unconfirmed: {
      title: 'Unconfirmed extraction',
      body: 'Analysis is blocked until you confirm the extracted fields. Nothing is analyzed before your explicit confirmation.',
    },
    entitlement: {
      title: 'Server-side entitlement verification did not grant this data surface.',
      body: 'The comparison surface requires an active entitlement for this sport. The state is explicit, not silent.',
    },
    killswitch: {
      title: 'This surface is disabled by a kill switch.',
      body: 'The state is explicit, not silent. No data is filled in to replace the missing surface.',
    },
    service: {
      title: 'The assessment service is unavailable.',
      body: 'Nothing was invented to fill the gap. Re-run the assessment when the service returns.',
    },
  };
  const c = copy[state];
  return (
    <article aria-live="polite" className="pst-card rounded-md border-dashed p-6 text-center">
      <div className="pst-label">Price assessment</div>
      <div className="mt-1 text-sm font-semibold text-zinc-200">{c.title}</div>
      <p className="mt-1.5 text-[12.5px] text-zinc-500 max-w-md mx-auto leading-relaxed">{c.body}</p>
    </article>
  );
}
