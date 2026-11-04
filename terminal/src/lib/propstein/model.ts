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

/* ---------- probability of clearing a line (with integer push handling) ---------- */

/** Checks whether a line is an integer line within numerical tolerance. */
export function isWholeNumberLine(line: number): boolean {
  return Math.abs(line - Math.round(line)) < 1e-4;
}

/** P(outcome > line), with Python-exact discrete and continuous integer push handling. */
export function overProb(line: number, law: DistLaw): number {
  const isWhole = isWholeNumberLine(line);
  if (law.kind === "negbin") {
    // Discrete receptions: on an integer line k, over strictly requires > k (wins on >= k + 1)
    if (isWhole) {
      const k = Math.round(line);
      return 1 - lawCdf(k, law);
    }
    return 1 - lawCdf(Math.floor(line), law);
  }
  // Continuous yards compound: integer line L pushes on (L - 0.5, L + 0.5]
  if (isWhole) {
    const L = Math.round(line);
    return Math.max(0, 1 - lawCdf(L + 0.5, law));
  }
  return lawSurvival(line, law);
}

/** P(outcome < line), with Python-exact discrete and continuous integer push handling. */
export function underProb(line: number, law: DistLaw): number {
  const isWhole = isWholeNumberLine(line);
  if (law.kind === "negbin") {
    // Discrete receptions: on an integer line k, under strictly requires < k (wins on <= k - 1)
    if (isWhole) {
      const k = Math.round(line);
      return k > 0 ? lawCdf(k - 1, law) : 0;
    }
    return lawCdf(Math.floor(line), law);
  }
  // Continuous yards compound: integer line L pushes on (L - 0.5, L + 0.5]
  if (isWhole) {
    const L = Math.round(line);
    return Math.max(0, lawCdf(L - 0.5, law));
  }
  return lawCdf(line, law);
}

/** Push probability mass at integer lines (0 on half-point lines). */
export function pushProb(line: number, law: DistLaw): number {
  if (!isWholeNumberLine(line)) return 0;
  if (law.kind === "negbin") {
    const k = Math.round(line);
    const cdfK = lawCdf(k, law);
    const cdfPrior = k > 0 ? lawCdf(k - 1, law) : 0;
    return Math.max(0, cdfK - cdfPrior);
  }
  const L = Math.round(line);
  return Math.max(0, lawCdf(L + 0.5, law) - lawCdf(L - 0.5, law));
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

/* ---------- CLV & Model Divergence Metrics ---------- */

/**
 * Model-vs-close line difference standardized by model σ: (close − fair)/σ.
 * Per docs/EDGE_GATE.md §2, this is a diagnostic divergence measure, NOT CLV.
 * It measures model disagreement with the market and never contributes to a pass decision.
 */
export function modelVsCloseDivergence(closeLine: number, fairLine: number, sd: number): number {
  return sd > 0 ? (closeLine - fairLine) / sd : 0;
}

/** Standardized divergence alias kept for backwards compatibility. */
export function standardizedClv(rec: { fairLine: number; closeLine: number; sd: number }): number {
  return modelVsCloseDivergence(rec.closeLine, rec.fairLine, rec.sd);
}

/**
 * Price CLV (the primary gate estimand, docs/EDGE_GATE.md §2):
 * CLV_i = p_fair(entry, s) − p_fair(close, s)
 * where p_fair is the de-vigged implied probability of side s.
 * Positive CLV_i means the entry beat the close on that side.
 */
export function priceClv(entryFairProb: number, closeFairProb: number): number {
  return entryFairProb - closeFairProb;
}

/**
 * Line movement delta:
 * For OVER: close_line − entry_line (positive ⇒ market moved up, beating the close)
 * For UNDER: entry_line − close_line (positive ⇒ market moved down, beating the close)
 */
export function lineMovementDelta(side: "over" | "under", entryLine: number, closeLine: number): number {
  return side === "over" ? closeLine - entryLine : entryLine - closeLine;
}

export interface ClvRecord {
  /** model fair line (median) at evaluation */
  fairLine: number;
  /** market closing line */
  closeLine: number;
  /** model σ at evaluation */
  sd: number;
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
  const beat = zs.filter((z) => z < 0).length / n;
  return { n, mean, ci95: 1.96 * se, beatCloseRate: beat, sd };
}
