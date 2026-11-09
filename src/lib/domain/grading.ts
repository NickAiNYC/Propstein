/**
 * PropStein — Grader (module 4, evaluation half).
 *
 * CLV definition (preregistered interpretation note):
 *
 *   The governing formula sheet writes CLV_i = p_fair(entry, side) −
 *   p_fair(close, side). Read literally, that sign convention makes "beating
 *   the close" negative, which contradicts the sheet's own gate semantics
 *   ("mean price CLV at least +1.0 pp", "percentage of entries beating
 *   close", "positive descriptive CLV"). The implemented, preregistered
 *   convention is therefore the standard one:
 *
 *       CLV_i = p_fair(close, side) − p_fair(entry, side)
 *
 *   positive = the entry price was superior to the closing reference price
 *   ("beat the close"). Two-way proportional de-vig is applied identically at
 *   entry and at close. Model-versus-close probability difference is a
 *   diagnostic only and is never presented as CLV.
 *
 * Exclusions are retained with reason codes and are NEVER counted as losses
 * or zeros.
 */

import { fairProbabilityForSide } from './odds';
import { oddsBand } from './odds';
import type { ClvOutcome, ExclusionReason } from './types';
import type { LedgerEntryRecord } from './ledger';

export interface GradingClosingInfo {
  quality: 'fresh' | 'stale' | 'missing' | 'conflicting';
  fairProbability: number | null;
  independenceVerified: boolean;
  provider: string | null;
}

export interface GradingSettlementInfo {
  status: 'pending' | 'settled' | 'void' | 'canceled' | 'push' | 'dnp';
  result: 'win' | 'loss' | 'push' | 'void' | null;
}

/**
 * Price CLV in percentage points for one entry. Returns null with a reason
 * code when the entry is unevaluable — never a silent zero.
 */
export function priceClvPp(
  entry: Pick<
    LedgerEntryRecord,
    'selection' | 'enteredAmericanOdds' | 'enteredCounterpartOdds'
  >,
  closing: GradingClosingInfo,
): { clvPp: number | null; reason: ExclusionReason | null } {
  if (closing.quality === 'missing' || closing.fairProbability === null) {
    return { clvPp: null, reason: 'MISSING_CLOSE' };
  }
  if (closing.quality === 'stale') {
    return { clvPp: null, reason: 'STALE_CLOSE' };
  }
  if (closing.quality === 'conflicting') {
    return { clvPp: null, reason: 'CONFLICTING_CLOSE' };
  }
  if (!closing.independenceVerified) {
    return { clvPp: null, reason: 'NOT_INDEPENDENT_CLOSE' };
  }
  const entryFair = fairProbabilityForSide(
    entry.enteredAmericanOdds,
    entry.enteredCounterpartOdds,
    entry.selection,
  );
  const clvPp = (closing.fairProbability - entryFair) * 100;
  return { clvPp: Number(clvPp.toFixed(3)), reason: null };
}

/**
 * Two independent closing sources must agree within the preregistered
 * tolerance (percentage points of implied probability), otherwise the close
 * is CONFLICTING and the entry becomes unevaluable — never silently resolved.
 */
export function closingQualityFromSources(
  primaryImplied: number | null,
  secondaryImplied: number | null,
  tolerancePp: number,
): 'fresh' | 'conflicting' {
  if (primaryImplied === null || secondaryImplied === null) return 'fresh';
  return Math.abs(primaryImplied - secondaryImplied) * 100 > tolerancePp ? 'conflicting' : 'fresh';
}

/**
 * Full grading outcome for one ledger entry: exclusion first, evaluation
 * second. Duplicates and correlation are flags evaluated by the caller with
 * the ledger context.
 */
export function gradeEntry(
  entry: LedgerEntryRecord,
  closing: GradingClosingInfo | null,
  settlement: GradingSettlementInfo | null,
  flags: { duplicate: boolean; correlatedExcluded: boolean } = { duplicate: false, correlatedExcluded: false },
): ClvOutcome {
  let reasonCode: ExclusionReason | null = null;
  let evaluable = false;
  let clvPp: number | null = null;

  if (flags.duplicate) {
    reasonCode = 'DUPLICATE';
  } else if (flags.correlatedExcluded) {
    reasonCode = 'CORRELATED';
  } else if (!settlement || settlement.status === 'pending') {
    reasonCode = 'UNSETTLED';
  } else if (settlement.status === 'push') {
    reasonCode = 'PUSH';
  } else if (settlement.status === 'void') {
    reasonCode = 'VOID';
  } else if (settlement.status === 'canceled') {
    reasonCode = 'CANCELED';
  } else if (settlement.status === 'dnp') {
    reasonCode = 'DNP';
  } else if (!closing) {
    reasonCode = 'MISSING_CLOSE';
  } else {
    const r = priceClvPp(entry, closing);
    reasonCode = r.reason;
    clvPp = r.clvPp;
    evaluable = r.reason === null;
  }

  return {
    ledgerId: entry.ledgerId,
    sport: entry.sport,
    gameClusterId: entry.gameClusterId,
    market: entry.market,
    modelVersion: entry.modelVersion,
    entrySource: entry.sourceType,
    oddsBand: oddsBand(entry.enteredAmericanOdds),
    clvPp,
    evaluable,
    reasonCode,
    beatClose: evaluable ? (clvPp as number) > 0 : null,
    modelProbability: entry.modelProbability,
    modelCalibrated: entry.modelCoverage === 'calibrated',
    result: settlement?.result ?? null,
  };
}

/**
 * Apply the correlation policy to a list of graded outcomes:
 * within each correlation group only the earliest recorded entry remains a
 * qualifying signal; the others are excluded with reason CORRELATED. Game
 * cluster ids on retained rows are untouched, so cluster dependence is
 * preserved for the bootstrap.
 */
export function applyCorrelationPolicy<T extends { ledgerId: string; correlationGroup: string | null; recordedAtUtc: string }>(
  rows: T[],
): Map<string, 'retain' | 'correlated'> {
  const byGroup = new Map<string, T[]>();
  for (const row of rows) {
    if (!row.correlationGroup) continue;
    const list = byGroup.get(row.correlationGroup) ?? [];
    list.push(row);
    byGroup.set(row.correlationGroup, list);
  }
  const decisions = new Map<string, 'retain' | 'correlated'>();
  for (const row of rows) decisions.set(row.ledgerId, 'retain');
  for (const [, list] of byGroup) {
    const sorted = [...list].sort((a, b) => (a.recordedAtUtc < b.recordedAtUtc ? -1 : 1));
    for (let i = 1; i < sorted.length; i++) {
      decisions.set(sorted[i].ledgerId, 'correlated');
    }
  }
  return decisions;
}
