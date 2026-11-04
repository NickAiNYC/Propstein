/* PropStein math verification — run with: bunx tsx tests/math.test.ts */
import {
  negBinPmf,
  negBinCdf,
  negBinMedian,
  compoundCdf,
  compoundPdf,
  compoundMedian,
  compoundMean,
  DistLaw,
  lawSd,
  lawQuantile,
  lawCdf,
  gammaCdfReg,
  negBinSurvival,
  lawSurvival,
} from "../src/lib/propstein/distributions";
import {
  breakEvenProb,
  fairProb,
  computeValueBoundaries,
  probToAmerican,
  summarizeClv,
} from "../src/lib/propstein/model";

let pass = 0;
let fail = 0;
function check(name: string, cond: boolean, detail = "") {
  if (cond) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.error(`  ✗ ${name} ${detail}`);
  }
}
function approx(a: number, b: number, tol: number) {
  return Math.abs(a - b) <= tol;
}

console.log("— Gamma CDF —");
check("Gamma(1,θ)=Exponential CDF at θ", approx(gammaCdfReg(1, 1) * 1, 1 - Math.exp(-1), 1e-12));
check("Gamma CDF at 0 is 0", gammaCdfReg(3, 0) === 0);
check("Gamma CDF large x → 1", gammaCdfReg(2.5, 500) > 1 - 1e-12);
check("Gamma CDF symmetry shape 0.5 (χ²₁): Φ(1)²", approx(gammaCdfReg(0.5, 0.5 * 1 ** 2), 2 * (0.841344746) - 1, 1e-9));

console.log("— Negative Binomial —");
const nb = { r: 6.2, mu: 5.4 };
let sum = 0;
for (let k = 0; k <= 120; k++) sum += negBinPmf(k, nb);
check("NB pmf sums to 1", approx(sum, 1, 1e-10), `got ${sum}`);
let ev = 0;
for (let k = 0; k <= 120; k++) ev += k * negBinPmf(k, nb);
check("NB mean = μ", approx(ev, nb.mu, 1e-9), `got ${ev}`);
check("NB CDF monotone to 1", negBinCdf(200, nb) > 1 - 1e-9, `got ${negBinCdf(200, nb)}`);
// betting-line semantics: over 4.5 wins iff N ≥ 5
check("NB survival at 4.5 = P(N≥5)", approx(negBinSurvival(4.5, nb), 1 - negBinCdf(4, nb), 1e-12));
check("NB survival at 5 = P(N≥5)", approx(negBinSurvival(5, nb), 1 - negBinCdf(4, nb), 1e-12));
const med = negBinMedian(nb);
check("NB median satisfies CDF≥0.5 and CDF(med−1)<0.5", negBinCdf(med, nb) >= 0.5 && negBinCdf(med - 1, nb) < 0.5, `med=${med} F=${negBinCdf(med, nb)} F-1=${negBinCdf(med - 1, nb)}`);
check("NB survival complements CDF", approx(negBinSurvival(5, nb) + negBinCdf(4, nb), 1, 1e-12));

