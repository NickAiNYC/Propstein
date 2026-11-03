#!/usr/bin/env node
// Diagnostic probe: which empty-state branch fires in the parity sandbox,
// and why. Run: node scripts/probe_parity_branch.mjs
process.env.TZ = 'America/New_York';
import { buildSandbox, loadApp, attachSyntheticQuote } from '../test/helpers/sandbox.mjs';

const { sandbox, registry } = buildSandbox();
const P = loadApp(sandbox);
await P.loadSlate('2026_w7');
const synth = attachSyntheticQuote(P);

console.log('feedHealth          =', JSON.stringify(P.state.feedHealth));
const hs = P.feedHealthStates();
console.log('oddsFreshness       =', hs.oddsFreshness, '| newsFreshness =', hs.newsFreshness);
console.log('oddsAgeSeconds      =', hs.oddsAgeSeconds, '(limit', hs.thresholds.oddsStaleSeconds, ')');
console.log('dataKind            =', hs.dataKind);
console.log('default playMode    =', P.state.filters.playMode);
console.log('quotes length       =', (P.state.odds.quotes || []).length);
P.renderBoard();
const empty = registry.get('#emptyState');
console.log('--- after boot+synthetic (default actionable mode) ---');
console.log('paused?             =', empty.innerHTML.includes('Live qualification paused'));
console.log('anti-tout?          =', empty.innerHTML.includes('0 Qualified Plays Today'));
console.log('no-match?           =', empty.innerHTML.includes('No Matching Records'));
console.log('hidden?             =', empty.hidden);

// Replicate the parity harness's dumpRender for table/receptions:
P.state.filters.market = 'receptions';
P.setView('table');
P.renderAll();
const empty2 = registry.get('#emptyState');
console.log('--- after dumpRender(table, receptions) ---');
console.log('paused?             =', empty2.innerHTML.includes('Live qualification paused'));
console.log('anti-tout?          =', empty2.innerHTML.includes('0 Qualified Plays Today'));
console.log('new CTA present?    =', empty2.innerHTML.includes('View 390 Research Projections'));
console.log('hidden?             =', empty2.hidden);
const hs2 = P.feedHealthStates();
console.log('freshness now       =', hs2.oddsFreshness, '| dataKind =', hs2.dataKind);
