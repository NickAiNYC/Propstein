import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { buildSandbox, loadApp } from './helpers/sandbox.mjs';

/**
 * QUANT MATH GOLDENS (2026-11-02) — characterization pins for the §22
 * odds & distribution math ("the frozen model").
 *
 * Every expectation below was generated from the live pre-extraction
 * implementation (scripts/generate_quant_goldens.mjs, app.js @ main) and is
 * asserted with exact double equality — JSON round-trips doubles losslessly,
 * so any bit-level numeric drift in a refactor, dependency bump, or engine
 * change fails here. If a delta is EARNED (e.g. a recalibrated model), the
 * whitelist procedure is: regenerate fixtures, document the calibration
 * change in the PR, and update this table in the same commit.
 *
 * The NFL model constants (alpha=0.1097, k=1.555) come from the sport
 * adapter; they are asserted first so a silent constants change cannot hide
 * behind "just math" deltas.
 */

const ODDS_CASES = [
  [-300, 1.3333333333333333],
  [-110, 1.9090909090909092],
  [-105, 1.9523809523809523],
  [-100, 2],
  [0, 0],
  [100, 2],
  [110, 2.1],
  [150, 2.5],
  [250, 3.5],
  [null, 0],
  ['abc', 0],
  ['', 0]
];

const IMPLIED_CASES = [
  [-300, 0.75],
  [-110, 0.5238095238095238],
  [-105, 0.5121951219512195],
  [-100, 0.5],
  [0, 0],
  [100, 0.5],
  [110, 0.47619047619047616],
  [150, 0.4],
  [250, 0.2857142857142857],
  [null, 0],
  ['abc', 0],
  ['', 0]
];

const DEVIG_CASES = [
  [[-110, -110], { over: 0.5, under: 0.5 }],
  [[-105, -115], { over: 0.4891657638136511, under: 0.5108342361863489 }],
  [[100, -120], { over: 0.4782608695652174, under: 0.5217391304347826 }],
  [[-220, 180], { over: 0.6581196581196581, under: 0.3418803418803419 }],
  [[0, 0], { over: 0.5, under: 0.5 }],
  [[null, -110], { over: 0, under: 1 }]
];

const REC_GRID = [];
for (const mu of [1.2, 2.5, 4.9, 5.1, 8.7]) {
  for (const line of [0.5, 1.5, 3.5, 6.5, 10.5]) REC_GRID.push([mu, line]);
}
const REC_EXPECTED = [
  0.6761025224756021, 0.3326390773611865, 0.043454642882974515, 0.0008368277422762249, 0.0000017631404461981859,
  0.8902200926355961, 0.6748386773630753, 0.25340519561542285, 0.027858867466938886, 0.000649874699407027,
  0.9801866006263845, 0.917042689983525, 0.6607511501948843, 0.2516046618118749, 0.036263036234456925,
  0.9825873137537219, 0.9256418772554127, 0.6849561768862087, 0.27668291979017723, 0.043747491172178465,
  0.9977756226659661, 0.9878737695015032, 0.9191649286599105, 0.6735391794027334, 0.29714858239021513
];

const YDS_GRID = [];
for (const [muRec, muYpr] of [[3.1, 7.4], [4.2, 8.8], [6.5, 12.1]]) {
  for (const line of [12.5, 29.5, 55.5, 80.5, 120.5]) YDS_GRID.push([muRec, muYpr, line]);
}
const YDS_EXPECTED = [
  0.6626021095826592, 0.30167523009599784, 0.059958392854423836, 0.00946911848510934, 0.00034231545808582897,
  0.8267078539827348, 0.5460719291630591, 0.2128317387864146, 0.06750736621782905, 0.0077701507603754605,
  0.9595856807893424, 0.8628239930527934, 0.6432492998764818, 0.4248652531729261, 0.17678067318434443
];
const YDS_CDF_EXPECTED = [
  0.3373978904173408, 0.6983247699040022, 0.9400416071455762, 0.9905308815148907, 0.9996576845419142,
  0.17329214601726511, 0.4539280708369408, 0.7871682612135854, 0.932492633782171, 0.9922298492396245,
  0.04041431921065765, 0.13717600694720658, 0.3567507001235182, 0.5751347468270739, 0.8232193268156556
];

