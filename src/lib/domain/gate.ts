/**
 * PropStein — preregistered commercialization gate.
 *
 * Governing rule (verbatim from the specification):
 *   A commercial actionable-signal product may launch for a sport only after
 *   that sport's gate passes: N=600 evaluable qualifying signals, observed
 *   mean price CLV of at least +1.0 percentage point, and a game-clustered
 *   bootstrap lower bound above zero. Cross-sport pooling is forbidden.
 *
 * Preregistered constants (immutable in code; changing any of them is a
 * protocol change requiring re-registration):
 *   - confirmatory N      = 600 independently evaluable qualifying signals
 *   - interim look        = 300 (descriptive only, never a verdict)
 *   - effect threshold    = mean price CLV >= +1.0 pp
 *   - one-sided alpha     = 0.0125 per attempt
 *   - attempts            = at most two prospective attempts per sport
 *   - bootstrap           = game-clustered, 10,000 replicates, seed 20261024
 *   - cluster floor       = 30 distinct game clusters, else INCONCLUSIVE
 *   - default             = DENY commercial actionable-signal launch
 */

import {
  BOOTSTRAP_REPLICATES,
  GATE_ALPHA_ONE_SIDED,
  GATE_BOOTSTRAP_SEED,
  GATE_MEAN_CLV_MIN_PP,
  GATE_MIN_CLUSTERS,
  GATE_N_CONFIRM,
  GATE_N_INTERIM,
  clusterBootstrapMean,
  mean,
} from './stats';
import { applyCorrelationPolicy } from './grading';
import type { GateAttemptResult, GateSignal } from './types';

export const GATE_SPORTS = ['NFL', 'NBA', 'UFC'] as const;

export class CrossSportPoolingError extends Error {
  constructor() {
    super('CROSS_SPORT_POOLING_FORBIDDEN: evidence for one sport never authorizes claims about another.');
    this.name = 'CrossSportPoolingError';
  }
}

export class ProtocolError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'ProtocolError';
  }
}

/**
 * Prepare a sport's signal set: drop duplicates/correlated-with-reason,
 * require evaluability, and detect model-version stratification problems.
 *
 * Model-version rule: a confirmatory set must be accumulated under a single
 * model version for the model-covered portion. A version change mid-set
 * invalidates accumulation from the start of the newer version (the
 * confirmatory N restarts); the affected signals are retained with a note,
 * never silently dropped.
 */
export function prepareConfirmatorySet(
  sport: string,
  signals: GateSignal[],
): {
  qualifying: GateSignal[];
  excluded: { signalId: string; reason: string }[];
  modelVersionIssue: string | null;
} {
  if (signals.some((s) => s.sport !== sport)) {
    throw new CrossSportPoolingError();
  }

  const excluded: { signalId: string; reason: string }[] = [];

  // 1. Non-evaluable signals are retained with reason codes.
  for (const s of signals) {
    if (!s.evaluable) {
      excluded.push({ signalId: s.signalId, reason: s.reasonCode ?? 'UNSETTLED' });
    }
  }

  // 2. Duplicates (identical dedupe key) — first occurrence retained.
  const seenDedupe = new Set<string>();
  const deduped: GateSignal[] = [];
  for (const s of signals) {
    if (!s.evaluable) continue;
    const key = `${s.gameClusterId}|${s.signalId.split('#')[0]}`;
    // signalId convention: "<dedupeKey>#<seq>"; dedupe on the base key.
    const base = s.signalId.includes('#') ? s.signalId.split('#')[0] : s.signalId;
    const dedupeKey = `${s.sport}|${s.gameClusterId}|${base}`;
    if (seenDedupe.has(dedupeKey)) {
      excluded.push({ signalId: s.signalId, reason: 'DUPLICATE' });
      continue;
    }
    seenDedupe.add(dedupeKey);
    deduped.push(s);
  }

  // 3. Correlation policy: within a correlation group (same game cluster +
  //    player) only the earliest recorded signal remains qualifying; game
  //    cluster ids on retained rows are untouched, so cluster dependence is
  //    preserved for the bootstrap.
  const corrRows = deduped.map((s) => ({
    ledgerId: s.signalId,
    correlationGroup: correlationGroupOf(s),
    recordedAtUtc: s.recordedAtUtc,
  }));
  const decisions = applyCorrelationPolicy(corrRows);
  const qualifying: GateSignal[] = [];
  for (const s of deduped) {
    if (decisions.get(s.signalId) === 'correlated') {
      excluded.push({ signalId: s.signalId, reason: 'CORRELATED' });
    } else {
      qualifying.push(s);
    }
  }

  // 4. Model-version stratification.
  const versions = [...new Set(qualifying.map((s) => s.modelVersion).filter((v): v is string => v !== null))];
  let modelVersionIssue: string | null = null;
  if (versions.length > 1) {
    modelVersionIssue =
      `Confirmatory set spans model versions ${versions.join(', ')}; ` +
      'accumulation restarts at the version boundary and prior signals are marked PRE_REGISTRATION.';
    // Signals recorded before the newest version's first signal are excluded.
    const newest = versions[versions.length - 1];
    const firstNew = qualifying.find((s) => s.modelVersion === newest)?.recordedAtUtc;
    if (firstNew !== undefined) {
      const retained: GateSignal[] = [];
      for (const s of qualifying) {
        if (s.modelVersion === null || s.recordedAtUtc < firstNew) {
          if (s.modelVersion !== newest) {
            excluded.push({ signalId: s.signalId, reason: 'PRE_REGISTRATION' });
            continue;
          }
        }
        retained.push(s);
      }
      qualifying.length = 0;
      qualifying.push(...retained);
    }
  }

  return { qualifying, excluded, modelVersionIssue };
}

