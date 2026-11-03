/**
 * PropStein Live Sniper — Odds Mathematics
 * =======================================
 * Exact formulas per spec §7, cross-checked against the repo's
 * `src/contracts/odds.py` American-odds conventions (|odds| >= 100).
 *
 *   decimal from American:  d = 1 + a/100          (a > 0)
 *                           d = 1 + 100/|a|        (a < 0)
 *   break-even probability: P* = 1/d
 *   EV per unit staked:     EV = p(d-1) - (1-p)
 *
 * All functions are pure and throw on invalid input — never return
 * fabricated numbers.
 */

export class InvalidOddsError extends Error {
  constructor(value: unknown, reason: string) {
    super(`Invalid odds ${JSON.stringify(value)}: ${reason}`);
    this.name = "InvalidOddsError";
  }
}

const MIN_ABS_AMERICAN = 100;

function assertFiniteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new InvalidOddsError(value, `${label} must be a finite number`);
  }
  return value;
}

/** American odds (+160 / -110) → decimal odds (2.60 / 1.909...). */
export function americanToDecimal(american: number): number {
  const a = assertFiniteNumber(american, "american odds");
  if (a === 0) throw new InvalidOddsError(a, "0 is not a valid American odds price");
  if (Math.abs(a) < MIN_ABS_AMERICAN) {
    throw new InvalidOddsError(a, `|odds| must be >= ${MIN_ABS_AMERICAN} (repo contract)`);
  }
  return a > 0 ? 1 + a / 100 : 1 + 100 / Math.abs(a);
}

/** Decimal odds → American odds. d > 1 required. */
export function decimalToAmerican(decimal: number): number {
  const d = assertFiniteNumber(decimal, "decimal odds");
  if (d <= 1) throw new InvalidOddsError(d, "decimal odds must be > 1");
  return d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1));
}

/** Implied (break-even) probability of decimal odds: 1/d. */
export function impliedProbability(decimal: number): number {
  const d = assertFiniteNumber(decimal, "decimal odds");
  if (d <= 1) throw new InvalidOddsError(d, "decimal odds must be > 1");
  return 1 / d;
}

/** Break-even probability — alias of impliedProbability (spec terminology). */
export const breakEvenProbability = impliedProbability;

/** Implied probability directly from American odds. */
export function americanImpliedProbability(american: number): number {
  return impliedProbability(americanToDecimal(american));
}

/**
 * Expected value per unit staked:
 *   EV = p(d-1) - (1-p)
 */
export function expectedValue(modelProbability: number, decimal: number): number {
  const p = assertFiniteNumber(modelProbability, "model probability");
  const d = assertFiniteNumber(decimal, "decimal odds");
  if (p < 0 || p > 1) throw new InvalidOddsError(p, "probability must be in [0, 1]");
  if (d <= 1) throw new InvalidOddsError(d, "decimal odds must be > 1");
  return p * (d - 1) - (1 - p);
}

/** Probability-point discrepancy: p - 1/d. */
export function probabilityEdge(modelProbability: number, decimal: number): number {
  return modelProbability - impliedProbability(decimal);
}

/** Fair decimal odds for a model probability: 1/p. */
export function fairDecimalOdds(modelProbability: number): number {
  const p = assertFiniteNumber(modelProbability, "model probability");
  if (p <= 0 || p >= 1) throw new InvalidOddsError(p, "fair odds require 0 < p < 1");
  return 1 / p;
}

/**
 * Two-way multiplicative devig. Returns no-vig probabilities that sum to 1.
 * (Baseline method; documented as such — power/Shin methods are future work.)
 */
export function devigTwoWay(decimalA: number, decimalB: number): { pA: number; pB: number; vig: number } {
  const ia = impliedProbability(decimalA);
  const ib = impliedProbability(decimalB);
  const sum = ia + ib;
  if (sum < 0.98 || sum > 1.45) {
    // Mirrors the repo OddsQuote vig validator range.
    throw new InvalidOddsError([decimalA, decimalB], `implied sum ${sum.toFixed(4)} outside [0.98, 1.45]`);
  }
  return { pA: ia / sum, pB: ib / sum, vig: sum - 1 };
}

/**
 * Uncertainty haircut: shrink a model probability toward the break-even
 * probability by `margin` before making an alert decision. Display values
 * remain raw; this only feeds the alert threshold check.
 */
export function applyProbabilityHaircut(
  modelProbability: number,
  breakEven: number,
  margin: number,
): number {
  const p = assertFiniteNumber(modelProbability, "model probability");
  const b = assertFiniteNumber(breakEven, "break-even probability");
  const m = assertFiniteNumber(margin, "haircut margin");
  if (m < 0 || m > 1) throw new InvalidOddsError(m, "haircut margin must be in [0, 1]");
  return b + (p - b) * (1 - m);
}

/** Format American odds for terminal display: +160 / -110. */
export function formatAmerican(american: number): string {
  const a = assertFiniteNumber(american, "american odds");
  if (Math.abs(a) < MIN_ABS_AMERICAN) {
    throw new InvalidOddsError(a, `|odds| must be >= ${MIN_ABS_AMERICAN}`);
  }
  return a > 0 ? `+${Math.round(a)}` : `-${Math.round(Math.abs(a))}`;
}

/** Parse displayed odds text into American odds number. Fail-safe. */
export function parseAmericanOddsText(text: string): number | undefined {
  const t = (text ?? "").trim();
  if (!t) return undefined;
  // "EVEN" / "EVEN MONEY" → +100
  if (/^even(\s+money)?$/i.test(t)) return 100;
  // "+160", "-110", "160", "−110" (typographic minus), "1,000"
  const normalized = t.replace(/[−–—]/g, "-").replace(/,/g, "");
  const m = /^([+-]?)\s*(\d+(?:\.\d+)?)$/.exec(normalized);
  if (!m) return undefined;
  const sign = m[1] === "-" ? -1 : 1;
  const value = Math.round(parseFloat(m[2]!));
  const signed = sign * value;
  if (Math.abs(signed) < MIN_ABS_AMERICAN) return undefined;
  return signed;
}

/** Parse decimal odds text ("2.60"). Fail-safe. */
export function parseDecimalOddsText(text: string): number | undefined {
  const t = (text ?? "").trim();
  const m = /^\d+(?:\.\d+)?$/.exec(t);
  if (!m) return undefined;
  const d = parseFloat(t);
  return d > 1 && Number.isFinite(d) ? d : undefined;
}

/** Percentage formatting for terminal display: 38.46% */
export function formatPercent(value: number, digits = 2): string {
  const v = assertFiniteNumber(value, "percentage value");
  return `${(v * 100).toFixed(digits)}%`;
}

/** EV formatting: +14.4% / -2.1% */
export function formatEvPerUnit(value: number): string {
  const v = assertFiniteNumber(value, "EV value");
  const pct = v * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}
