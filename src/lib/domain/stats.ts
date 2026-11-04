/**
 * PropStein — statistics.
 *
 * Preregistered choices:
 *   - Bootstrap: game-clustered, resampling CLUSTERS with replacement,
 *     10,000 replicates, fixed seed per surface (gate seed 20261024).
 *   - Shrinkage: shrunk mean = N / (N + K) × mean, K = 100 (prior strength).
 *   - Luck Meter interval: two-sided 95% percentile interval.
 *   - Gate bound: one-sided lower bound at the 1 − 0.0125 level, i.e. the
 *     1.25th percentile of the bootstrap distribution of the mean.
 */

import { mulberry32, seedFrom } from './determinism';
import type { ClvOutcome, LuckMeterReport, ReasonCodeCount, RecordSlice } from './types';

export const SHRINKAGE_K = 100;
export const MIN_SAMPLE = 30;
export const BOOTSTRAP_REPLICATES = 10000;
export const GATE_BOOTSTRAP_SEED = 20261024;
export const GATE_ALPHA_ONE_SIDED = 0.0125;
export const GATE_MEAN_CLV_MIN_PP = 1.0;
export const GATE_N_CONFIRM = 600;
export const GATE_N_INTERIM = 300;
export const GATE_MIN_CLUSTERS = 30;

export function mean(xs: number[]): number | null {
  if (xs.length === 0) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function shrunkMean(xs: number[], k: number = SHRINKAGE_K): number | null {
  const m = mean(xs);
  if (m === null) return null;
  return (xs.length / (xs.length + k)) * m;
}

export function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) throw new RangeError('quantile of empty');
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/**
 * Game-clustered bootstrap of the mean. Clusters (games) are resampled with
 * replacement; the replicate mean is over all signals in the resampled
 * clusters, preserving within-cluster dependence.
 */
export function clusterBootstrapMean(
  values: number[],
  clusterIds: string[],
  opts: { replicates?: number; seed?: number } = {},
): { replicates: number[]; lowerBoundOneSided0125: number; ci95: { lower: number; upper: number } } {
  if (values.length !== clusterIds.length) throw new RangeError('values/cluster mismatch');
  if (values.length === 0) throw new RangeError('bootstrap of empty');
  const replicates = opts.replicates ?? BOOTSTRAP_REPLICATES;
  const seed = opts.seed ?? GATE_BOOTSTRAP_SEED;

  const clusters = new Map<string, number[]>();
  clusterIds.forEach((c, i) => {
    const list = clusters.get(c) ?? [];
    list.push(values[i]);
    clusters.set(c, list);
  });
  const clusterKeys = [...clusters.keys()];
  const clusterValues = clusterKeys.map((k) => clusters.get(k) as number[]);
  const totalN = values.length;

  const rand = mulberry32(seed);
  const reps: number[] = [];
  for (let r = 0; r < replicates; r++) {
    let sum = 0;
    for (let c = 0; c < clusterKeys.length; c++) {
      const idx = Math.floor(rand() * clusterKeys.length);
      const vals = clusterValues[idx];
      for (const v of vals) sum += v;
    }
    reps.push(sum / totalN);
  }
  const sorted = [...reps].sort((a, b) => a - b);
  return {
    replicates: reps,
    lowerBoundOneSided0125: quantile(sorted, GATE_ALPHA_ONE_SIDED),
    ci95: { lower: quantile(sorted, 0.025), upper: quantile(sorted, 0.975) },
  };
}

// ---------------------------------------------------------------------------
// Calibration
// ---------------------------------------------------------------------------

export interface CalibrationRow {
  bucket: string;
  n: number;
  predicted: number;
  observed: number;
}

