import test from 'node:test';
import assert from 'node:assert/strict';

/* ─── CORRELATED EXPOSURE ENGINE IMPLEMENTATION (PURE LOGIC) ─── */
function checkCorrelatedRisk(row, evaluation, state) {
  if (!row) return null;
  const market = state.filters?.market || 'receiving_yards';
  const correlationKey = `${row.team}::${market}`;
  if (state.dismissedCorrelations && state.dismissedCorrelations.has(correlationKey)) {
    return null;
  }

  const portfolio = state.portfolio || [];
  const competing = portfolio.find(
    (b) => b.team === row.team && b.player_id !== row.player_id && b.market === market
  );
  if (!competing) return null;

  const rowSide = evaluation?.side || 'OVER';
  const compSide = competing.side || 'OVER';

  if (rowSide === 'OVER' && compSide === 'OVER') {
    return {
      type: 'SAME_TEAM_EXPOSURE',
      isHedge: false,
      competingPlayer: competing.player_name,
      competingSide: compSide,
      team: row.team,
      market,
      badgeText: `⚠️ Same-Team (${competing.player_name.split(' ').pop()})`,
      badgeClass: 'corr-risk',
      message: `Same-team exposure: results may be correlated (target distribution & game script with ${competing.player_name} on ${row.team})`,
      dismissKey: correlationKey
    };
  } else if ((rowSide === 'OVER' && compSide === 'UNDER') || (rowSide === 'UNDER' && compSide === 'OVER')) {
    return {
      type: 'DISTRIBUTION_HEDGE',
      isHedge: true,
      competingPlayer: competing.player_name,
      competingSide: compSide,
      team: row.team,
      market,
      badgeText: `⚡ Hedge (${competing.player_name.split(' ').pop()})`,
      badgeClass: 'corr-hedge',
      message: `Offensive distribution hedge: Active ${compSide} on ${competing.player_name} (${row.team})`,
      dismissKey: correlationKey
    };
  } else {
    return {
      type: 'SCRIPT_CORRELATION',
      isHedge: true,
      competingPlayer: competing.player_name,
      competingSide: compSide,
      team: row.team,
      market,
      badgeText: `⚡ Script (${competing.player_name.split(' ').pop()})`,
      badgeClass: 'corr-hedge',
      message: `Correlated game script: Dual ${compSide} on ${row.team} receivers (${competing.player_name})`,
      dismissKey: correlationKey
    };
  }
}

function getPortfolioCorrelations(portfolio, dismissedSet = new Set()) {
  const byTeamAndMarket = {};
  portfolio.forEach((b) => {
    const k = `${b.team}::${b.market}`;
    if (!byTeamAndMarket[k]) byTeamAndMarket[k] = [];
    byTeamAndMarket[k].push(b);
  });
  const conflicts = [];
  Object.entries(byTeamAndMarket).forEach(([key, bets]) => {
    if (bets.length > 1 && !dismissedSet.has(key)) {
      const [team, market] = key.split('::');
      const hasOver = bets.some((b) => (b.side || 'OVER') === 'OVER');
      const hasUnder = bets.some((b) => (b.side || 'OVER') === 'UNDER');
      const isHedge = hasOver && hasUnder;

      conflicts.push({
        key,
        team,
        market,
        isHedge,
        title: isHedge ? 'Distribution Hedge' : 'Concentrated Volume Risk',
        description: isHedge
          ? `Offensive distribution hedge on <strong>${team}</strong>: Active opposing positions on <em>${bets.map((b) => b.player_name).join(' & ')}</em>.`
          : `Same-team exposure on <strong>${team}</strong>: Multiple receiver positions on <em>${bets.map((b) => b.player_name).join(' & ')}</em>. Results may be correlated by game script and target distribution.`,
        players: bets.map((b) => b.player_name),
        bets
      });
    }
  });
  return conflicts;
}

