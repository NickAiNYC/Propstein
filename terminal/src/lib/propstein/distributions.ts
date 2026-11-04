/* ============================================================
   PropStein — distribution library
   Negative Binomial counts · Gamma yards-per-reception ·
   exact compound receiving-yards distribution.

   All functions are pure and deterministic. No approximation
   is used for the compound law: the sum of n iid Gamma(k, θ)
   variates is exactly Gamma(nk, θ), so the mixture over the
   NB count is computed in closed form and truncated only when
   the remaining count tail mass is below 1e-10.
   ============================================================ */

/* ---------- log-gamma (Lanczos) ---------- */
const LANCZOS_G = 7;
const LANCZOS_COEFFS = [
  0.99999999999980993, 676.5203681218851, -1259.1392167224028,
  771.32342877765313, -176.61502916214059, 12.507343278686905,
  -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
];

export function logGamma(x: number): number {
  if (x < 0.5) {
    // reflection: Γ(x)Γ(1-x) = π / sin(πx)
    return Math.log(Math.PI / Math.sin(Math.PI * x)) - logGamma(1 - x);
  }
  x -= 1;
  let a = LANCZOS_COEFFS[0];
  const t = x + LANCZOS_G + 0.5;
  for (let i = 1; i < LANCZOS_COEFFS.length; i++) {
    a += LANCZOS_COEFFS[i] / (x + i);
  }
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

export function logFactorial(n: number): number {
  return n <= 1 ? 0 : logGamma(n + 1);
}

/* ---------- regularized lower incomplete gamma P(a, x) ---------- */
function gammpSer(a: number, x: number): number {
  // series expansion for x < a + 1
  let ap = a;
  let sum = 1 / a;
  let del = sum;
  for (let n = 0; n < 512; n++) {
    ap += 1;
    del *= x / ap;
    sum += del;
    if (Math.abs(del) < Math.abs(sum) * 1e-14) break;
  }
  return sum * Math.exp(-x + a * Math.log(x) - logGamma(a));
}

function gammqCf(a: number, x: number): number {
  // continued fraction for Q(a,x) = 1 - P(a,x), x >= a + 1
  const FPMIN = 1e-300;
  let b = x + 1 - a;
  let c = 1 / FPMIN;
  let d = 1 / b;
  let h = d;
  for (let i = 1; i <= 512; i++) {
    const an = -i * (i - a);
    b += 2;
    d = an * d + b;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = b + an / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-14) break;
  }
  return Math.exp(-x + a * Math.log(x) - logGamma(a)) * h;
}

/** Regularized lower incomplete gamma P(a, x) — the Gamma(a) CDF at x. */
export function gammaCdfReg(a: number, x: number): number {
  if (a <= 0) return NaN;
  if (x <= 0) return 0;
  if (x < a + 1) return gammpSer(a, x);
  return 1 - gammqCf(a, x);
}

/* ---------- Gamma pdf ---------- */
export function gammaPdf(x: number, shape: number, scale: number): number {
  if (x <= 0 || shape <= 0 || scale <= 0) return 0;
  return Math.exp(
    (shape - 1) * Math.log(x) - x / scale - logGamma(shape) - shape * Math.log(scale)
  );
}

/* ============================================================
   Negative Binomial — NB2 parameterization (mean μ, size r).
   Support k = 0, 1, 2, …  Var = μ + μ²/r (overdispersed Poisson).
   ============================================================ */
export interface NegBinParams {
  /** dispersion/size — smaller r ⇒ heavier tails */
  r: number;
  /** modeled mean reception count */
  mu: number;
}

export function negBinLogPmf(k: number, { r, mu }: NegBinParams): number {
  if (k < 0 || !Number.isInteger(k)) return -Infinity;
  return (
    logGamma(k + r) -
    logGamma(r) -
    logFactorial(k) +
    r * Math.log(r / (r + mu)) +
    k * Math.log(mu / (r + mu))
  );
}

export function negBinPmf(k: number, p: NegBinParams): number {
  return Math.exp(negBinLogPmf(k, p));
}

/** P(N ≤ k). Kahan-compensated summation for accuracy. */
export function negBinCdf(k: number, p: NegBinParams): number {
  if (k < 0) return 0;
  const n = Math.floor(k);
  let cdf = 0;
  let c = 0;
  for (let i = 0; i <= n; i++) {
    const pmf = negBinPmf(i, p);
    const y = pmf - c;
    const t = cdf + y;
    c = t - cdf - y;
    cdf = t;
  }
  return Math.min(1, cdf);
}