function correlationGroupOf(s: GateSignal): string | null {
  // Correlation group = same game cluster + same player, different record.
  if (!s.playerId) return null;
  return `corr:${s.gameClusterId}|${s.playerId}`;
}

/**
 * Evaluate one gate attempt for a sport. Deterministic given the signal set
 * and the preregistered seed.
 */
export function evaluateGateAttempt(
  sport: string,
  attemptNo: number,
  signals: GateSignal[],
  evaluatedAtUtc: string,
): GateAttemptResult {
  if (signals.some((s) => s.sport !== sport)) {
    throw new CrossSportPoolingError();
  }
  if (attemptNo < 1 || attemptNo > 2) {
    throw new ProtocolError(`ATTEMPT_LIMIT: at most two prospective attempts per sport (got ${attemptNo}).`);
  }

  const { qualifying, excluded, modelVersionIssue } = prepareConfirmatorySet(sport, signals);
  const notes: string[] = [];
  if (excluded.length > 0) {
    const hist = new Map<string, number>();
    for (const e of excluded) hist.set(e.reason, (hist.get(e.reason) ?? 0) + 1);
    notes.push(
      `Excluded ${excluded.length} signals with reason codes: ${[...hist.entries()].map(([k, v]) => `${k}×${v}`).join(', ')}.`,
    );
  }
  if (modelVersionIssue) notes.push(modelVersionIssue);

  const n = qualifying.length;
  const clusters = new Set(qualifying.map((s) => s.gameClusterId));
  const distinctClusters = clusters.size;
  const m = mean(qualifying.map((s) => s.clvPp)) as number;

  if (n < GATE_N_INTERIM) {
    return {
      sport,
      attemptNo,
      nEvaluable: n,
      distinctClusters,
      meanClvPp: Number(m.toFixed(3)),
      bootstrapLbPp: 0,
      verdict: 'IN_PROGRESS',
      seed: GATE_BOOTSTRAP_SEED,
      replicates: BOOTSTRAP_REPLICATES,
      modelVersions: [...new Set(qualifying.map((s) => s.modelVersion).filter(Boolean) as string[])],
      evaluatedAtUtc,
      notes: [...notes, `Accumulating: ${n}/${GATE_N_CONFIRM} evaluable qualifying signals.`],
    };
  }

  if (n < GATE_N_CONFIRM) {
    return {
      sport,
      attemptNo,
      nEvaluable: n,
      distinctClusters,
      meanClvPp: Number(m.toFixed(3)),
      bootstrapLbPp: 0,
      verdict: 'INTERIM',
      seed: GATE_BOOTSTRAP_SEED,
      replicates: BOOTSTRAP_REPLICATES,
      modelVersions: [...new Set(qualifying.map((s) => s.modelVersion).filter(Boolean) as string[])],
      evaluatedAtUtc,
      notes: [...notes, `Interim look at N=${n} is descriptive only and never a verdict.`],
    };
  }

  if (distinctClusters < GATE_MIN_CLUSTERS) {
    return {
      sport,
      attemptNo,
      nEvaluable: n,
      distinctClusters,
      meanClvPp: Number(m.toFixed(3)),
      bootstrapLbPp: 0,
      verdict: 'INCONCLUSIVE',
      seed: GATE_BOOTSTRAP_SEED,
      replicates: BOOTSTRAP_REPLICATES,
      modelVersions: [...new Set(qualifying.map((s) => s.modelVersion).filter(Boolean) as string[])],
      evaluatedAtUtc,
      notes: [
        ...notes,
        `Insufficient cluster representation: ${distinctClusters} distinct game clusters (< ${GATE_MIN_CLUSTERS}). Verdict is INCONCLUSIVE by protocol.`,
      ],
    };
  }

  const boot = clusterBootstrapMean(
    qualifying.map((s) => s.clvPp),
    qualifying.map((s) => s.gameClusterId),
    { replicates: BOOTSTRAP_REPLICATES, seed: GATE_BOOTSTRAP_SEED },
  );
  const lb = boot.lowerBoundOneSided0125;

  const passed = m >= GATE_MEAN_CLV_MIN_PP && lb > 0;
  return {
    sport,
    attemptNo,
    nEvaluable: n,
    distinctClusters,
    meanClvPp: Number(m.toFixed(3)),
    bootstrapLbPp: Number(lb.toFixed(3)),
    verdict: passed ? 'PASS' : 'FAIL',
    seed: GATE_BOOTSTRAP_SEED,
    replicates: BOOTSTRAP_REPLICATES,
    modelVersions: [...new Set(qualifying.map((s) => s.modelVersion).filter(Boolean) as string[])],
    evaluatedAtUtc,
    notes: [
      ...notes,
      `One-sided alpha ${GATE_ALPHA_ONE_SIDED}: bootstrap lower bound is the ${(GATE_ALPHA_ONE_SIDED * 100).toFixed(2)}th percentile of the cluster-bootstrap distribution of the mean.`,
      `Mean price CLV ${(m.toFixed(3))} pp vs threshold +${GATE_MEAN_CLV_MIN_PP.toFixed(1)} pp; lower bound ${lb.toFixed(3)} pp.`,
    ],
  };
}

