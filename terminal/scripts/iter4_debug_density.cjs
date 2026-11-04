// Debug the pww density computation with real slate data + the frozen engine.
const fs = require('fs');
const vm = require('vm');

// Load quant-math.js in a sandbox
const ctx = { window: {}, Math, Number, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('viewer/js/quant-math.js', 'utf8'), ctx);

const rows = JSON.parse(fs.readFileSync('viewer/slate_2026_w7.json'));
const row = rows.find(r => r.player_display_name === 'Amon-Ra St. Brown');
console.log('row:', row.player_display_name, 'mu_rec:', row.mu_rec, 'mu_ypr:', row.mu_ypr, 'fair:', row.fair_line_yards, 'proj:', row.proj_yards);

const M = ctx.window.PropWireMath;
const qm = M.createQuantMath({ alpha: 0.1097, k: 1.555 });
const muRec = row.mu_rec, muYpr = row.mu_ypr;
const xHi = Math.max(40, Math.ceil(muRec * muYpr * 2.1));
const xLo = 0;
const steps = 140;
const dx = (xHi - xLo) / steps;
console.log('xHi:', xHi, 'dx:', dx.toFixed(3));

let yMax = 0;
const densities = [];
for (let i = 0; i <= steps; i++) {
  const x = xLo + i * dx;
  const a = qm.compoundYardsCdf(Math.max(0, x - dx / 2), muRec, muYpr);
  const b = qm.compoundYardsCdf(x + dx / 2, muRec, muYpr);
  const d = Math.max(0, b - a) / dx;
  densities.push(d);
  yMax = Math.max(yMax, d);
}
console.log('PDF yMax:', yMax.toFixed(5));
console.log('density @ x=100:', densities[Math.round((100 / xHi) * steps)].toFixed(5));
console.log('density @ x=113:', densities[Math.round((113 / xHi) * steps)].toFixed(5));

// CDF check
console.log('CDF(113):', qm.compoundYardsCdf(113, muRec, muYpr).toFixed(4));
console.log('pYardsOver(113):', qm.pYardsOver(muRec, muYpr, 113).toFixed(4));
