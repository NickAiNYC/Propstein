/**
 * PropStein Live Sniper — Panel View Models
 * =======================================
 * Pure mapping from SignalSnapshot → display rows. All formatting and
 * display-state decisions live here so they are unit-testable without React.
 */

import {
  formatAmerican,
  formatPercent,
  formatEvPerUnit,
  formatQuoteAge,
  signalStatusLabel,
  fairDecimalOdds,
  type SignalSnapshot,
  type ModelConfidence,
} from "@propstein/core";

export type SignalTone = "positive" | "caution" | "negative" | "neutral" | "muted";

export interface SignalCardViewModel {
  key: string;
  leagueLine: string;
  marketTitle: string;
  playerLine: string;
  selectionLine: string;
  sportsbookPrice: string;
  breakEven: string;
  modelProbability: string;
  estimatedEv: string;
  evTone: SignalTone;
  source: string;
  marketStatus: string;
  model: string;
  quoteAge: string;
  statusLabel: string;
  tone: SignalTone;
  withdrawn: boolean;
  reasons: string[];
  confidenceLabel: string;
  fairOdds: string | null;
  probabilityEdge: string | null;
}

function toneForState(s: SignalSnapshot): SignalTone {
  if (s.withdrawn) return "muted";
  switch (s.state) {
    case "ALERTABLE": return "positive";
    case "BELOW_THRESHOLD": return (s.evaluation?.evPerUnit ?? 0) >= 0 ? "neutral" : "negative";
    case "UNVERIFIED": return "caution";
    case "STALE":
    case "SUSPENDED":
    case "MODEL_UNAVAILABLE": return "caution";
    default: return "neutral";
  }
}

function confidenceLabel(c: ModelConfidence | undefined): string {
  switch (c) {
    case "calibrated": return "CALIBRATED";
    case "insufficient_evidence": return "INSUFFICIENT EVIDENCE";
    case "uncalibrated": return "UNCALIBRATED";
    default: return "UNKNOWN";
  }
}

export function toSignalCardViewModel(s: SignalSnapshot): SignalCardViewModel {
  const m = s.observed;
  const ev = s.evaluation;
  const evValue = ev?.evPerUnit ?? 0;
  const evTone: SignalTone = !ev ? "muted" : evValue > 0 ? "positive" : evValue < 0 ? "negative" : "neutral";
  const driveTag = m.driveId ? " · LIVE DRIVE" : "";
  const provenanceTag = m.provenance === "synthetic-fixture" ? " · DEMO FIXTURE" : "";

  return {
    key: s.signalKey,
    leagueLine: `${m.league}${driveTag}${provenanceTag}`,
    marketTitle: (s.normalized?.observed.marketLabel ?? m.marketLabel).toUpperCase(),
    playerLine: `Player: ${m.playerName}`,
    selectionLine: `Market: ${m.selection}`,
    sportsbookPrice: m.americanOdds !== undefined ? formatAmerican(m.americanOdds) : (m.decimalOdds !== undefined ? `${m.decimalOdds.toFixed(2)}` : "—"),
    breakEven: ev ? formatPercent(ev.impliedProbability) : "—",
    modelProbability: ev ? formatPercent(ev.modelProbability, 1) : "—",
    estimatedEv: ev ? formatEvPerUnit(ev.evPerUnit) : "—",
    evTone,
    source: m.source === "demobook" ? "SYNTHETIC DEMO PAGE" : "VISIBLE PAGE · UNVERIFIED",
    marketStatus:
      m.marketStatus === "OPEN"
        ? `OPEN (OBSERVED${provenanceTag ? ", DEMO" : ""})`
        : m.marketStatus === "SUSPENDED" ? "SUSPENDED (OBSERVED)" : m.marketStatus,
    model: s.model ? `${s.model.modelVersion} · ${confidenceLabel(s.model.confidence)}` : "NO MODEL COVERAGE",
    quoteAge: formatQuoteAge(s.quoteAgeMs),
    statusLabel: signalStatusLabel(s),
    tone: toneForState(s),
    withdrawn: s.withdrawn,
    reasons: s.reasons.slice(0, 3),
    confidenceLabel: confidenceLabel(s.model?.confidence),
    fairOdds: ev ? `${fairDecimalOdds(Math.min(0.9999, Math.max(0.0001, ev.modelProbability))).toFixed(2)} dec` : null,
    probabilityEdge: ev ? `${((ev.modelProbability - ev.impliedProbability) * 100).toFixed(1)} pts` : null,
  };
}