/** Smallest k with P(N ≤ k) ≥ 0.5 — the integer median. */
export function negBinMedian(p: NegBinParams): number {
  const sd = Math.sqrt(p.mu + (p.mu * p.mu) / p.r);
  let lo = 0;
  let hi = Math.ceil(p.mu + 14 * sd + 24);
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (negBinCdf(mid, p) >= 0.5) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** P(N ≥ k) for any real k — betting-over probability at line k.
    For x.5 lines this equals P(N ≥ ceil(x)) since N is integer-valued. */
export function negBinSurvival(k: number, p: NegBinParams): number {
  if (k <= 0) return 1;
  return 1 - negBinCdf(Math.ceil(k) - 1, p);
}

/** Truncation bound for NB tail < 1e-10. */
export function negBinSupportMax(p: NegBinParams): number {
  const sd = Math.sqrt(p.mu + (p.mu * p.mu) / p.r);
  let hi = Math.ceil(p.mu + 14 * sd + 32);
  while (negBinSurvival(hi, p) > 1e-10 && hi < 400) hi += 8;
  return hi;
}

/* ============================================================
   Compound receiving-yards law.
   Y = Σ_{i=1..N} X_i,  N ~ NB2(r, μ),  X_i ~ Gamma(k, θ) iid.
   Exact because Σ_{i=1..n} X_i ~ Gamma(n·k, θ).
   Atom at 0: P(Y = 0) = P(N = 0).
   ============================================================ */
export interface CompoundParams {
  /** NB dispersion (receptions) */
  r: number;
  /** NB mean (expected receptions) */
  mu: number;
  /** Gamma shape (yards per reception) */
  k: number;
  /** Gamma scale (yards per reception) */
  theta: number;
}

export function compoundP0(p: CompoundParams): number {
  return negBinPmf(0, { r: p.r, mu: p.mu });
}

/** Continuous density of Y on (0, ∞) — mixture over n ≥ 1. */
export function compoundPdf(y: number, p: CompoundParams): number {
  if (y <= 0) return 0;
  const nb: NegBinParams = { r: p.r, mu: p.mu };
  const nMax = negBinSupportMax(nb);
  let dens = 0;
  let remaining = 1;
  for (let n = 1; n <= nMax; n++) {
    const pn = negBinPmf(n, nb);
    remaining -= pn;
    if (n > p.mu + 6 && (pn < 1e-13 || remaining < 1e-10)) break;
    dens += pn * gammaPdf(y, n * p.k, p.theta);
  }
  return dens;
}

/** P(Y ≤ y) including the atom at zero. */
export function compoundCdf(y: number, p: CompoundParams): number {
  if (y < 0) return 0;
  if (y === 0) return compoundP0(p);
  const nb: NegBinParams = { r: p.r, mu: p.mu };
  const nMax = negBinSupportMax(nb);
  let cdf = compoundP0(p);
  let remaining = 1 - compoundP0(p);
  for (let n = 1; n <= nMax; n++) {
    const pn = negBinPmf(n, nb);
    remaining -= pn;
    if (n > p.mu + 6 && (pn < 1e-13 || remaining < 1e-10)) break;
    cdf += pn * gammaCdfReg(n * p.k, y / p.theta);
    if (remaining < 1e-12) break;
  }
  return Math.min(1, cdf);
}

/** Mean of Y = E[N] · E[X] = μ·kθ. */
export function compoundMean(p: CompoundParams): number {
  return p.mu * p.k * p.theta;
}

/** Median by bisection on the exact CDF. */
export function compoundMedian(p: CompoundParams): number {
  const mean = compoundMean(p);
  let lo = 0;
  let hi = Math.max(mean * 4, 1);
  while (compoundCdf(hi, p) < 0.5) hi *= 2;
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    if (compoundCdf(mid, p) < 0.5) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

/** P(Y ≥ y) for a betting line. y > 0 continuous. */
export function compoundSurvival(y: number, p: CompoundParams): number {
  if (y <= 0) return 1;
  return 1 - compoundCdf(y, p);
}

/* ---------- unified law interface ---------- */
export interface DistLaw {
  kind: "negbin" | "compound";
  nb: NegBinParams;
  gamma?: { k: number; theta: number };
}

export function lawCdf(x: number, law: DistLaw): number {
  if (law.kind === "negbin") return negBinCdf(x, law.nb);
  return compoundCdf(x, {
    r: law.nb.r,
    mu: law.nb.mu,
    k: law.gamma!.k,
    theta: law.gamma!.theta,
  });
}

export function lawSurvival(x: number, law: DistLaw): number {
  if (law.kind === "negbin") return negBinSurvival(x, law.nb);
  return compoundSurvival(x, {
    r: law.nb.r,
    mu: law.nb.mu,
    k: law.gamma!.k,
    theta: law.gamma!.theta,
  });
}

export function lawMean(law: DistLaw): number {
  if (law.kind === "negbin") return law.nb.mu;
  return law.nb.mu * law.gamma!.k * law.gamma!.theta;
}

export function lawMedian(law: DistLaw): number {
  if (law.kind === "negbin") return negBinMedian(law.nb);
  return compoundMedian({
    r: law.nb.r,
    mu: law.nb.mu,
    k: law.gamma!.k,
    theta: law.gamma!.theta,
  });
}

/** Exact standard deviation:
    NB: sqrt(μ + μ²/r)
    Compound (total variance): sqrt(E[N]·Var(X) + Var(N)·E[X]²) */
export function lawSd(law: DistLaw): number {
  if (law.kind === "negbin") {
    const { mu, r } = law.nb;
    return Math.sqrt(mu + (mu * mu) / r);
  }
  const { r, mu } = law.nb;
  const { k, theta } = law.gamma!;
  const varN = mu + (mu * mu) / r;
  const ex = k * theta;
  const varX = k * theta * theta;
  return Math.sqrt(mu * varX + varN * ex * ex);
}

/** Inverse CDF (quantile) for probability q ∈ (0,1). */
export function lawQuantile(q: number, law: DistLaw): number {
  let hi = Math.max(lawMean(law) * 6, 8);
  while (lawCdf(hi, law) < q) hi *= 2;
  let lo = 0;
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    if (lawCdf(mid, law) < q) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}
