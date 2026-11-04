/**
 * PropStein — Tracked-Bet Alerts (module 6).
 *
 * Rules (product charter):
 *   - Opt-in by alert type; daily cap of 3 push notifications per user.
 *   - Non-urgent updates are batched.
 *   - Every alert links to the immutable ledger entry, shows snapshot time
 *     and data source.
 *   - If freshness cannot be verified, send a STALE QUOTE state or suppress.
 *   - No urgency language, no model-derived advice before a sport gate
 *     passes — and even then, alerts stay factual.
 */

import { DAILY_PUSH_CAP } from './tokens';
import { lintCopy } from './copy-lint';
import { fmtAmerican } from './odds';
import { freshnessState } from './freshness';
import type { AlertType } from './types';

export interface AlertCandidate {
  ledgerEntryId: string;
  type: AlertType;
  /** Build the factual message. Templates live here only. */
  message: string;
  snapshotTimeUtc: string;
  sourceProvider: string;
  /** Urgent types count against the daily push cap. */
  urgent: boolean;
  batchKey?: string;
  capturedAtUtc: string | null;
}

export interface AlertDecision {
  deliver: boolean;
  reason?: 'MUTED' | 'DAILY_CAP' | 'STALE_SUPPRESSED' | 'LINT_REJECTED' | 'DISABLED_BY_PREFERENCE';
}

export interface AlertContext {
  enabledTypes: Set<AlertType>;
  mutedEntryIds: Set<string>;
  pushesSentToday: number;
  nowUtc: string;
}

/** Decide delivery for one candidate. Pure function of (candidate, context). */
export function decideAlert(candidate: AlertCandidate, ctx: AlertContext): AlertDecision {
  if (!ctx.enabledTypes.has(candidate.type)) {
    return { deliver: false, reason: 'DISABLED_BY_PREFERENCE' };
  }
  if (ctx.mutedEntryIds.has(candidate.ledgerEntryId)) {
    return { deliver: false, reason: 'MUTED' };
  }
  // Freshness gate: unverified freshness => STALE QUOTE or suppression.
  const fresh = freshnessState(candidate.capturedAtUtc, ctx.nowUtc);
  if (fresh.state === 'unknown') {
    return { deliver: false, reason: 'STALE_SUPPRESSED' };
  }
  // Copy gate: templates must be lint-clean; a violation is a build bug, fail closed.
  if (lintCopy(candidate.message).length > 0) {
    return { deliver: false, reason: 'LINT_REJECTED' };
  }
  if (candidate.urgent && ctx.pushesSentToday >= DAILY_PUSH_CAP) {
    return { deliver: false, reason: 'DAILY_CAP' };
  }
  return { deliver: true };
}

// ---------------------------------------------------------------------------
// Message templates — factual, past-tense, no instructions.
// ---------------------------------------------------------------------------

export const ALERT_TEMPLATES = {
  quoteChanged: (from: number, to: number) =>
    `Saved quote changed from ${fmtAmerican(from)} to ${fmtAmerican(to)}.`,
  quoteAged: (minutes: number) => `Saved quote is now ${minutes} minute${minutes === 1 ? '' : 's'} old.`,
  playerStatus: (from: string, to: string) => `Player status changed from ${from} to ${to}.`,
  marketSuspended: () => `Market is suspended.`,
  closingAvailable: (provider: string) => `Closing reference is now available from ${provider}.`,
  entrySettled: (status: string) => `Saved entry has settled with status ${status}.`,
  entryUnevaluable: (reason: string) =>
    `Saved entry is unevaluable because the closing reference is ${reason}.`,
} as const;

/** Types that count against the daily push cap (urgent family). */
export const URGENT_ALERT_TYPES: AlertType[] = ['player_status', 'market_suspended'];

/** Batch key for non-urgent updates (e.g., nightly digest of quote drift). */
export function batchKeyFor(type: AlertType, dayUtc: string): string | null {
  if (URGENT_ALERT_TYPES.includes(type)) return null;
  return `batch:${type}:${dayUtc.slice(0, 10)}`;
}

/**
 * Build the demo alert feed for pending entries using deterministic drift.
 * Non-urgent alerts batch into a single digest line.
 */
export function buildDemoAlerts(
  entries: {
    ledgerId: string;
    playerName: string;
    market: string;
    capturedAtUtc: string;
    enteredAmericanOdds: number;
    drift: { newAmericanOdds: number; suspended: boolean; playerStatus: string };
    nowUtc: string;
  }[],
  ctx: AlertContext,
): { delivered: AlertCandidate[]; suppressed: { ledgerId: string; reason: string }[] } {
  const delivered: AlertCandidate[] = [];
  const suppressed: { ledgerId: string; reason: string }[] = [];
  for (const e of entries) {
    const candidates: AlertCandidate[] = [];
    if (e.drift.newAmericanOdds !== e.enteredAmericanOdds) {
      candidates.push({
        ledgerEntryId: e.ledgerId,
        type: 'quote_changed',
        message: ALERT_TEMPLATES.quoteChanged(e.enteredAmericanOdds, e.drift.newAmericanOdds),
        snapshotTimeUtc: e.capturedAtUtc,
        sourceProvider: 'DEMO-CMP-A (simulated)',
        urgent: false,
        capturedAtUtc: e.capturedAtUtc,
      });
    }
    if (e.drift.playerStatus !== 'Available') {
      candidates.push({
        ledgerEntryId: e.ledgerId,
        type: 'player_status',
        message: ALERT_TEMPLATES.playerStatus('Questionable', e.drift.playerStatus),
        snapshotTimeUtc: e.capturedAtUtc,
        sourceProvider: 'DEMO-STATUS-FEED (simulated)',
        urgent: true,
        capturedAtUtc: e.capturedAtUtc,
      });
    }
    if (e.drift.suspended) {
      candidates.push({
        ledgerEntryId: e.ledgerId,
        type: 'market_suspended',
        message: ALERT_TEMPLATES.marketSuspended(),
        snapshotTimeUtc: e.capturedAtUtc,
        sourceProvider: 'DEMO-CMP-A (simulated)',
        urgent: true,
        capturedAtUtc: e.capturedAtUtc,
      });
    }
    for (const c of candidates) {
      const decision = decideAlert(c, ctx);
      if (decision.deliver) delivered.push(c);
      else suppressed.push({ ledgerId: c.ledgerEntryId, reason: decision.reason ?? 'UNKNOWN' });
    }
  }
  return { delivered, suppressed };
}