const GAMMA_CASES = [
  [[1, 0.5], 0.39346934028734454],
  [[0.5, 1.2], 0.8786647496414963],
  [[2, 3.5], 0.8641117745995713],
  [[5, 12], 0.9923996093189333],
  [[3, 30], 0.9999999999549898],
  [[8, 0.1], 2.2693269500713511e-13],
  [[0.25, 4.75], 0.9993469351898926]
];

const LOGGAMMA_CASES = [
  [0.1, 2.2527126517342193],
  [0.5, 0.5723649429247182],
  [1, 2.4424906541753444e-14],
  [2.5, 0.2846828704729565],
  [10, 12.801827480081519],
  [142.8, 564.1331527005613],
  [1e-3, 6.907178885383866]
];

test('NFL model constants are the calibrated NegBin/Gamma pair (alpha 0.1097, k 1.555)', () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  assert.equal(P.adapter.model.alpha, 0.1097);
  assert.equal(P.adapter.model.k, 1.555);
});

test('americanToDecimal matches the frozen goldens (incl. degenerate inputs)', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  for (const [input, expected] of ODDS_CASES) {
    assert.equal(M.americanToDecimal(input), expected, `americanToDecimal(${JSON.stringify(input)})`);
  }
});

test('impliedProbability matches the frozen goldens', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  for (const [input, expected] of IMPLIED_CASES) {
    assert.equal(M.impliedProbability(input), expected, `impliedProbability(${JSON.stringify(input)})`);
  }
});

test('devig matches the frozen goldens and stays normalized', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  for (const [[over, under], expected] of DEVIG_CASES) {
    const got = M.devig(over, under);
    assert.equal(got.over, expected.over, `devig(${over}, ${under}).over`);
    assert.equal(got.under, expected.under, `devig(${over}, ${under}).under`);
  }
});

test('pRecOver matches the frozen goldens on the mu × line grid', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  REC_GRID.forEach(([mu, line], i) => {
    assert.equal(M.pRecOver(mu, line), REC_EXPECTED[i], `pRecOver(${mu}, ${line}) [case ${i}]`);
  });
});

test('pYardsOver and compoundYardsCdf match the frozen goldens and complement exactly', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  YDS_GRID.forEach(([muRec, muYpr, line], i) => {
    assert.equal(M.pYardsOver(muRec, muYpr, line), YDS_EXPECTED[i], `pYardsOver(${muRec}, ${muYpr}, ${line}) [case ${i}]`);
    assert.equal(M.compoundYardsCdf(muRec, muYpr, line), YDS_CDF_EXPECTED[i], `compoundYardsCdf(${muRec}, ${muYpr}, ${line}) [case ${i}]`);
    // pYardsOver is defined as max(0, min(1, 1 - cdf)) — on this in-range grid
    // the complement identity must hold bit-exactly.
    if (YDS_EXPECTED[i] > 0 && YDS_EXPECTED[i] < 1) {
      assert.equal(M.pYardsOver(muRec, muYpr, line), 1 - M.compoundYardsCdf(muRec, muYpr, line));
    }
  });
});

test('regularizedGammaP matches the frozen goldens across both series branches', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  for (const [[shape, value], expected] of GAMMA_CASES) {
    assert.equal(M.regularizedGammaP(shape, value), expected, `regularizedGammaP(${shape}, ${value})`);
  }
});

