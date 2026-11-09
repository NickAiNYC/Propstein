/**
 * PropStein — Hurdle Router (module 2).
 *
 * Model-free where it must be, fail-closed where it has to be.
 *
 * The router computes a categorical PRICE ASSESSMENT from one of exactly nine
 * allowed values. It never emits a pick, never labels a market difference as
 * an advantage claim, and never proceeds on stale or unverified context.
 *
 * Deterministic evaluation order (preregistered):
 *   1. SETTLED            — a settlement exists; the card shows the recorded outcome.
 *   2. UNVERIFIED CONTEXT — required provenance inputs lack observed-at
 *                           timestamps at-or-before the pricing cutoff.
 *   3. STALE QUOTE        — comparison exists but its snapshot age exceeds threshold.
 *   4. MODEL UNAVAILABLE  — model mode requested; registry coverage exists but the
 *                           model surface is down / revoked (fail closed).
 *   5. NO MODEL COVERAGE  — model mode requested; no calibrated coverage for market.
 *   6. INSUFFICIENT MARKET DATA — market mode; no licensed comparison available.
 *   7. MARKET HURDLE BAND — market mode with a fresh licensed comparison:
 *                           delta bands around zero (preregistered ±0.25 pp).
 */

import {
  breakEvenProbability,
  impliedProbability,
  priceDeltaPp,
} from './odds';
import { freshnessState } from './freshness';
import { REQUIRED_CONTEXT_INPUTS } from './types';
import type { HurdleInput, HurdleResult, ProvenanceRecord } from './types';

/**
 * Half-width of the "AT MARKET HURDLE" band, in percentage points of implied
 * probability. A display constant: purely descriptive price comparison.
 */
export const HURDLE_BAND_PP = 0.25;

export interface ProvenanceCheck {
  ok: boolean;
  missing: string[];
  late: string[];
}

/**
 * Hard rule: spread, total, and (outdoor sports) weather must each carry an
 * observed-at timestamp at-or-before the pricing cutoff. Otherwise the
 * assessment fails closed to UNVERIFIED CONTEXT.
 */
export function checkProvenance(provenance: ProvenanceRecord, sport: string): ProvenanceCheck {
  const missing: string[] = [];
  const late: string[] = [];
  const cutoff = Date.parse(provenance.pricingCutoffUtc);
  for (const [key, applies] of Object.entries(REQUIRED_CONTEXT_INPUTS)) {
    if (!applies(sport)) continue;
    const input = provenance.inputs.find((i) => i.key === key);
    if (!input || input.observedAtUtc === null) {
      missing.push(key);
      continue;
    }
    const observed = Date.parse(input.observedAtUtc);
    if (!Number.isFinite(observed) || !Number.isFinite(cutoff) || observed > cutoff) {
      late.push(key);
    }
  }
  return { ok: missing.length === 0 && late.length === 0, missing, late };
}