export function calibrationTable(
  modelProbabilities: number[],
  outcomes: number[], // 1 = win, 0 = loss; excluded rows must be filtered by caller
): { brierScore: number; deciles: CalibrationRow[] } {
  if (modelProbabilities.length !== outcomes.length || modelProbabilities.length === 0) {
    return { brierScore: NaN, deciles: [] };
  }
  let brier = 0;
  for (let i = 0; i < modelProbabilities.length; i++) {
    brier += (modelProbabilities[i] - outcomes[i]) ** 2;
  }
  const rows: CalibrationRow[] = [];
  for (let d = 0; d < 10; d++) {
    const lo = d / 10;
    const hi = (d + 1) / 10;
    const idx: number[] = [];
    for (let i = 0; i < modelProbabilities.length; i++) {
      const p = modelProbabilities[i];
      if (p >= lo && (p < hi || (d === 9 && p <= hi))) idx.push(i);
    }
    if (idx.length === 0) continue;
    const pred = idx.reduce((a, i) => a + modelProbabilities[i], 0) / idx.length;
    const obs = idx.reduce((a, i) => a + outcomes[i], 0) / idx.length;
    rows.push({
      bucket: `${Math.round(lo * 100)}–${Math.round(hi * 100)}%`,
      n: idx.length,
      predicted: Number(pred.toFixed(4)),
      observed: Number(obs.toFixed(4)),
    });
  }
  return { brierScore: Number((brier / modelProbabilities.length).toFixed(4)), deciles: rows };
}

// ---------------------------------------------------------------------------
// Luck Meter report
// ---------------------------------------------------------------------------

const VERBATIM_DISPLAY_RULES: Record<LuckMeterReport['verdict'], string> = {
  'NO RECORD': 'No graded entries yet.',
  'INSUFFICIENT SAMPLE': 'Not enough evaluable entries to draw a conclusion.',
  'DESCRIPTIVE ONLY': 'This is descriptive. It does not establish an advantage over the market.',
  INCONCLUSIVE: 'The interval includes zero. Do not interpret this as an advantage over the market.',
  'POSITIVE BUT UNPROVEN': 'Positive descriptive CLV. The preregistered confirmation gate has not passed.',
  'GATE PASSED': 'Preregistered confirmation gate passed for this record set. Commercial actionable-signal surfaces additionally require recorded compliance approval.',
};

export interface LuckMeterInput {
  outcomes: ClvOutcome[];
  /** Recorded gate + compliance state for the record's dominant sport. */
  gatePassed?: boolean;
  complianceApproved?: boolean;
  seed?: number;
}

