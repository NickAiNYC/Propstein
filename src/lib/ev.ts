// Propstein 2.0 — expected-value math (shared shape with worker/ev.py)
// American odds <-> decimal <-> implied probability, fair odds, EV, Kelly.

export function americanToDecimal(american: number): number {
  // +150: stake 100 to win 150 -> 2.50 | -110: stake 110 to win 100 -> 1.909
  return american > 0 ? 1 + american / 100 : 1 + 100 / Math.abs(american);
}

export function decimalToAmerican(decimal: number): number {
  if (decimal >= 2) return Math.round(100 * (decimal - 1));
  return -Math.round(100 / (decimal - 1));
}

export function impliedProb(decimal: number): number {
  return 1 / decimal;
}

/**
 * Model win probability for a total-style prop at `line` given a `fairLine`
 * (model mean), using a Gaussian tail with a market-aware sigma.
 * sigma = max(floor, cv * fairLine) keeps short markets honest.
 */
export function probOver(fairLine: number, line: number, market: string): number {
  const floors: Record<string, number> = {
    receptions: 1.4,
    receiving_yards: 9.5,
    yards: 9.5,
    points: 4.5,
    rebounds: 3.2,
    assists: 2.6,
    threes: 1.2,
  };
  const cvs: Record<string, number> = {
    receptions: 0.34,
    receiving_yards: 0.26,
    yards: 0.26,
    points: 0.24,
    rebounds: 0.28,
    assists: 0.3,
    threes: 0.42,
  };
  const floor = floors[market] ?? 4.0;
  const cv = cvs[market] ?? 0.3;
  const sigma = Math.max(floor, cv * Math.max(fairLine, 1));
  // P(X > line) with continuity-style half-step for discrete markets
  const z = (fairLine - line - 0.25) / sigma;
  return normalCdf(z);
}

export function normalCdf(z: number): number {
  // Abramowitz & Stegun 7.1.26 via erf approximation
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989422804014327 * Math.exp((-z * z) / 2);
  const p =
    d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - p : p;
}

export interface OddsQuote {
  fairLine: number;
  line: number;
  market: string;
  overOdds?: number | null;
  underOdds?: number | null;
}

export interface ModelEdge {
  bestSide: "OVER" | "UNDER";
  probWin: number;
  fairOdds: number;
  ev: number;
  kelly: number;
  lean: "WATCH" | "PASS";
}

/** Full edge computation for one prop quote. Matches worker/ev.py. */
export function computeEdge(q: OddsQuote): ModelEdge {
  const pOver = probOver(q.fairLine, q.line, q.market);
  const pUnder = 1 - pOver;
  const overDec = q.overOdds != null ? americanToDecimal(q.overOdds) : 1.909;
  const underDec = q.underOdds != null ? americanToDecimal(q.underOdds) : 1.909;
  const evOver = pOver * overDec - 1;
  const evUnder = pUnder * underDec - 1;
  const bestSide: "OVER" | "UNDER" = evOver >= evUnder ? "OVER" : "UNDER";
  const probWin = bestSide === "OVER" ? pOver : pUnder;
  const dec = bestSide === "OVER" ? overDec : underDec;
  const b = dec - 1;
  const fairDecimal = 1 / probWin;
  const fairOdds = decimalToAmerican(fairDecimal);
  const ev = (probWin * dec - 1) * 100; // percent of stake
  const kellyRaw = b > 0 ? (probWin * dec - 1) / b : 0;
  const kelly = Math.max(0, Math.min(0.25, kellyRaw)); // quarter-cap guard applied at 1x
  const lean: "WATCH" | "PASS" = ev >= 2 && kelly > 0.005 ? "WATCH" : "PASS";
  return { bestSide, probWin, fairOdds, ev, kelly, lean };
}