/** Run the Hurdle Router. Pure: same inputs -> same categorical output. */
export function runHurdleRouter(input: HurdleInput): HurdleResult {
  const breakEven = breakEvenProbability(input.enteredAmericanOdds);

  const base = {
    breakEvenProbability: breakEven,
    comparisonImpliedProbability: null as number | null,
    priceDeltaPp: null as number | null,
    deltaVerdict: null as 'better' | 'worse' | 'at' | null,
    freshness: null as HurdleResult['freshness'],
    marketComparisonAvailable: false,
    modelAssessmentAvailable: false,
  };

  // 1. SETTLED override -------------------------------------------------------
  if (input.settled && input.settled.status !== 'pending') {
    return {
      ...base,
      assessment: 'SETTLED',
      reasonCode: 'SETTLED_OVERRIDE',
      detail:
        `Settlement recorded with status ${input.settled.status}` +
        (input.settled.result ? ` and result ${input.settled.result}.` : '.'),
    };
  }

  // 2. UNVERIFIED CONTEXT (fail closed) ---------------------------------------
  const prov = checkProvenance(input.provenance, input.sport);
  if (!prov.ok) {
    const parts = [
      prov.missing.length ? `missing observed-at for: ${prov.missing.join(', ')}` : '',
      prov.late.length ? `observed after pricing cutoff: ${prov.late.join(', ')}` : '',
    ].filter(Boolean);
    return {
      ...base,
      assessment: 'UNVERIFIED CONTEXT',
      reasonCode: 'PROVENANCE_INCOMPLETE',
      detail: `Context inputs are not verified as known before the pricing cutoff (${parts.join('; ')}). The assessment fails closed.`,
    };
  }

  // 3. STALE QUOTE -------------------------------------------------------------
  if (input.comparison) {
    const fresh = freshnessState(input.comparison.capturedAtUtc, input.nowUtc);
    if (fresh.state !== 'fresh') {
      return {
        ...base,
        freshness: fresh,
        assessment: 'STALE QUOTE',
        reasonCode: 'COMPARISON_STALE',
        detail:
          fresh.state === 'unknown'
            ? 'Comparison snapshot timestamp is missing or unparsable. The assessment fails closed.'
            : `Comparison snapshot is ${fresh.ageSeconds} seconds old (threshold ${fresh.thresholdSeconds} seconds). The comparison is retained but not used.`,
      };
    }
  }

  // 4/5. Model mode ------------------------------------------------------------
  if (input.mode === 'model') {
    if (input.model.coverage === 'unavailable') {
      return {
        ...base,
        assessment: 'MODEL UNAVAILABLE',
        reasonCode: 'MODEL_SERVICE_UNAVAILABLE',
        detail: 'The model registry lists this market, but the model surface is unavailable. The assessment fails closed.',
      };
    }
    if (input.model.coverage !== 'calibrated') {
      return {
        ...base,
        assessment: 'NO MODEL COVERAGE',
        reasonCode: 'NO_CALIBRATED_MODEL',
        detail: 'No calibrated model coverage exists for this market. This is not an instruction to take or decline the price.',
      };
    }
  }

  // 6. INSUFFICIENT MARKET DATA -------------------------------------------------
  if (!input.comparison || !input.comparison.licensed) {
    const reason =
      input.comparisonUnavailableReason === 'entitlement_failure'
        ? 'Server-side entitlement verification did not grant market comparison for this sport.'
        : input.comparisonUnavailableReason === 'no_license'
          ? 'No licensed comparison feed is available for this sport and market.'
          : 'No comparison quote was available at assessment time.';
    return {
      ...base,
      assessment: 'INSUFFICIENT MARKET DATA',
      reasonCode: 'COMPARISON_UNAVAILABLE',
      detail: `${reason} Break-even probability is still shown because it derives from the entered price alone. This is not an instruction to take or decline the price.`,
    };
  }

  // 7. MARKET HURDLE BAND --------------------------------------------------------
  const comparisonOdds =
    input.selection === 'over' ? input.comparison.overAmericanOdds : input.comparison.underAmericanOdds;
  const comparisonImplied = impliedProbability(comparisonOdds);
  const delta = priceDeltaPp(input.enteredAmericanOdds, comparisonOdds);
  const fresh = freshnessState(input.comparison.capturedAtUtc, input.nowUtc);
  const marketAssessmentAvailable = input.model.coverage === 'calibrated';

  let assessment: HurdleResult['assessment'];
  let deltaVerdict: 'better' | 'worse' | 'at';
  if (delta < -HURDLE_BAND_PP) {
    assessment = 'PRICE ABOVE MARKET HURDLE';
    deltaVerdict = 'better';
  } else if (delta > HURDLE_BAND_PP) {
    assessment = 'PRICE BELOW MARKET HURDLE';
    deltaVerdict = 'worse';
  } else {
    assessment = 'PRICE AT MARKET HURDLE';
    deltaVerdict = 'at';
  }

  return {
    assessment,
    reasonCode: 'MARKET_HURDLE_BAND',
    detail:
      `Entered price is ${Math.abs(delta).toFixed(1)} percentage points ${deltaVerdict === 'at' ? 'from' : deltaVerdict === 'better' ? 'better than' : 'worse than'} the comparison snapshot. ` +
      'This is a market comparison, not a model assessment, and not a betting recommendation.',
    breakEvenProbability: breakEven,
    comparisonImpliedProbability: comparisonImplied,
    priceDeltaPp: delta,
    deltaVerdict,
    freshness: fresh,
    marketComparisonAvailable: true,
    modelAssessmentAvailable: marketAssessmentAvailable,
  };
}