export function buildLuckMeterReport(input: LuckMeterInput): LuckMeterReport {
  const { outcomes } = input;
  const notes: string[] = [];

  const evaluable = outcomes.filter((o) => o.evaluable && o.clvPp !== null);
  const excluded = outcomes.filter((o) => !o.evaluable);
  const values = evaluable.map((o) => o.clvPp as number);
  const clusters = [...new Set(evaluable.map((o) => o.gameClusterId))];

  // Reason-code histogram — nothing silently dropped.
  const reasonCounts = new Map<string, number>();
  for (const o of excluded) {
    const key = o.reasonCode ?? 'UNSETTLED';
    reasonCounts.set(key, (reasonCounts.get(key) ?? 0) + 1);
  }
  const exclusions: ReasonCodeCount[] = [...reasonCounts.entries()]
    .map(([reason, count]) => ({ reason: reason as ReasonCodeCount['reason'], count }))
    .sort((a, b) => b.count - a.count);

  const meanClvPp = mean(values);
  const shrunk = shrunkMean(values);

  let ci: { lower: number; upper: number } | null = null;
  if (values.length >= 1 && clusters.length >= 1) {
    const boot = clusterBootstrapMean(
      values,
      evaluable.map((o) => o.gameClusterId),
      { seed: input.seed ?? seedFrom('LUCKMETER', evaluable.length) },
    );
    ci = {
      lower: Number(boot.ci95.lower.toFixed(3)),
      upper: Number(boot.ci95.upper.toFixed(3)),
    };
  }

  const beatClosePct =
    evaluable.length > 0 ? (evaluable.filter((o) => (o.clvPp as number) > 0).length / evaluable.length) * 100 : null;

  // Calibration over entries with calibrated model probabilities.
  const calRows = evaluable.filter((o) => o.modelCalibrated && o.modelProbability !== null && (o.result === 'win' || o.result === 'loss'));
  const calibration =
    calRows.length > 0
      ? (() => {
          const t = calibrationTable(
            calRows.map((o) => o.modelProbability as number),
            calRows.map((o) => (o.result === 'win' ? 1 : 0)),
          );
          return { nWithModelProbability: calRows.length, brierScore: t.brierScore, deciles: t.deciles };
        })()
      : { nWithModelProbability: 0, brierScore: null, deciles: [] };

  // Verdict ladder (preregistered).
  let verdict: LuckMeterReport['verdict'];
  if (evaluable.length === 0 && excluded.length === 0) {
    verdict = 'NO RECORD';
  } else if (evaluable.length < MIN_SAMPLE) {
    verdict = 'INSUFFICIENT SAMPLE';
    notes.push(`Fewer than ${MIN_SAMPLE} evaluable entries.`);
  } else if (input.gatePassed && input.complianceApproved) {
    verdict = 'GATE PASSED';
  } else if (ci && ci.lower <= 0 && ci.upper >= 0) {
    verdict = 'INCONCLUSIVE';
  } else if (ci && ci.lower > 0 && meanClvPp !== null && shrunk !== null && shrunk > 0) {
    verdict = 'POSITIVE BUT UNPROVEN';
    notes.push('The preregistered confirmation gate has not passed; this remains descriptive.');
  } else {
    verdict = 'DESCRIPTIVE ONLY';
  }
  if (verdict !== 'GATE PASSED') {
    notes.push('This record does not authorize any commercial actionable-signal claim.');
  }

  // Slices.
  const slices: RecordSlice[] = [];
  const sliceDims: { dimension: string; key: (o: ClvOutcome) => string }[] = [
    { dimension: 'Sport', key: (o) => o.sport },
    { dimension: 'Market', key: (o) => o.market },
    { dimension: 'Odds band', key: (o) => o.oddsBand },
    { dimension: 'Model version', key: (o) => o.modelVersion ?? 'no model' },
    { dimension: 'Entry source', key: (o) => o.entrySource },
  ];
  for (const dim of sliceDims) {
    const groups = new Map<string, ClvOutcome[]>();
    for (const o of evaluable) {
      const k = dim.key(o);
      const list = groups.get(k) ?? [];
      list.push(o);
      groups.set(k, list);
    }
    for (const [value, list] of [...groups.entries()].sort((a, b) => b[1].length - a[1].length)) {
      const vals = list.map((o) => o.clvPp as number);
      slices.push({
        dimension: dim.dimension,
        value,
        n: list.length,
        meanClvPp: mean(vals) !== null ? Number((mean(vals) as number).toFixed(3)) : null,
        shrunkClvPp: shrunkMean(vals) !== null ? Number((shrunkMean(vals) as number).toFixed(3)) : null,
        beatClosePct: list.length > 0 ? Number(((list.filter((o) => (o.clvPp as number) > 0).length / list.length) * 100).toFixed(1)) : null,
        belowMinSample: list.length < MIN_SAMPLE,
      });
    }
  }

  return {
    verdict,
    verdictDisplayRule: VERBATIM_DISPLAY_RULES[verdict],
    evaluableCount: evaluable.length,
    excludedCount: excluded.length,
    exclusions,
    meanClvPp: meanClvPp !== null ? Number(meanClvPp.toFixed(3)) : null,
    shrunkClvPp: shrunk !== null ? Number(shrunk.toFixed(3)) : null,
    confidenceIntervalPp: ci,
    bootstrapReplicates: BOOTSTRAP_REPLICATES,
    bootstrapSeed: input.seed ?? seedFrom('LUCKMETER', evaluable.length),
    beatClosePct: beatClosePct !== null ? Number(beatClosePct.toFixed(1)) : null,
    calibration: calibration.brierScore !== null && Number.isFinite(calibration.brierScore as number) ? (calibration as LuckMeterReport['calibration']) : { nWithModelProbability: calRows.length, brierScore: null, deciles: [] },
    slices,
    minSampleThreshold: MIN_SAMPLE,
    notes,
  };
}
