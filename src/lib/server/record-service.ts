/**
 * PropStein — record service: the Luck Meter behind GET /records/luck-meter.
 */

import { db } from '@/lib/db';
import { buildLuckMeterReport } from '@/lib/domain/stats';
import { buildOutcomesForUser } from './ledger-service';
import { seedFrom } from '@/lib/domain/determinism';
import type { LuckMeterReport } from '@/lib/domain/types';

export async function getLuckMeter(userId: string): Promise<LuckMeterReport> {
  const outcomes = await buildOutcomesForUser(userId);

  // Gate/compliance state for the record's dominant sport (NFL by demo setup).
  const sports = [...new Set(outcomes.map((o) => o.sport))];
  let gatePassed = false;
  let complianceApproved = false;
  for (const sport of sports) {
    const attempts = await db.gateAttempt.findMany({ where: { sport } });
    const compliance = await db.complianceApproval.findUnique({ where: { sport } });
    const passes = attempts.some((a) => a.verdict === 'PASS');
    if (passes) gatePassed = true;
    if (compliance?.status === 'granted') complianceApproved = true;
  }

  return buildLuckMeterReport({
    outcomes,
    gatePassed,
    complianceApproved,
    seed: seedFrom('LUCKMETER', userId),
  });
}
