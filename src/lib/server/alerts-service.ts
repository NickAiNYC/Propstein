/**
 * PropStein — alerts service: preferences, feed, and the on-demand evaluation
 * worker (in production this is a background worker; the reference
 * deployment evaluates on request for demo purposes).
 */

import { db } from '@/lib/db';
import { buildDemoAlerts, decideAlert, ALERT_TEMPLATES } from '@/lib/domain/alerts';
import { marketDrift } from '@/lib/domain/sim-market';
import { DAILY_PUSH_CAP } from '@/lib/domain/tokens';
import { isoUtc } from '@/lib/domain/determinism';
import type { AlertType } from '@/lib/domain/types';

export const ALL_ALERT_TYPES: AlertType[] = [
  'quote_changed',
  'quote_aged',
  'player_status',
  'market_suspended',
  'closing_available',
  'entry_settled',
  'entry_unevaluable',
];

export async function getPreferences(userId: string) {
  const rows = await db.alertPreference.findMany({ where: { userId } });
  const map = new Map(rows.map((r) => [r.alertType, r.enabled]));
  return ALL_ALERT_TYPES.map((t) => ({ type: t, enabled: map.get(t) ?? true }));
}

export async function setPreferences(userId: string, enabled: Record<string, boolean>) {
  for (const [type, on] of Object.entries(enabled)) {
    if (!ALL_ALERT_TYPES.includes(type as AlertType)) continue;
    await db.alertPreference.upsert({
      where: { userId_alertType: { userId, alertType: type } },
      create: { userId, alertType: type, enabled: Boolean(on) },
      update: { enabled: Boolean(on) },
    });
  }
  return getPreferences(userId);
}

export async function getFeed(userId: string) {
  const rows = await db.alertEvent.findMany({
    where: { userId },
    orderBy: { createdAtUtc: 'desc' },
    take: 60,
  });
  return rows.map((r) => ({
    id: r.id,
    ledgerEntryId: r.ledgerEntryId,
    type: r.type,
    message: r.message,
    snapshotTimeUtc: r.snapshotTimeUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    sourceProvider: r.sourceProvider,
    createdAtUtc: r.createdAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    delivered: r.delivered,
    suppressedReason: r.suppressedReason,
    batchKey: r.batchKey,
  }));
}

/**
 * Evaluate updates for saved pending entries. Generates factual alerts via
 * the deterministic drift engine; respects preferences, mutes, the daily push
 * cap, and the freshness gate.
 */
export async function evaluateAlerts(userId: string): Promise<{ created: number; suppressed: { ledgerId: string; reason: string }[] }> {
  const nowUtc = isoUtc();
  const prefs = await getPreferences(userId);
  const enabledTypes = new Set(prefs.filter((p) => p.enabled).map((p) => p.type as AlertType));
  const muted = new Set<string>(); // per-entry mute is a record-level flag; none muted by default
  const todayStart = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const pushesToday = await db.alertEvent.count({
    where: { userId, delivered: true, createdAtUtc: { gte: todayStart }, type: { in: ['player_status', 'market_suspended'] } },
  });

  const pending = await db.ledgerEntry.findMany({
    where: { userId, settlement: { status: 'pending' }, duplicateOfLedgerId: null },
    include: { settlement: true, closingReference: true },
    take: 12,
    orderBy: { createdAtUtc: 'desc' },
  });

  const entries = pending.map((e) => ({
    ledgerId: e.ledgerId,
    playerName: e.playerName,
    market: e.market,
    capturedAtUtc: e.capturedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    enteredAmericanOdds: e.enteredAmericanOdds,
    nowUtc,
    drift: marketDrift({
      eventId: e.eventId,
      playerId: e.playerId,
      market: e.market,
      line: e.line,
      enteredAmericanOdds: e.enteredAmericanOdds,
      elapsedSeconds: Math.floor((Date.now() - e.capturedAtUtc.getTime()) / 1000),
    }),
  }));

  const { delivered, suppressed } = buildDemoAlerts(entries, {
    enabledTypes,
    mutedEntryIds: muted,
    pushesSentToday: pushesToday,
    nowUtc,
  });

  let created = 0;
  for (const d of delivered) {
    const existing = await db.alertEvent.findFirst({
      where: { userId, ledgerEntryId: d.ledgerEntryId, type: d.type, message: d.message },
    });
    if (existing) continue;
    await db.alertEvent.create({
      data: {
        userId,
        ledgerEntryId: d.ledgerEntryId,
        type: d.type,
        message: d.message,
        snapshotTimeUtc: new Date(d.snapshotTimeUtc),
        sourceProvider: d.sourceProvider,
        delivered: true,
        batchKey: d.batchKey ?? null,
      },
    });
    created++;
  }

  // Closing-reference availability alerts for settled entries lacking one.
  for (const e of pending) {
    if (e.closingReference) continue;
    const candidate = {
      ledgerEntryId: e.ledgerId,
      type: 'closing_available' as AlertType,
      message: ALERT_TEMPLATES.closingAvailable('DEMO-CLOSE-1 (simulated)'),
      snapshotTimeUtc: nowUtc,
      sourceProvider: 'DEMO-CLOSE-1 (simulated)',
      urgent: false,
      capturedAtUtc: nowUtc,
    };
    const decision = decideAlert(candidate, {
      enabledTypes,
      mutedEntryIds: muted,
      pushesSentToday: pushesToday + created,
      nowUtc,
    });
    if (decision.deliver) {
      const existing = await db.alertEvent.findFirst({ where: { userId, ledgerEntryId: e.ledgerId, type: 'closing_available' } });
      if (!existing) {
        await db.alertEvent.create({
          data: {
            userId,
            ledgerEntryId: e.ledgerId,
            type: 'closing_available',
            message: candidate.message,
            snapshotTimeUtc: new Date(candidate.snapshotTimeUtc),
            sourceProvider: candidate.sourceProvider,
            delivered: true,
          },
        });
        created++;
      }
    } else {
      suppressed.push({ ledgerId: e.ledgerId, reason: decision.reason ?? 'UNKNOWN' });
    }
  }

  return { created, suppressed };
}

export const ALERT_DAILY_CAP = DAILY_PUSH_CAP;
