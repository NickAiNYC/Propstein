/**
 * One-shot generator: bakes the CURRENT viewer/app.js §22 numerics into
 * test/quant-math.golden.mjs fixtures. Run once before the extraction
 * (values below are the pre-extraction implementation's exact outputs).
 * Usage: node scripts/generate_quant_goldens.mjs > /tmp/goldens.json
 */
import { buildSandbox, loadApp } from '../test/helpers/sandbox.mjs';

const { sandbox } = buildSandbox();
const P = loadApp(sandbox);
const M = P.quantMath;

const ODDS = [-300, -110, -105, -100, 0, 100, 110, 150, 250, null, 'abc', ''];
const DEVIG_PAIRS = [[-110, -110], [-105, -115], [100, -120], [-220, 180], [0, 0], [null, -110]];
const REC_GRID = [];
for (const mu of [1.2, 2.5, 4.9, 5.1, 8.7]) for (const line of [0.5, 1.5, 3.5, 6.5, 10.5]) REC_GRID.push([mu, line]);
const YDS_GRID = [];
for (const [muRec, muYpr] of [[3.1, 7.4], [4.2, 8.8], [6.5, 12.1]]) for (const line of [12.5, 29.5, 55.5, 80.5, 120.5]) YDS_GRID.push([muRec, muYpr, line]);
const GAMMA_GRID = [[1, 0.5], [0.5, 1.2], [2, 3.5], [5, 12], [3, 30], [8, 0.1], [0.25, 4.75]];
const LOGGAMMA_GRID = [0.1, 0.5, 1, 2.5, 10, 142.8, 1e-3];

const out = {
  modelConstants: { alpha: P.adapter.model.alpha, k: P.adapter.model.k },
  americanToDecimal: Object.fromEntries(ODDS.map((o) => [String(o), M.americanToDecimal(o)])),
  impliedProbability: Object.fromEntries(ODDS.map((o) => [String(o), M.impliedProbability(o)])),
  devig: DEVIG_PAIRS.map(([a, b]) => M.devig(a, b)),
  pRecOver: REC_GRID.map(([mu, line]) => M.pRecOver(mu, line)),
  pYardsOver: YDS_GRID.map(([muRec, muYpr, line]) => M.pYardsOver(muRec, muYpr, line)),
  compoundYardsCdf: YDS_GRID.map(([muRec, muYpr, line]) => M.compoundYardsCdf(muRec, muYpr, line)),
  regularizedGammaP: GAMMA_GRID.map(([s, v]) => M.regularizedGammaP(s, v)),
  logGamma: LOGGAMMA_GRID.map((v) => M.logGamma(v)),
};
process.stdout.write(JSON.stringify(out, null, 2));
