/**
 * PropStein — gate service: loads stored signals per sport, evaluates the
 * preregistered gate deterministically, and reports commercial state.
 */

import { db } from '@/lib/db';
import { evaluateGateAttempt, sportCommercialState } from '@/lib/domain/gate';
import { isoUtc } from '@/lib/domain/determinism';
import type { GateAttemptResult, GateSignal } from '@/lib/domain/types';

export interface GateStatusView {
  sport: string;
  preregistered: {
    nConfirm: number;
    nInterim: number;
    meanClvMinPp: number;
    alphaOneSided: number;
    bootstrapReplicates: number;
    seed: number;
    maxAttempts: number;
    minClusters: number;
  };
  nSignalsStored: number;
  currentAttempt: number;
  nEvaluable: number;
  distinctClusters: number;
  attempts: {
    attemptNo: number;
    nEvaluable: number;
    distinctClusters: number;
    meanClvPp: number;
    bootstrapLbPp: number;
    verdict: string;
    notes: string[];
    evaluatedAtUtc: string;
  }[];
  compliance: { status: string; approver: string; recordedAtUtc: string; note: string } | null;
  commercial: {
    gatePassed: boolean;
    retired: boolean;
    commercialSignalEnabled: boolean;
    explanation: string;
  };
}

const PREREG = {
  nConfirm: 600,
  nInterim: 300,
  meanClvMinPp: 1.0,
  alphaOneSided: 0.0125,
  bootstrapReplicates: 10000,
  seed: 20261024,
  maxAttempts: 2,
  minClusters: 30,
};

async function signalsForSport(sport: string, attemptScope?: number): Promise<GateSignal[]> {
  const where = attemptScope ? { sport, attemptScope } : { sport };
  const rows = await db.gateSignal.findMany({ where });
  return rows.map((r) => ({
    signalId: r.signalId,
    sport: r.sport,
    gameClusterId: r.gameClusterId,
    playerId: r.playerId,
    clvPp: r.clvPp,
    evaluable: r.evaluable,
    reasonCode: (r.reasonCode ?? null) as GateSignal['reasonCode'],
    modelVersion: r.modelVersion,
    recordedAtUtc: r.recordedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
  }));
}

/** Attempt scope encoded in the signal id convention "SPORT|A{n}|…". */
function signalAttempt(signalId: string): number {
  const m = /\|A(\d+)\|/.exec(signalId);
  return m ? Number(m[1]) : 1;
}

export async function getGateStatuses(): Promise<GateStatusView[]> {
  const sports = ['NFL', 'NBA', 'UFC'];
  const views: GateStatusView[] = [];
  for (const sport of sports) {
    const attemptRows = await db.gateAttempt.findMany({ where: { sport }, orderBy: { attemptNo: 'asc' } });
    const compliance = await db.complianceApproval.findUnique({ where: { sport } });
    // Progress reflects the CURRENT accumulating attempt (latest scope);
    // historical attempt scopes are shown in the attempt history below.
    const currentScope = attemptRows.length > 0 ? Math.max(...attemptRows.map((a) => a.attemptNo)) : 1;
    const allSignals = await signalsForSport(sport);
    const scopedSignals = currentScope === 1 ? allSignals.filter((s) => signalAttempt(s.signalId) === 1) : await signalsForSport(sport, currentScope);
    const evaluable = scopedSignals.filter((s) => s.evaluable);
    const clusters = new Set(evaluable.map((s) => s.gameClusterId));

    const commercial = sportCommercialState(
      sport,
      attemptRows.map((a) => ({ attemptNo: a.attemptNo, verdict: a.verdict })),
      compliance ? { status: compliance.status as 'granted' | 'denied' | 'pending' } : null,
    );

    views.push({
      sport,
      preregistered: PREREG,
      nSignalsStored: allSignals.length,
      currentAttempt: currentScope,
      nEvaluable: evaluable.length,
      distinctClusters: clusters.size,
      attempts: attemptRows.map((a) => ({
        attemptNo: a.attemptNo,
        nEvaluable: a.nEvaluable,
        distinctClusters: a.distinctClusters,
        meanClvPp: a.meanClvPp,
        bootstrapLbPp: a.bootstrapLbPp,
        verdict: a.verdict,
        notes: JSON.parse(a.notesJson) as string[],
        evaluatedAtUtc: a.evaluatedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
      })),
      compliance: compliance
        ? {
            status: compliance.status,
            approver: compliance.approver,
            recordedAtUtc: compliance.recordedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
            note: compliance.note,
          }
        : null,
      commercial,
    });
  }
  return views;
}

/**
 * Recompute attempt 1 from stored signals. Deterministic: same stored set and
 * the preregistered seed produce the same verdict every time (this is the
 * reproducibility guarantee made visible in the Gate Monitor UI).
 */
export async function recomputeAttempt(
  sport: string,
  attemptNo = 1,
): Promise<{ stored: GateAttemptResult; recomputed: GateAttemptResult; matchesStored: boolean }> {
  const signals = await signalsForSport(sport, attemptNo);
  const recomputed = evaluateGateAttempt(sport, attemptNo, signals, isoUtc());
  const storedRow = await db.gateAttempt.findUnique({ where: { sport_attemptNo: { sport, attemptNo } } });
  const stored: GateAttemptResult = storedRow
    ? {
        sport,
        attemptNo: storedRow.attemptNo,
        nEvaluable: storedRow.nEvaluable,
        distinctClusters: storedRow.distinctClusters,
        meanClvPp: storedRow.meanClvPp,
        bootstrapLbPp: storedRow.bootstrapLbPp,
        verdict: storedRow.verdict as GateAttemptResult['verdict'],
        seed: storedRow.seed,
        replicates: storedRow.replicates,
        modelVersions: JSON.parse(storedRow.modelVersionsJson),
        evaluatedAtUtc: storedRow.evaluatedAtUtc.toISOString(),
        notes: JSON.parse(storedRow.notesJson) as string[],
      }
    : recomputed;
  const matchesStored =
    !storedRow ||
    (stored.verdict === recomputed.verdict &&
      stored.meanClvPp === recomputed.meanClvPp &&
      stored.nEvaluable === recomputed.nEvaluable);
  return { stored, recomputed, matchesStored };
}
