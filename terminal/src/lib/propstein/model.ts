/* ============================================================
   PropStein — market math
   American odds ⇄ probability, vig removal, value boundaries.

   Definitions (fail-closed, no fabrication):
   • breakEvenProb(odds): the win probability at which the
     price has zero expected value.
   • fairProb(over, under): vig-free normalized probability.
   • valueBoundaries: the set of lines L for which NEITHER
     side clears its break-even probability against the model.
     Over clears ⇔ P(X ≥ L) > p_be(over).  Because P(over) is
     strictly decreasing in L, the boundary is an interval
     [L_over, L_under] — the "no-value band".
   ============================================================ */

import { DistLaw, lawSurvival, lawCdf, lawQuantile } from "./distributions";

/* ---------- American odds ---------- */

/** Break-even win probability implied by American odds. */
export function breakEvenProb(american: number): number {
  if (american > 0) return 100 / (american + 100);
  if (american < 0) return -american / (-american + 100);
  return 0.5;
}

/** American odds from win probability (with sign). */
export function probToAmerican(p: number): number {
  if (p <= 0) return -10000;
  if (p >= 1) return 10000;
  if (p >= 0.5) return -Math.round((100 * p) / (1 - p));
  return Math.round((100 * (1 - p)) / p);
}

/** Vig-free normalized probability from a two-sided quote. */
export function fairProb(overOdds: number, underOdds: number): number {
  const po = breakEvenProb(overOdds);
  const pu = breakEvenProb(underOdds);
  const s = po + pu;
  if (s <= 0) return NaN;
  return po / s;
}

/** Total bookmaker hold (overround − 1) of a two-sided quote. */
export function quoteHold(overOdds: number, underOdds: number): number {
  return breakEvenProb(overOdds) + breakEvenProb(underOdds) - 1;
}

/* ---------- probability of clearing a line ---------- */

/** P(outcome ≥ line) — betting "over" wins ties pushed aside by .5 lines. */
export function overProb(line: number, law: DistLaw): number {
  return lawSurvival(line, law);
}

/** P(outcome ≤ line). */
export function underProb(line: number, law: DistLaw): number {
  const discrete = law.kind === "negbin";
  if (discrete) {
    // under a x.5 line means N ≤ floor(line); handle integer lines as push-free lower side
    return 1 - lawSurvival(line, law);
  }
  return lawCdf(line, law);
}

/* ---------- value boundaries ---------- */

export interface ValueBoundaries {
  /** lowest line at which neither side clears break-even (over side boundary) */
  lower: number;
  /** highest line in the no-value band (under side boundary) */
  upper: number;
  /** true when the captured line sits inside the band */
  lineInsideBand: boolean;
  /** model P(over) at the captured line minus over break-even, in probability points */
  edgeOver: number | null;
  /** break-even probability of the captured over price */
  breakEvenOver: number;
  /** break-even probability of the captured under price */
  breakEvenUnder: number;
}

/**
 * Solve the no-value band [L_over, L_under]:
 *   P(X ≥ L_over) = p_be(over)   (below this line the over has positive EV)
 *   P(X ≤ L_under) = p_be(under) (above this line the under has positive EV)
 */
export function computeValueBoundaries(
  law: DistLaw,
  overOdds: number,
  underOdds: number,
  capturedLine?: number
): ValueBoundaries {
  const beOver = breakEvenProb(overOdds);
  const beUnder = breakEvenProb(underOdds);

  // solve P(X ≥ L) = beOver  →  L = S^{-1}(beOver)
  const lower = lawQuantile(1 - beOver, law);
  // solve P(X ≤ L) = beUnder  →  L = F^{-1}(beUnder)
  const upper = lawQuantile(beUnder, law);

  let edgeOver: number | null = null;
  let lineInsideBand: boolean | null = null;
  if (capturedLine !== undefined && Number.isFinite(capturedLine)) {
    edgeOver = overProb(capturedLine, law) - beOver;
    lineInsideBand = capturedLine >= lower && capturedLine <= upper;
  }
  return {
    lower,
    upper,
    lineInsideBand: lineInsideBand ?? false,
    edgeOver,
    breakEvenOver: beOver,
    breakEvenUnder: beUnder,
  };
}

/* ---------- model ↔ market comparison ---------- */

export interface MarketComparison {
  /** model fair line (median) */
  fairLine: number;
  /** model projected volume (mean) */
  projectedVolume: number;
  /** captured market line, if any */
  marketLine: number | null;
  /** divergence in line units: fair − market (positive ⇒ model projects more) */
  lineDivergence: number | null;
  /** divergence standardized by model σ */
  standardizedDivergence: number | null;
  /** model P(over) at market line vs vig-free fair prob, in probability points */
  probDivergence: number | null;
}

export function compareMarket(
  law: DistLaw,
  fairLine: number,
  projectedVolume: number,
  sd: number,
  marketLine: number | null,
  overOdds?: number,
  underOdds?: number
): MarketComparison {
  const base: MarketComparison = {
    fairLine,
    projectedVolume,
    marketLine,
    lineDivergence: null,
    standardizedDivergence: null,
    probDivergence: null,
  };
  if (marketLine === null || !Number.isFinite(marketLine)) return base;
  const div = fairLine - marketLine;
  base.lineDivergence = div;
  base.standardizedDivergence = sd > 0 ? div / sd : null;
  if (overOdds !== undefined && underOdds !== undefined) {
    const pf = fairProb(overOdds, underOdds);
    if (Number.isFinite(pf)) {
      base.probDivergence = overProb(marketLine, law) - pf;
    }
  }
  return base;
}

/* ---------- CLV (closing line value) research metrics ---------- */

export interface ClvRecord {
  /** model fair line (median) at evaluation */
  fairLine: number;
  /** market closing line */
  closeLine: number;
  /** model σ at evaluation */
  sd: number;
}

/** Standardized CLV: (close − fair)/σ. Calibrated model ⇒ mean ≈ 0. */
export function standardizedClv(rec: ClvRecord): number {
  return rec.sd > 0 ? (rec.closeLine - rec.fairLine) / rec.sd : 0;
}

export interface ClvSummary {
  n: number;
  mean: number;
  /** 95% CI half-width on the mean */
  ci95: number;
  /** share of markets where the close moved toward the model median */
  beatCloseRate: number;
  sd: number;
}

export function summarizeClv(records: ClvRecord[]): ClvSummary {
  const n = records.length;
  if (n === 0) {
    return { n: 0, mean: NaN, ci95: NaN, beatCloseRate: NaN, sd: NaN };
  }
  const zs = records.map(standardizedClv);
  const mean = zs.reduce((a, b) => a + b, 0) / n;
  const varSample = zs.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, n - 1);
  const sd = Math.sqrt(varSample);
  const se = sd / Math.sqrt(n);
  const beat = zs.filter((z) => z < 0).length / n; // close below fair ⇒ market moved toward model over side
  return { n, mean, ci95: 1.96 * se, beatCloseRate: beat, sd };
}