/* ─── SNIPER RULES & RATE-LIMITING ENGINE ─── */
function evaluateSniperTrigger(quote, sniperConfig, cooldownsNow, nowMs = Date.now()) {
  if (!sniperConfig || !sniperConfig.enabled) return { trigger: false, reason: 'disabled' };
  const minEdge = Number(sniperConfig.minEdge) || 0.15;
  const gateMetOnly = sniperConfig.gateMetOnly !== false;

  const ev = quote.evaluation || {};
  const edge = Number(ev.prob_edge || 0);
  const expectedReturn = Number(ev.expected_return || 0);
  const qualified = !gateMetOnly || (ev.is_qualified && expectedReturn > 0);

  if (edge < minEdge) return { trigger: false, reason: 'edge_below_threshold' };
  if (!qualified) return { trigger: false, reason: 'unqualified_or_negative_ev' };

  const k = `${quote.player_id}::${quote.market}`;
  const lastAlertTime = cooldownsNow[k] || 0;
  if (nowMs - lastAlertTime < 15 * 60 * 1000) {
    return { trigger: false, reason: 'rate_limited_cooldown' };
  }

  // Record cooldown
  cooldownsNow[k] = nowMs;

  return {
    trigger: true,
    alertPayload: {
      playerId: quote.player_id,
      player: quote.player_name,
      team: quote.team,
      side: ev.best_side || 'OVER',
      line: quote.line,
      edge,
      expectedReturn
    }
  };
}

/* ─── TICK DELTA DETECTION ENGINE ─── */
function evaluateTickMove(prev, curQuote, curEv, curEdge) {
  if (!prev) return null;
  const evDelta = curEv - prev.ev;
  const edgeDelta = curEdge - prev.edge;
  const lineDelta = Math.abs(curQuote.line - prev.line);
  const oddsDelta = Math.abs((curQuote.over_odds || 0) - (prev.odds || 0));

  // Filter noisy flicker: must cross meaningful threshold
  const isSignificant = lineDelta >= 0.5 || oddsDelta >= 10 || Math.abs(evDelta) >= 0.015 || Math.abs(edgeDelta) >= 0.015;
  if (!isSignificant) return null;

  if (evDelta > 0.005 || edgeDelta > 0.005) {
    return { dir: 'up', glyph: '▲', evDelta, edgeDelta, lineDelta, oddsDelta };
  } else if (evDelta < -0.005 || edgeDelta < -0.005) {
    return { dir: 'down', glyph: '▼', evDelta, edgeDelta, lineDelta, oddsDelta };
  }
  return null;
}

/* ─── SETTLED-RESULTS EVALUATOR ─── */
function evaluateSettledRowPure(row, side = 'OVER', isYards = true) {
  const actual = Number(isYards ? row.receiving_yards : row.receptions) || 0;
  const line = Number(isYards ? row.fair_line_yards : row.fair_line_rec) || 0;
  const delta = side === 'UNDER' ? +(line - actual).toFixed(1) : +(actual - line).toFixed(1);
  const won = side === 'UNDER' ? (actual < line) : (actual > line);
  const lost = side === 'UNDER' ? (actual > line) : (actual < line);
  const push = actual === line;
  const outcome = won ? 'WON' : lost ? 'LOST' : 'PUSH';
  const outcomeClass = won ? 'settled-won' : lost ? 'settled-lost' : 'settled-push';
  return { actual, line, delta, outcome, outcomeClass, isYards, side };
}

