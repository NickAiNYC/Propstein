'use client';

/**
 * PropStein — Evidence DNA panel (module 5).
 *
 * Answers, per record: what information existed, when each input was
 * observed, which model version was used, what was uncertain, what was
 * missing, what would make the assessment unavailable, whether context was
 * known before the pricing cutoff, and whether the closing reference was
 * independent and fresh.
 *
 * Hard rule displayed on the panel: spread/total/weather lacking an
 * observed-at before the pricing cutoff => UNVERIFIED CONTEXT.
 */

import { MetaRow, Note, SectionLabel, fmtAmerican, fmtEt, fmtPct } from './shared';
import { devigTwoWay } from '@/lib/domain/odds';
import type { ModelAssessment, ProvenanceRecord, ComparisonQuote } from '@/lib/domain/types';
import { cn } from '@/lib/utils';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';

export interface EvidenceDnaProps {
  provenance: ProvenanceRecord;
  model: ModelAssessment;
  comparison: ComparisonQuote | null;
  slip: { enteredAmericanOdds: number; selection: string; line: number; book: string; capturedAtUtc: string; sport: string };
  record?: {
    ledgerId: string;
    createdAtUtc: string;
    revisionCount: number;
    settlementStatus: string;
    clvAvailable: boolean;
    closingQuality?: string | null;
  } | null;
}