/**
 * Retire logic: a failed second attempt permanently retires the sport's
 * commercial actionable-signal flag.
 */
export function sportCommercialState(
  sport: string,
  attempts: { attemptNo: number; verdict: string }[],
  compliance: { status: 'granted' | 'denied' | 'pending' } | null,
): {
  gatePassed: boolean;
  retired: boolean;
  commercialSignalEnabled: boolean;
  explanation: string;
} {
  const fails = attempts.filter((a) => a.verdict === 'FAIL').length;
  const passes = attempts.filter((a) => a.verdict === 'PASS').length;
  const retired = fails >= 2;
  const gatePassed = passes >= 1 && !retired;
  const commercialSignalEnabled = gatePassed && compliance?.status === 'granted';

  let explanation: string;
  if (retired) {
    explanation = `Both prospective attempts failed. The commercial actionable-signal flag for ${sport} is retired; no signal surface may launch for this sport.`;
  } else if (gatePassed && compliance?.status !== 'granted') {
    explanation = `Gate PASS recorded for ${sport}, but commercial launch additionally requires an explicit compliance approval record. Current status: ${compliance?.status ?? 'pending'}. Default is deny.`;
  } else if (gatePassed) {
    explanation = `Gate PASS and compliance approval recorded for ${sport}. Actionable-signal surfaces remain bounded to ${sport} only.`;
  } else {
    explanation = `No gate PASS recorded for ${sport}. Default is deny: no actionable-signal surface may launch.`;
  }

  return { gatePassed, retired, commercialSignalEnabled, explanation };
}