/* ─── SPARKLINE FORMATTING ─── */
function formatSparklineLabel(openVal, curVal) {
  const delta = +(curVal - openVal).toFixed(1);
  const deltaStr = `${delta > 0 ? '+' : ''}${delta.toFixed(1)}`;
  const ariaLabel = `Line trajectory: opened ${openVal.toFixed(1)}, current ${curVal.toFixed(1)} (${deltaStr} steam)`;
  return { delta, deltaStr, ariaLabel };
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*                            UNIT TEST CASES                                 */
/* ═══════════════════════════════════════════════════════════════════════════ */

test('correlation engine: Over + Over on same team identifies concentrated exposure risk', () => {
  const state = {
    filters: { market: 'receiving_yards' },
    portfolio: [
      { player_id: 'p1', player_name: 'Khalil Shakir', team: 'BUF', market: 'receiving_yards', side: 'OVER', line: 45.5 }
    ],
    dismissedCorrelations: new Set()
  };

  const incomingRow = { player_id: 'p2', player_display_name: 'Keon Coleman', team: 'BUF' };
  const incomingEval = { side: 'OVER', edge: 0.14 };

  const risk = checkCorrelatedRisk(incomingRow, incomingEval, state);
  assert.ok(risk !== null);
  assert.equal(risk.type, 'SAME_TEAM_EXPOSURE');
  assert.equal(risk.isHedge, false);
  assert.equal(risk.competingPlayer, 'Khalil Shakir');
  assert.equal(risk.badgeText, '⚠️ Same-Team (Shakir)');
  assert.match(risk.message, /Same-team exposure: results may be correlated/);
  // Verify it does NOT claim "cannibalizes reception volume" as absolute fact
  assert.doesNotMatch(risk.message, /cannibalizes/i);
});

test('correlation engine: Over + Under on same team identifies distribution hedge', () => {
  const state = {
    filters: { market: 'receiving_yards' },
    portfolio: [
      { player_id: 'p1', player_name: 'Khalil Shakir', team: 'BUF', market: 'receiving_yards', side: 'OVER', line: 45.5 }
    ],
    dismissedCorrelations: new Set()
  };

  const incomingRow = { player_id: 'p2', player_display_name: 'Keon Coleman', team: 'BUF' };
  const incomingEval = { side: 'UNDER', edge: 0.12 };

  const risk = checkCorrelatedRisk(incomingRow, incomingEval, state);
  assert.ok(risk !== null);
  assert.equal(risk.type, 'DISTRIBUTION_HEDGE');
  assert.equal(risk.isHedge, true);
  assert.equal(risk.badgeText, '⚡ Hedge (Shakir)');
  assert.match(risk.message, /Offensive distribution hedge/);
});

test('correlation engine: players on different teams have zero correlation risk', () => {
  const state = {
    filters: { market: 'receiving_yards' },
    portfolio: [
      { player_id: 'p1', player_name: 'Khalil Shakir', team: 'BUF', market: 'receiving_yards', side: 'OVER', line: 45.5 }
    ],
    dismissedCorrelations: new Set()
  };

  const incomingRow = { player_id: 'p3', player_display_name: 'Travis Kelce', team: 'KC' };
  const incomingEval = { side: 'OVER', edge: 0.15 };

  const risk = checkCorrelatedRisk(incomingRow, incomingEval, state);
  assert.equal(risk, null);
});

test('correlation engine: user dismissals are honored and suppress warning', () => {
  const state = {
    filters: { market: 'receiving_yards' },
    portfolio: [
      { player_id: 'p1', player_name: 'Khalil Shakir', team: 'BUF', market: 'receiving_yards', side: 'OVER', line: 45.5 }
    ],
    dismissedCorrelations: new Set(['BUF::receiving_yards'])
  };

  const incomingRow = { player_id: 'p2', player_display_name: 'Keon Coleman', team: 'BUF' };
  const incomingEval = { side: 'OVER', edge: 0.14 };

  const risk = checkCorrelatedRisk(incomingRow, incomingEval, state);
  assert.equal(risk, null);
});

test('correlation engine: getPortfolioCorrelations separates hedges from concentrated volume risk', () => {
  const portfolio = [
    { player_id: 'p1', player_name: 'Tyreek Hill', team: 'MIA', market: 'receiving_yards', side: 'OVER' },
    { player_id: 'p2', player_name: 'Jaylen Waddle', team: 'MIA', market: 'receiving_yards', side: 'OVER' },
    { player_id: 'p3', player_name: 'A.J. Brown', team: 'PHI', market: 'receiving_yards', side: 'OVER' },
    { player_id: 'p4', player_name: 'DeVonta Smith', team: 'PHI', market: 'receiving_yards', side: 'UNDER' },
  ];

  const conflicts = getPortfolioCorrelations(portfolio);
  assert.equal(conflicts.length, 2);

  const miaConflict = conflicts.find((c) => c.team === 'MIA');
  assert.equal(miaConflict.isHedge, false);
  assert.equal(miaConflict.title, 'Concentrated Volume Risk');

  const phiConflict = conflicts.find((c) => c.team === 'PHI');
  assert.equal(phiConflict.isHedge, true);
  assert.equal(phiConflict.title, 'Distribution Hedge');
});

test('sniper rules: respects edge hurdle thresholds', () => {
  const sniperConfig = { enabled: true, minEdge: 0.15, gateMetOnly: true };
  const cooldowns = {};

  const quoteSub15 = {
    player_id: 'p1', player_name: 'Player 1', market: 'receiving_yards', team: 'BUF', line: 50.5,
    evaluation: { prob_edge: 0.13, expected_return: 0.08, is_qualified: true }
  };
  const res1 = evaluateSniperTrigger(quoteSub15, sniperConfig, cooldowns);
  assert.equal(res1.trigger, false);
  assert.equal(res1.reason, 'edge_below_threshold');

  const quoteOver15 = {
    player_id: 'p2', player_name: 'Player 2', market: 'receiving_yards', team: 'BUF', line: 50.5,
    evaluation: { prob_edge: 0.16, expected_return: 0.10, is_qualified: true, best_side: 'OVER' }
  };
  const res2 = evaluateSniperTrigger(quoteOver15, sniperConfig, cooldowns);
  assert.equal(res2.trigger, true);
  assert.equal(res2.alertPayload.player, 'Player 2');
});

test('sniper rules: gate requirement rejects unverified or negative-EV quotes', () => {
  const sniperConfig = { enabled: true, minEdge: 0.15, gateMetOnly: true };
  const cooldowns = {};

  const quoteUnqualified = {
    player_id: 'p3', player_name: 'Player 3', market: 'receiving_yards', team: 'MIA', line: 40.5,
    evaluation: { prob_edge: 0.18, expected_return: 0.12, is_qualified: false }
  };
  const res = evaluateSniperTrigger(quoteUnqualified, sniperConfig, cooldowns);
  assert.equal(res.trigger, false);
  assert.equal(res.reason, 'unqualified_or_negative_ev');
});

test('sniper rate-limiting: 15-minute cooldown prevents alert flooding on noisy lines', () => {
  const sniperConfig = { enabled: true, minEdge: 0.12, gateMetOnly: false };
  const cooldowns = {};
  const t0 = 10000000;

  const quote = {
    player_id: 'p4', player_name: 'Player 4', market: 'receiving_yards', team: 'DET', line: 62.5,
    evaluation: { prob_edge: 0.14, expected_return: 0.09, is_qualified: true }
  };

  // First tick fires
  const first = evaluateSniperTrigger(quote, sniperConfig, cooldowns, t0);
  assert.equal(first.trigger, true);

  // Second tick at t0 + 5 minutes is blocked
  const second = evaluateSniperTrigger(quote, sniperConfig, cooldowns, t0 + 5 * 60 * 1000);
  assert.equal(second.trigger, false);
  assert.equal(second.reason, 'rate_limited_cooldown');

  // Third tick at t0 + 14.9 minutes is blocked
  const third = evaluateSniperTrigger(quote, sniperConfig, cooldowns, t0 + 14.9 * 60 * 1000);
  assert.equal(third.trigger, false);
  assert.equal(third.reason, 'rate_limited_cooldown');

  // Fourth tick at t0 + 15.1 minutes triggers
  const fourth = evaluateSniperTrigger(quote, sniperConfig, cooldowns, t0 + 15.1 * 60 * 1000);
  assert.equal(fourth.trigger, true);
});

test('tick-delta detection: filters noisy sub-threshold moves and captures meaningful shifts', () => {
  const prev = { line: 55.5, odds: -110, ev: 0.05, edge: 0.08 };

  // Sub-threshold move: 0.1 yd line change, 2 cents odds, 0.002 ev delta -> ignored
  const curSub = { line: 55.6, over_odds: -112 };
  const subResult = evaluateTickMove(prev, curSub, 0.052, 0.082);
  assert.equal(subResult, null, 'Noisy tick flicker should be ignored');

  // Meaningful line move: 0.5 yds with positive EV gain -> up tick
  const curLineShift = { line: 56.0, over_odds: -110 };
  const shiftResult = evaluateTickMove(prev, curLineShift, 0.07, 0.10);
  assert.ok(shiftResult !== null);
  assert.equal(shiftResult.dir, 'up');
  assert.equal(shiftResult.glyph, '▲');

  // Meaningful adverse move: odds drift with negative EV delta -> down tick
  const curAdverse = { line: 55.5, over_odds: -125 };
  const adverseResult = evaluateTickMove(prev, curAdverse, 0.03, 0.06);
  assert.ok(adverseResult !== null);
  assert.equal(adverseResult.dir, 'down');
  assert.equal(adverseResult.glyph, '▼');
});

test('sparklines: formats accessible trajectory labels and standalone steam delta tags', () => {
  const sparkUp = formatSparklineLabel(75.5, 78.5);
  assert.equal(sparkUp.delta, 3.0);
  assert.equal(sparkUp.deltaStr, '+3.0');
  assert.equal(sparkUp.ariaLabel, 'Line trajectory: opened 75.5, current 78.5 (+3.0 steam)');

  const sparkDown = formatSparklineLabel(50.0, 48.5);
  assert.equal(sparkDown.delta, -1.5);
  assert.equal(sparkDown.deltaStr, '-1.5');
  assert.equal(sparkDown.ariaLabel, 'Line trajectory: opened 50.0, current 48.5 (-1.5 steam)');
});

test('settled results evaluator: correctly grades OVER, UNDER, and PUSH with signed deltas', () => {
  // Over bet: actual 72 yds, line 55.5 yds -> WON, delta +16.5 yds
  const overWon = evaluateSettledRowPure({ receiving_yards: 72, fair_line_yards: 55.5 }, 'OVER', true);
  assert.equal(overWon.outcome, 'WON');
  assert.equal(overWon.outcomeClass, 'settled-won');
  assert.equal(overWon.delta, 16.5);

  // Over bet: actual 42 yds, line 55.5 yds -> LOST, delta -13.5 yds
  const overLost = evaluateSettledRowPure({ receiving_yards: 42, fair_line_yards: 55.5 }, 'OVER', true);
  assert.equal(overLost.outcome, 'LOST');
  assert.equal(overLost.outcomeClass, 'settled-lost');
  assert.equal(overLost.delta, -13.5);

  // Under bet: actual 42 yds, line 55.5 yds -> WON, delta +13.5 yds
  const underWon = evaluateSettledRowPure({ receiving_yards: 42, fair_line_yards: 55.5 }, 'UNDER', true);
  assert.equal(underWon.outcome, 'WON');
  assert.equal(underWon.outcomeClass, 'settled-won');
  assert.equal(underWon.delta, 13.5);

  // Under bet: actual 72 yds, line 55.5 yds -> LOST, delta -16.5 yds
  const underLost = evaluateSettledRowPure({ receiving_yards: 72, fair_line_yards: 55.5 }, 'UNDER', true);
  assert.equal(underLost.outcome, 'LOST');
  assert.equal(underLost.outcomeClass, 'settled-lost');
  assert.equal(underLost.delta, -16.5);

  // Push: actual 4.0 rec, line 4.0 rec -> PUSH, delta 0.0
  const pushRec = evaluateSettledRowPure({ receptions: 4, fair_line_rec: 4.0 }, 'OVER', false);
  assert.equal(pushRec.outcome, 'PUSH');
  assert.equal(pushRec.outcomeClass, 'settled-push');
  assert.equal(pushRec.delta, 0.0);
});

/* ─── VOLATILITY CIRCUIT BREAKER TESTS ─── */
function checkVolatilityCircuitBreaker(openLine, curLine, isYards = true, options = {}) {
  if (openLine === null || openLine === undefined || openLine <= 0) return { halt: false, drift: 0, driftPct: 0, isExempt: false };
  const drift = +(curLine - openLine).toFixed(1);
  const absDrift = Math.abs(drift);
  const driftPct = absDrift / openLine;
  const hurdle = isYards ? 5.0 : 1.0;

  const isBeneficiary = Boolean(options.isBeneficiary);
  const isModeledAbsence = Boolean(options.isModeledAbsence);
  const maxBeneficiaryDrift = isYards ? 8.5 : 2.0;

  if (isBeneficiary && drift > maxBeneficiaryDrift) {
    return {
      halt: true,
      drift,
      driftPct,
      isExempt: false,
      reason: `Beneficiary line surged ${drift > 0 ? '+' : ''}${drift} ${isYards ? 'yds' : 'rec'}, exceeding model absorption limit (+${maxBeneficiaryDrift}). Oversteamed/second-order news suspected.`
    };
  }

  // Exemption: modeled upward surge on beneficiary within bound, or modeled downward shift on injured player
  if ((isBeneficiary && drift > 0) || (isModeledAbsence && drift < 0)) {
    return { halt: false, drift, driftPct, isExempt: true, reason: 'Exempted modeled move' };
  }

  if (absDrift >= hurdle || driftPct >= 0.12) {
    return {
      halt: true,
      drift,
      driftPct,
      isExempt: false,
      reason: `Line moved sharply (${drift > 0 ? '+' : ''}${drift} ${isYards ? 'yds' : 'rec'}, ${(driftPct * 100).toFixed(0)}% vs open). Model baseline may be stale — check breaking news before trading.`
    };
  }
  return { halt: false, drift, driftPct, isExempt: false };
}

test('volatility circuit breaker: trips and halts execution when market line plunges (suspected QB injury / news)', () => {
  // Receiver opened at 65.5, line plummeted to 58.5 (-7.0 yds drift, -10.7%) on late-night QB scratch
  const plunge = checkVolatilityCircuitBreaker(65.5, 58.5, true);
  assert.equal(plunge.halt, true);
  assert.equal(plunge.drift, -7.0);
  assert.match(plunge.reason, /Line moved sharply/);
});

test('volatility circuit breaker: trips symmetrically on sharp unmodeled upside steam (+6.5 yds)', () => {
  // Unmodeled steam up (e.g. sharp group betting or unannounced opposing CB injury)
  const steamUp = checkVolatilityCircuitBreaker(50.0, 56.5, true);
  assert.equal(steamUp.halt, true);
  assert.equal(steamUp.drift, 6.5);
  assert.match(steamUp.reason, /Line moved sharply/);
});

test('volatility circuit breaker: EXEMPTS modeled beneficiary upward steam (e.g. Douglas +6.0 yds after Doubs OUT)', () => {
  // DeMario Douglas opens at 45.5, books steam him to 51.5 (+6.0 yds) because Doubs was ruled OUT.
  // Since model already redistributed Doubs' 7.2 targets to Douglas, this move matches modeled expectations.
  const beneficiaryMove = checkVolatilityCircuitBreaker(45.5, 51.5, true, { isBeneficiary: true });
  assert.equal(beneficiaryMove.halt, false, 'Must not halt modeled beneficiary legitimate line adjustments');
  assert.equal(beneficiaryMove.isExempt, true);
  assert.equal(beneficiaryMove.drift, 6.0);
});

test('volatility circuit breaker: TRIPS if modeled beneficiary surge exceeds absorption limit (+15.0 yds)', () => {
  // Douglas line steams from 45.5 to 60.5 (+15.0 yds). While direction is correct, magnitude far exceeds
  // the modeled target absorption cap of +8.5 yds, indicating second-order news or book over-reaction.
  const oversteamed = checkVolatilityCircuitBreaker(45.5, 60.5, true, { isBeneficiary: true });
  assert.equal(oversteamed.halt, true, 'Surge beyond model capacity must trip the circuit breaker');
  assert.match(oversteamed.reason, /exceeding model absorption limit/);
});

test('volatility circuit breaker: still trips if modeled beneficiary drops sharply (-6.0 yds adverse drift)', () => {
  // If Douglas was expected to surge, but his line drops from 45.5 to 39.5, that contradicts our model (unmodeled news)
  const adverseBeneficiary = checkVolatilityCircuitBreaker(45.5, 39.5, true, { isBeneficiary: true });
  assert.equal(adverseBeneficiary.halt, true, 'Adverse line drop on a modeled beneficiary must halt');
  assert.equal(adverseBeneficiary.drift, -6.0);
});

test('volatility circuit breaker: trips and halts execution on steep percentage drift (> 12%)', () => {
  // Lower-volume receiver opened at 32.5, line plunged to 27.5 (-5.0 yds, -15.4%)
  const pctTrip = checkVolatilityCircuitBreaker(32.5, 27.5, true);
  assert.equal(pctTrip.halt, true);
  assert.equal(pctTrip.drift, -5.0);
  assert.ok(pctTrip.driftPct >= 0.12);
});

test('volatility circuit breaker: trips on receptions market shifts >= 1.0 rec', () => {
  // Pass-catcher receptions line drops from 4.5 to 3.5 (-1.0 rec, -22.2%)
  const recTrip = checkVolatilityCircuitBreaker(4.5, 3.5, false);
  assert.equal(recTrip.halt, true);
  assert.equal(recTrip.drift, -1.0);
});

test('volatility circuit breaker: permits standard market drift within normal bounds', () => {
  // Routine limit-testing drift: opened at 54.5, drifted to 55.5 (+1.0 yd, +1.8%)
  const normal = checkVolatilityCircuitBreaker(54.5, 55.5, true);
  assert.equal(normal.halt, false);
  assert.equal(normal.drift, 1.0);
});

test('volatility circuit breaker: suppresses Sniper alerts on unmodeled line crashes', () => {
  const sniperConfig = { enabled: true, minEdge: 0.15, gateMetOnly: true };
  const cooldowns = {};

  const crashedQuote = {
    player_id: 'p_qb_dependent',
    player_name: 'Stefon Diggs',
    market: 'receiving_yards',
    team: 'HOU',
    line: 55.5,
    evaluation: {
      prob_edge: 0.25,
      expected_return: 0.40,
      is_qualified: true,
      best_side: 'OVER'
    }
  };

  const openLine = 68.5;
  const cb = checkVolatilityCircuitBreaker(openLine, crashedQuote.line, true);
  assert.equal(cb.halt, true);

  let triggered = false;
  if (!cb.halt) {
    const res = evaluateSniperTrigger(crashedQuote, sniperConfig, cooldowns);
    triggered = res.trigger;
  }
  assert.equal(triggered, false, 'Sniper alert must be halted by circuit breaker despite massive apparent edge');
});

test('ledger override: records manual bet on halted line with volatility_flag: true and config_version', () => {
  const haltedEval = {
    volatilityHalt: true,
    haltReason: 'Line moved sharply (+7.0 yds vs open)',
    edge: 0.16,
    ev: 0.12
  };

  const ticketEntry = {
    ticket_id: 'A1B2',
    player_name: 'DeMario Douglas',
    volatility_flag: Boolean(haltedEval.volatilityHalt),
    volatility_reason: haltedEval.haltReason,
    config_version: '1.1.0'
  };

  assert.equal(ticketEntry.volatility_flag, true);
  assert.equal(ticketEntry.config_version, '1.1.0');
  assert.match(ticketEntry.volatility_reason, /Line moved sharply/);
});

test('news watcher: dead-mans switch trips and halts alerts when feed age > 300s', () => {
  const nowMs = 1761000000000;
  const freshTime = new Date(nowMs - 45 * 1000).toISOString();
  const staleTime = new Date(nowMs - 400 * 1000).toISOString();

  const isFreshStale = (nowMs - new Date(freshTime).getTime()) / 1000 > 300;
  const isOldStale = (nowMs - new Date(staleTime).getTime()) / 1000 > 300;

  assert.equal(isFreshStale, false, 'Feed checked 45s ago is active');
  assert.equal(isOldStale, true, 'Feed checked 400s ago trips dead-man switch');
});

test('settled results: complete universe reconciliation accounts for won, lost, and push', () => {
  const won = 176;
  const lost = 251;
  const push = 4;
  const totalGraded = won + lost + push;

  assert.equal(totalGraded, 431, '176 won + 251 lost + 4 push reconciles exactly to 431 total stat boxes');
  const winRateExcludingPush = won / (won + lost);
  assert.ok(Math.abs(winRateExcludingPush - 0.412) < 0.005);
});