test('logGamma matches the frozen goldens (Lanczos, incl. the logGamma(1)≈2.4e-14 residue)', () => {
  const { sandbox } = buildSandbox();
  const M = loadApp(sandbox).quantMath;
  for (const [value, expected] of LOGGAMMA_CASES) {
    assert.equal(M.logGamma(value), expected, `logGamma(${value})`);
  }
});

/** Bare-window VM with ONLY viewer/js/quant-math.js loaded — no app.js, no
 *  adapters, no DOM. Proves the extracted module is standalone and that the
 *  app.js-bound functions are the very same objects the module exports. */
function loadModuleOnly() {
  const window = {};
  const ctx = { window, Math, Number, console };
  vm.createContext(ctx);
  const file = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'viewer', 'js', 'quant-math.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: 'viewer/js/quant-math.js' });
  return window.PropWireMath;
}

test('the extracted module is standalone (loads with no app.js/adapters) and matches the same goldens', () => {
  const M = loadModuleOnly();
  assert.ok(M, 'window.PropWireMath must exist after loading only quant-math.js');
  for (const [input, expected] of ODDS_CASES) {
    assert.equal(M.americanToDecimal(input), expected, `module americanToDecimal(${JSON.stringify(input)})`);
  }
  for (const [[shape, value], expected] of GAMMA_CASES) {
    assert.equal(M.regularizedGammaP(shape, value), expected, `module regularizedGammaP(${shape}, ${value})`);
  }
  for (const [value, expected] of LOGGAMMA_CASES) {
    assert.equal(M.logGamma(value), expected, `module logGamma(${value})`);
  }
  const bound = M.createQuantMath({ alpha: 0.1097, k: 1.555 });
  REC_GRID.forEach(([mu, line], i) => {
    assert.equal(bound.pRecOver(mu, line), REC_EXPECTED[i], `module pRecOver(${mu}, ${line}) [case ${i}]`);
  });
  YDS_GRID.forEach(([muRec, muYpr, line], i) => {
    assert.equal(bound.pYardsOver(muRec, muYpr, line), YDS_EXPECTED[i], `module pYardsOver(${muRec}, ${muYpr}, ${line}) [case ${i}]`);
  });
});

test('app.js binds the exact module functions (single source of numeric truth)', () => {
  const { sandbox } = buildSandbox();
  const P = loadApp(sandbox);
  const moduleExports = sandbox.window.PropWireMath;
  assert.ok(moduleExports, 'app boot requires window.PropWireMath');
  // Same vm context, so identity must hold: the names app.js destructured in
  // §22 ARE the module's export objects — no copies, no adapters in between.
  assert.equal(P.quantMath.americanToDecimal, moduleExports.americanToDecimal);
  assert.equal(P.quantMath.impliedProbability, moduleExports.impliedProbability);
  assert.equal(P.quantMath.devig, moduleExports.devig);
  assert.equal(P.quantMath.regularizedGammaP, moduleExports.regularizedGammaP);
  assert.equal(P.quantMath.logGamma, moduleExports.logGamma);
  // The bound distribution functions carry the NFL adapter's constants.
  assert.equal(P.quantMath.pRecOver(4.9, 3.5), moduleExports.createQuantMath({ alpha: 0.1097, k: 1.555 }).pRecOver(4.9, 3.5));
});

test('createQuantMath guards: a model-less sport (null constants) never silently fabricates numbers', () => {
  const M = loadModuleOnly();
  const bound = M.createQuantMath({ alpha: null, k: null });
  // alpha null → r = 1/null = Infinity → p = NaN → cdf = NaN → clamped by
  // Math.max/min… which PASS NaN THROUGH (max(0, NaN) is NaN). So a
  // model-less sport yields NaN — never a plausible-looking probability.
  // Same behavior the inline §22 code had; call sites are guarded by
  // NFL-only row fields (app.js §1) and never execute for such sports.
  assert.ok(Number.isNaN(bound.pRecOver(5, 3.5)));
  assert.ok(Number.isNaN(bound.pYardsOver(5, 8, 45)));
});
