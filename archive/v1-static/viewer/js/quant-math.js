/**
 * PropWire Quant Math — the frozen odds & distribution engine.
 *
 * Extracted 2026-11-02 from viewer/app.js §22 (behavior-preserving; numerics
 * are byte-identical and pinned by test/quant-math.golden.mjs, whose
 * fixtures were generated from the pre-extraction implementation).
 *
 * What lives here and why it is a module:
 *   - americanToDecimal / impliedProbability / devig — market pricing math.
 *   - regularizedGammaP / logGamma — the Lanczos machinery behind the
 *     compound yards CDF.
 *   - createQuantMath({ alpha, k }) — binds the per-sport model constants
 *     (NFL: alpha 0.1097, k 1.555, calibrated NegBin/Gamma pair) and returns
 *     pRecOver / pYardsOver / compoundYardsCdf.
 *
 * Contract:
 *   - PURE functions. No DOM, no state, no adapters, no fetch. app.js owns
 *     anything that reads `state` (e.g. targetLine stays there).
 *   - Load order: this file loads BEFORE /app.js (all scripts `defer`,
 *     document order). app.js throws if the namespace is missing — same
 *     fail-fast pattern as the sport registry.
 *   - The numeric helpers `num`/`finite` are faithful ports of the app.js §4
 *     coercers: the degenerate-input behavior of americanToDecimal (null /
 *   non-numeric / zero → 0) depends on their exact semantics.
 */
(() => {
  'use strict';

  // Faithful port of app.js §4 coercers (see contract above).
  const finite = (value) => Number.isFinite(Number(value));
  const num = (value, fallback = 0) => finite(value) ? Number(value) : fallback;

  function americanToDecimal(odds) {
    const value = num(odds, NaN);
    if (!value || Math.abs(value) === 0 || !Number.isFinite(value)) return 0;
    return value > 0 ? value / 100 + 1 : 100 / Math.abs(value) + 1;
  }

  function impliedProbability(odds) {
    const dec = americanToDecimal(odds);
    return dec > 0 ? 1 / dec : 0;
  }

  function devig(overOdds, underOdds) {
    const overRaw = impliedProbability(overOdds);
    const underRaw = impliedProbability(underOdds);
    const sum = overRaw + underRaw;
    return sum > 0 ? { over: overRaw / sum, under: underRaw / sum } : { over: 0.5, under: 0.5 };
  }

  function regularizedGammaP(shape, value) {
    if (value <= 0) return 0;
    if (shape <= 0) return 1;
    if (value < shape + 1) {
      let sum = 1 / shape;
      let term = sum;
      for (let n = 1; n < 100; n += 1) {
        term *= value / (shape + n);
        sum += term;
        if (term < sum * 1e-12) break;
      }
      return sum * Math.exp(-value + shape * Math.log(value) - logGamma(shape));
    }
    let a0 = 1, a1 = value, b0 = 0, b1 = 1, factor = 1, fraction = 0;
    for (let n = 1; n < 100; n += 1) {
      const coefficient = n - shape;
      a0 = (a1 + a0 * coefficient) * factor;
      b0 = (b1 + b0 * coefficient) * factor;
      const scaled = n * factor;
      a1 = value * a0 + scaled * a1;
      b1 = value * b0 + scaled * b1;
      if (a1 !== 0) { factor = 1 / a1; fraction = b1 * factor; }
    }
    return 1 - Math.exp(-value + shape * Math.log(value) - logGamma(shape)) * fraction;
  }

  function logGamma(value) {
    const coefficients = [57.1562356658629235, -59.5979603554754912, 14.1360979747417471, -0.4919138160960292, 0.00003399464998481189, 0.00004652362892704858, -0.00009837447530487956, 0.0001580887032249125, -0.00021026444172410488, 0.00021743961811521265, -0.0001643181065367639, 0.00008441822398385275, -0.000026190838401581408, 0.0000036899182659531625];
    if (value <= 0) return 0;
    let y = value;
    let temporary = value + 5.2421875;
    temporary = (value + 0.5) * Math.log(temporary) - temporary;
    let series = 0.9999999999999971;
    coefficients.forEach((coefficient) => { y += 1; series += coefficient / y; });
    return temporary + Math.log(2.5066282746310005 * series / value);
  }

  /**
   * Bind the per-sport model constants and return the distribution functions.
   * Adapters without a distribution model pass alpha/k as null — the returned
   * functions exist (call sites stay uniform) but are only ever invoked on
   * rows of a sport that actually carries a model (app.js §1 contract).
   */
  function createQuantMath({ alpha, k } = {}) {
    const MODEL_ALPHA = alpha;
    const MODEL_K = k;

    function pRecOver(mu, line) {
      const r = 1 / MODEL_ALPHA;
      const p = r / (r + mu);
      const maximum = Math.floor(line);
      let cdf = 0;
      let term = Math.pow(p, r);
      cdf += term;
      for (let k2 = 1; k2 <= maximum; k2 += 1) {
        term *= ((k2 - 1 + r) / k2) * (1 - p);
        cdf += term;
      }
      return Math.max(0, Math.min(1, 1 - cdf));
    }

    function compoundYardsCdf(muRec, muYpr, line) {
      if (line <= 0) return 0;
      const r = 1 / MODEL_ALPHA;
      const p = r / (r + muRec);
      const scale = muYpr / MODEL_K;
      if (!(scale > 0)) return 1;
      let cdf = Math.pow(p, r);
      let nbProbability = cdf;
      for (let n = 1; n <= 36; n += 1) {
        nbProbability *= ((n - 1 + r) / n) * (1 - p);
        cdf += nbProbability * regularizedGammaP(n * MODEL_K, line / scale);
      }
      return Math.max(0, Math.min(1, cdf));
    }

    function pYardsOver(muRec, muYpr, line) {
      return Math.max(0, Math.min(1, 1 - compoundYardsCdf(muRec, muYpr, line)));
    }

    return Object.freeze({ pRecOver, pYardsOver, compoundYardsCdf });
  }

  const PropWireMath = {
    americanToDecimal,
    impliedProbability,
    devig,
    regularizedGammaP,
    logGamma,
    createQuantMath,
  };

  Object.freeze(PropWireMath);
  window.PropSteinMath = PropWireMath;
  window.PropWireMath = PropWireMath;
})();
