/**
 * PropStein — assessment service.
 *
 * The pipeline that runs AFTER the user explicitly confirms an extraction:
 *   provenance assembly -> comparison lookup (entitlement-gated) ->
 *   model coverage lookup -> Hurdle Router -> persisted Assessment.
 *
 * Fail-closed scenarios can be injected for demonstration and testing
 * (scenario parameter). In production these occur naturally.
 */

import { db } from '@/lib/db';
import { comparisonQuote } from '@/lib/domain/sim-market';
import { assessModelCoverage, isModelOutage, setModelOutage } from '@/lib/domain/model-registry';
import { runHurdleRouter } from '@/lib/domain/hurdle';
import { breakEvenProbability, impliedProbability } from '@/lib/domain/odds';
import { canonicalJson, isoUtc, snapshotHash } from '@/lib/domain/determinism';
import type { ComparisonQuote, HurdleInput, HurdleResult, ModelAssessment, ProvenanceRecord } from '@/lib/domain/types';

export type DemoScenario =
  | 'none'
  | 'no_market_data'
  | 'entitlement_failure'
  | 'stale_quote'
  | 'unverified_context'
  | 'model_outage'
  | 'conflicting_close';

export interface ConfirmedSlip {
  sport: string;
  league: string;
  eventId: string;
  eventLabel: string;
  eventStartsAtUtc: string;
  playerId: string;
  playerName: string;
  market: string;
  marketLabel: string;
  selection: 'over' | 'under';
  line: number;
  enteredAmericanOdds: number;
  /** Counterpart (other side) quote at the user's book, for de-vig at entry. */
  enteredCounterpartOdds: number;
  book: string;
  capturedAtUtc: string;
  wagerAmount?: number | null;
}

export interface AssessmentBundle {
  assessmentId: string;
  slipUploadId?: string | null;
  createdAtUtc: string;
  hurdle: HurdleResult;
  model: ModelAssessment;
  provenance: ProvenanceRecord;
  comparison: ComparisonQuote | null;
  slip: ConfirmedSlip;
  scenario: DemoScenario;
}

const CONTEXT_SOURCES: Record<string, { sourceId: string; label: string }> = {
  spread: { sourceId: 'CTX-ODDS-1 (simulated)', label: 'Game spread' },
  total: { sourceId: 'CTX-ODDS-1 (simulated)', label: 'Game total' },
  weather: { sourceId: 'CTX-WX-1 (simulated)', label: 'Weather (kickoff forecast)' },
  injury_status: { sourceId: 'CTX-INJ-1 (simulated)', label: 'Injury / status report' },
  player_form: { sourceId: 'CTX-FORM-1 (simulated)', label: 'Player form (recent usage)' },
  opponent_coverage: { sourceId: 'CTX-COV-1 (simulated)', label: 'Opponent coverage profile' },
  market_quote: { sourceId: 'BOOK-USER', label: 'Market quote (user-entered book)' },
};