export function EvidenceDna({ provenance, model, comparison, slip, record }: EvidenceDnaProps) {
  const cutoff = Date.parse(provenance.pricingCutoffUtc);
  const missing = provenance.inputs.filter((i) => i.observedAtUtc === null);
  const unverified = provenance.inputs.filter((i) => {
    if (i.observedAtUtc === null) return false;
    return Date.parse(i.observedAtUtc) > cutoff;
  });

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-zinc-100">Evidence DNA</h3>
        <span className="text-[11px] text-zinc-400">what existed · when · what was missing</span>
      </div>
      <p className="mt-1 text-[12px] text-amber-300/90">
        If spread, total, or weather lacks an observed-at timestamp before the pricing cutoff, the assessment becomes
        UNVERIFIED CONTEXT. The pipeline fails closed in that situation.
      </p>

      <Accordion type="multiple" defaultValue={['dna-inputs', 'dna-provenance', 'dna-model', 'dna-market', 'dna-record']} className="mt-2">
        {/* 1. Inputs */}
        <AccordionItem value="dna-inputs">
          <AccordionTrigger className="text-[13px] py-2.5">Inputs — what information existed</AccordionTrigger>
          <AccordionContent className="space-y-0">
            {provenance.inputs.map((i) => (
              <MetaRow key={i.key} label={i.label}>
                <span className="text-zinc-300">
                  {i.value ?? 'not recorded'}
                  {i.observedAtUtc ? '' : <span className="text-amber-300/80"> · not observed</span>}
                </span>
              </MetaRow>
            ))}
          </AccordionContent>
        </AccordionItem>

        {/* 2. Provenance */}
        <AccordionItem value="dna-provenance">
          <AccordionTrigger className="text-[13px] py-2.5">Provenance — when each input was observed</AccordionTrigger>
          <AccordionContent>
            <div className="space-y-0">
              {provenance.inputs.map((i) => {
                const known = i.observedAtUtc !== null && Date.parse(i.observedAtUtc) <= cutoff;
                return (
                  <MetaRow key={i.key} label={i.label} mono>
                    <span className={cn(known ? 'text-zinc-300' : 'text-amber-300/80')}>
                      {i.observedAtUtc ? fmtEt(i.observedAtUtc) : 'never'}
                      <span className="text-zinc-400"> · {i.sourceId}</span>
                    </span>
                  </MetaRow>
                );
              })}
              <MetaRow label="Pricing cutoff" mono>{fmtEt(provenance.pricingCutoffUtc)}</MetaRow>
              <MetaRow label="Snapshot hash" mono>
                <span className="text-zinc-500">{provenance.snapshotHash.slice(0, 24)}…</span>
              </MetaRow>
            </div>
            <div className="mt-2">
              {missing.length === 0 && unverified.length === 0 ? (
                <Note tone="teal">Context was known before the pricing cutoff for every input.</Note>
              ) : (
                <Note tone="warn">
                  {missing.length > 0 && `Never observed: ${missing.map((m) => m.label).join(', ')}. `}
                  {unverified.length > 0 && `Observed after the cutoff: ${unverified.map((m) => m.label).join(', ')}.`}
                </Note>
              )}
            </div>
          </AccordionContent>
        </AccordionItem>

        {/* 3. Model */}
        <AccordionItem value="dna-model">
          <AccordionTrigger className="text-[13px] py-2.5">Model — version, coverage, uncertainty</AccordionTrigger>
          <AccordionContent>
            <div className="space-y-0">
              <MetaRow label="Model name" mono>{model.modelName ?? 'none'}</MetaRow>
              <MetaRow label="Model version" mono>{model.modelVersion ?? 'none'}</MetaRow>
              <MetaRow label="Coverage status" mono>{model.coverage}</MetaRow>
              <MetaRow label="Calibration status" mono>{model.calibrationStatus}</MetaRow>
              {model.probability !== null && <MetaRow label="Probability" mono>{fmtPct(model.probability)}</MetaRow>}
              {model.uncertainty && (
                <MetaRow label="Uncertainty interval" mono>
                  {fmtPct(model.uncertainty.lower)} – {fmtPct(model.uncertainty.upper)}
                </MetaRow>
              )}
            </div>
            {model.limitations.length > 0 && (
              <div className="mt-2">
                <SectionLabel>Known limitations</SectionLabel>
                <ul className="list-disc pl-4 mt-1 space-y-0.5 text-[12px] text-zinc-400">
                  {model.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-2">
              <Note>
                What would make this assessment unavailable: missing or late provenance inputs, a stale comparison
                snapshot, a failed entitlement check, an outage of the model surface, or a missing closing reference at
                grade time.
              </Note>
            </div>
          </AccordionContent>
        </AccordionItem>

        {/* 4. Market */}
        <AccordionItem value="dna-market">
          <AccordionTrigger className="text-[13px] py-2.5">Market — entered vs comparison</AccordionTrigger>
          <AccordionContent>
            <div className="space-y-0">
              <MetaRow label="Entered price" mono>
                {fmtAmerican(slip.enteredAmericanOdds)} ({slip.book})
              </MetaRow>
              {comparison ? (
                <>
                  <MetaRow label="Comparison price" mono>
                    {fmtAmerican(slip.selection === 'over' ? comparison.overAmericanOdds : comparison.underAmericanOdds)} ·{' '}
                    {comparison.provider}
                  </MetaRow>
                  <MetaRow label="De-vigged consensus (two-way)" mono>
                    {fmtPct(devigTwoWay(comparison.overAmericanOdds, comparison.underAmericanOdds).over, 2)} over
                  </MetaRow>
                  <MetaRow label="Comparison snapshot" mono>{fmtEt(comparison.capturedAtUtc)}</MetaRow>
                  <MetaRow label="Staleness threshold" mono>300 seconds (preregistered)</MetaRow>
                </>
              ) : (
                <MetaRow label="Comparison price" mono>unavailable</MetaRow>
              )}
            </div>
          </AccordionContent>
        </AccordionItem>

        {/* 5. Record */}
        <AccordionItem value="dna-record">
          <AccordionTrigger className="text-[13px] py-2.5">Record — ledger linkage</AccordionTrigger>
          <AccordionContent>
            {record ? (
              <div className="space-y-0">
                <MetaRow label="Ledger id" mono>{record.ledgerId}</MetaRow>
                <MetaRow label="Created" mono>{fmtEt(record.createdAtUtc)}</MetaRow>
                <MetaRow label="Revisions" mono>{record.revisionCount}</MetaRow>
                <MetaRow label="Settlement status" mono>{record.settlementStatus}</MetaRow>
                <MetaRow label="CLV availability" mono>
                  {record.clvAvailable
                    ? 'available from de-vigged entry and close'
                    : record.closingQuality && record.closingQuality !== 'missing'
                      ? `grading pending — closing reference quality is ${record.closingQuality}`
                      : 'closing reference unavailable'}
                </MetaRow>
              </div>
            ) : (
              <Note>
                Not yet saved to the immutable ledger. Closing reference independence: the closing feed namespace is
                disjoint from the model input feed.
              </Note>
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