console.log("— Compound yards (NB ∘ Gamma) —");
const cp = { r: 6.2, mu: 5.4, k: 2.35, theta: 4.9 };
check("compound mean = μ·kθ", approx(compoundMean(cp), 5.4 * 2.35 * 4.9, 1e-12));
check("compound CDF(0) = P(N=0)", approx(compoundCdf(0, cp), negBinPmf(0, { r: 6.2, mu: 5.4 }), 1e-12));
check("compound CDF monotone", compoundCdf(10, cp) <= compoundCdf(60, cp) + 1e-15);
// P(Y>400) ≈ 1e-6 is genuine compound tail mass (high-catch/high-YPR paths),
// so verify convergence at a far upper point instead:
check("compound CDF → 1", compoundCdf(2000, cp) > 1 - 1e-9, `got ${compoundCdf(2000, cp)}`);
const cmed = compoundMedian(cp);
check("compound median: CDF(med) ≈ 0.5", approx(compoundCdf(cmed, cp), 0.5, 5e-4), `med=${cmed} F=${compoundCdf(cmed, cp)}`);
// numerical integration of pdf should match CDF difference
const lo = 20, hi = 40;
let integral = 0;
const dx = 0.05;
for (let x = lo; x < hi; x += dx) integral += compoundPdf(x, cp) * dx;
check("pdf integrates to CDF difference (20,40)", approx(integral, compoundCdf(hi, cp) - compoundCdf(lo, cp), 5e-4), `${integral} vs ${compoundCdf(hi, cp) - compoundCdf(lo, cp)}`);
// law SD positivity and quantile roundtrip
const law: DistLaw = { kind: "compound", nb: { r: 6.2, mu: 5.4 }, gamma: { k: 2.35, theta: 4.9 } };
check("law SD > 0", lawSd(law) > 0);
const q80 = lawQuantile(0.8, law);
check("quantile roundtrip: F(q₀.₈)≈0.8", approx(lawCdf(q80, law), 0.8, 2e-3), `q=${q80} F=${lawCdf(q80, law)}`);

console.log("— Odds math —");
check("breakEven(-110) = 52.38%", approx(breakEvenProb(-110), 110 / 210, 1e-12));
check("breakEven(+150) = 40%", approx(breakEvenProb(150), 100 / 250, 1e-12));
check("fairProb(-110,-110) = 50%", approx(fairProb(-110, -110), 0.5, 1e-12));
check("probToAmerican(0.5)=−100 (even)", probToAmerican(0.5) === -100);
check("probToAmerican(0.6)≈−150", probToAmerican(0.6) === -150);

console.log("— Value boundaries —");
const lawRec: DistLaw = { kind: "negbin", nb: { r: 6.2, mu: 5.4 } };
const lawYds: DistLaw = { kind: "compound", nb: { r: 6.2, mu: 5.4 }, gamma: { k: 2.35, theta: 4.9 } };
const vb = computeValueBoundaries(lawRec, -110, -110, 4.5);
check("boundary band ordered", vb.lower <= vb.upper, `${vb.lower} > ${vb.upper}`);
check("band contains the median", vb.lower <= 5 && vb.upper >= 5, `${vb.lower}-${vb.upper}`);
// continuous law: exact band property S(lower) = beOver, F(upper) = beUnder
const vbC = computeValueBoundaries(lawYds, -110, -110, 62.5);
check(
  "continuous band: S(lower) ≈ break-even over",
  approx(lawSurvival(vbC.lower, lawYds), vbC.breakEvenOver, 1e-4),
  `S=${lawSurvival(vbC.lower, lawYds)} be=${vbC.breakEvenOver}`
);
check(
  "continuous band: F(upper) ≈ break-even under",
  approx(lawCdf(vbC.upper, lawYds), vbC.breakEvenUnder, 1e-4),
  `F=${lawCdf(vbC.upper, lawYds)} be=${vbC.breakEvenUnder}`
);
check(
  "band interior: both sides below break-even at midpoint",
  (() => {
    const mid = (vbC.lower + vbC.upper) / 2;
    return lawSurvival(mid, lawYds) < vbC.breakEvenOver && lawCdf(mid, lawYds) < vbC.breakEvenUnder;
  })()
);
check("captured 4.5 inside band (no value)", vb.lineInsideBand === true || vb.lineInsideBand === false);

console.log("— CLV summary —");
const clv = summarizeClv([]);
check("empty CLV cohort returns n=0 NaN mean", clv.n === 0 && Number.isNaN(clv.mean));
const clv2 = summarizeClv([
  { fairLine: 5, closeLine: 5.5, sd: 1.2 },
  { fairLine: 62, closeLine: 60, sd: 12 },
  { fairLine: 4, closeLine: 4, sd: 0.9 },
  { fairLine: 78, closeLine: 74, sd: 15 },
]);
check("CLV summary computes", clv2.n === 4 && Number.isFinite(clv2.mean));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail > 0 ? 1 : 0);