function buildProvenance(slip: ConfirmedSlip, scenario: DemoScenario, nowUtc: string): ProvenanceRecord {
  const captured = Date.parse(slip.capturedAtUtc);
  const minutes = (m: number) => new Date(captured - m * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const outdoor = ['NFL'].includes(slip.sport);
  const inputs = [
    { key: 'spread', value: 'TB +2.5' , observedAtUtc: minutes(9) },
    { key: 'total', value: '47.5', observedAtUtc: minutes(9) },
    { key: 'weather', value: outdoor ? 'Clear, wind 7 mph' : 'n/a (indoor)', observedAtUtc: outdoor ? minutes(31) : null },
    { key: 'injury_status', value: 'Questionable (limited practice)', observedAtUtc: minutes(1400) },
    { key: 'player_form', value: 'Recent 3-game usage within season baseline', observedAtUtc: minutes(1500) },
    { key: 'opponent_coverage', value: 'Zone-heavy, 62% snap rate vs slot', observedAtUtc: minutes(1500) },
    { key: 'market_quote', value: `${slip.selection === 'over' ? 'Over' : 'Under'} ${slip.line} at ${slip.enteredAmericanOdds}`, observedAtUtc: slip.capturedAtUtc },
  ];
  if (scenario === 'unverified_context') {
    const idx = inputs.findIndex((i) => i.key === 'weather');
    if (idx >= 0) inputs[idx] = { ...inputs[idx], observedAtUtc: null };
  }
  const record: ProvenanceRecord = {
    inputs: inputs.map((i) => ({
      key: i.key,
      label: CONTEXT_SOURCES[i.key]?.label ?? i.key,
      sourceId: CONTEXT_SOURCES[i.key]?.sourceId ?? 'CTX-1',
      observedAtUtc: i.observedAtUtc,
      value: i.value,
      rawCaptureRef: null,
    })),
    // Pricing cutoff: the context must be known before the user captured the price.
    pricingCutoffUtc: slip.capturedAtUtc,
    snapshotHash: '',
  };
  record.snapshotHash = snapshotHash(record);
  return record;
}

export async function runAssessment(
  userId: string,
  slip: ConfirmedSlip,
  scenario: DemoScenario = 'none',
  entitlementOk = true,
  mode: 'market' | 'model' = 'market',
): Promise<AssessmentBundle> {
  const nowUtc = isoUtc();
  const provenance = buildProvenance(slip, scenario, nowUtc);
  const eventKey = `${slip.sport}:${slip.eventId}:${slip.playerId}:${slip.market}:${slip.line}`;

  // Entitlement + scenario gate the comparison surface (fail closed).
  const entitled = entitlementOk && scenario !== 'entitlement_failure';
  let comparison: ComparisonQuote | null = null;
  if (entitled) {
    const capturedComparisonAt =
      scenario === 'stale_quote'
        ? new Date(Date.now() - 6.5 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')
        : nowUtc;
    comparison = comparisonQuote({
      sport: slip.sport,
      league: slip.league,
      eventId: slip.eventId,
      playerId: slip.playerId,
      market: slip.market,
      line: slip.line,
      enteredAmericanOdds: slip.enteredAmericanOdds,
      capturedAtUtc: capturedComparisonAt,
      scenario: scenario === 'no_market_data' ? 'no_market_data' : 'none',
    });
  }

  // Scenario-controlled model surface outage (fail-closed demonstration).
  const outageInjected = scenario === 'model_outage';
  if (outageInjected) setModelOutage(slip.market, true);
  const model = assessModelCoverage(slip.sport, slip.market, slip.selection, slip.line, eventKey);
  if (outageInjected) setModelOutage(slip.market, false);

  // Model-outage scenario forces the model surface path so the router fails
  // closed to MODEL UNAVAILABLE regardless of the requested mode.
  const effectiveMode: 'market' | 'model' = scenario === 'model_outage' ? 'model' : mode;

  const hurdleInput: HurdleInput = {
    sport: slip.sport,
    league: slip.league,
    market: slip.market,
    selection: slip.selection,
    line: slip.line,
    enteredAmericanOdds: slip.enteredAmericanOdds,
    comparison,
    comparisonUnavailableReason: !entitled
      ? 'entitlement_failure'
      : comparison === null
        ? 'no_license'
        : null,
    provenance,
    model,
    mode: effectiveMode,
    nowUtc,
    settled: null,
  };
  const hurdle = runHurdleRouter(hurdleInput);

  const resultPayload = {
    hurdle,
    model,
    provenance,
    comparison,
    slip: {
      ...slip,
      enteredImpliedProbability: Number(impliedProbability(slip.enteredAmericanOdds).toFixed(4)),
      breakEvenProbability: Number(breakEvenProbability(slip.enteredAmericanOdds).toFixed(4)),
    },
    scenario,
    computedAtUtc: nowUtc,
  };

  const row = await db.assessment.create({
    data: {
      userId,
      inputJson: canonicalJson(hurdleInput),
      snapshotHash: snapshotHash(resultPayload),
      resultJson: JSON.stringify(resultPayload),
      scenario,
    },
  });

  return {
    assessmentId: row.id,
    createdAtUtc: nowUtc,
    hurdle,
    model,
    provenance,
    comparison,
    slip,
    scenario,
  };
}

export async function loadAssessment(assessmentId: string): Promise<AssessmentBundle | null> {
  const row = await db.assessment.findUnique({ where: { id: assessmentId } });
  if (!row) return null;
  const parsed = JSON.parse(row.resultJson) as {
    hurdle: HurdleResult;
    model: ModelAssessment;
    provenance: ProvenanceRecord;
    comparison: ComparisonQuote | null;
    slip: ConfirmedSlip;
  };
  return {
    assessmentId: row.id,
    slipUploadId: row.slipUploadId,
    createdAtUtc: row.createdAtUtc.toISOString(),
    hurdle: parsed.hurdle,
    model: parsed.model,
    provenance: parsed.provenance,
    comparison: parsed.comparison,
    slip: parsed.slip,
    scenario: row.scenario as DemoScenario,
  };
}

/** Current model outage state (for the fail-closed demo controls). */
export function modelOutageActive(): boolean {
  return isModelOutage('player_reception_yds');
}
