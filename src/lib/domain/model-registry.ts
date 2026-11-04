/**
 * PropStein — model registry (demo corpus).
 *
 * Coverage policy (fail closed):
 *   - "calibrated"   -> probability + uncertainty interval may be displayed.
 *   - "uncalibrated" -> coverage exists but calibration is pending; NO numbers
 *                       are displayed ("No calibrated coverage").
 *   - "none"         -> no coverage at all.
 *   - "unavailable"  -> registry lists the market but the model surface is
 *                       down or revoked; assessment fails closed.
 *
 * The models here are deterministic demo models. They are NOT LLMs and no LLM
 * ever feeds them: each probability is a fixed function of (market, line,
 * event seed, model version). Rule 9 of the product charter is structural:
 * the LLM boundary is data extraction only.
 */

import { gauss, mulberry32, normalCdf, seedFrom } from './determinism';
import type { ModelAssessment } from './types';

export interface ModelRegistryEntry {
  modelName: string;
  modelVersion: string;
  sport: string;
  market: string;
  coverage: 'calibrated' | 'uncalibrated';
  corpusGames: number;
  dataFreshnessUtc: string;
  limitations: string[];
  /** Deterministic demo probability for the OVER side. */
  overProbability: (line: number, eventKey: string) => number;
}

const REC_V4_SIGMA_YDS = 12.4;
const PASS_V2_SIGMA_YDS = 26.0;

function normalOverProb(mu: number, sigma: number, line: number): number {
  return normalCdf((mu - line) / sigma);
}

export const MODEL_REGISTRY: ModelRegistryEntry[] = [
  {
    modelName: 'NFL Receiving Yards Model',
    modelVersion: 'REC-V4',
    sport: 'NFL',
    market: 'player_reception_yds',
    coverage: 'calibrated',
    corpusGames: 428,
    dataFreshnessUtc: '2026-11-01T06:00:00Z',
    limitations: [
      'Calibrated on 2024–2026 NFL regular-season games only; playoff contexts are out of corpus.',
      'Does not ingest in-game possession state; assessments are pregame only.',
      'Uncertainty interval reflects line/feature noise only, not injury-scratch risk.',
      'Uncalibrated for games with confirmed precipitation at kickoff.',
    ],
    overProbability: (line, eventKey) => {
      const rand = mulberry32(seedFrom('REC-V4', eventKey));
      // Deterministic pseudo-features: implied target share and usage drift.
      const mu = line + (rand() - 0.5) * 7.2 + gauss(rand) * 1.8;
      return normalOverProb(mu, REC_V4_SIGMA_YDS, line);
    },
  },
  {
    modelName: 'NFL Passing Yards Model',
    modelVersion: 'PASS-V2',
    sport: 'NFL',
    market: 'player_passing_yds',
    coverage: 'uncalibrated',
    corpusGames: 96,
    dataFreshnessUtc: '2026-10-28T06:00:00Z',
    limitations: [
      'Calibration corpus below preregistered minimum; probabilities are withheld.',
      'Coverage exists for research continuity only.',
    ],
    overProbability: (line, eventKey) => {
      const rand = mulberry32(seedFrom('PASS-V2', eventKey));
      return normalOverProb(line + (rand() - 0.5) * 14, PASS_V2_SIGMA_YDS, line);
    },
  },
];

/** Markets served by a model that is currently switched off (fail-closed demo). */
const MODEL_OUTAGE_MARKETS = new Set<string>();

/** Toggle a model surface outage (observability / fail-closed demonstration). */
export function setModelOutage(market: string, outage: boolean): void {
  if (outage) MODEL_OUTAGE_MARKETS.add(market);
  else MODEL_OUTAGE_MARKETS.delete(market);
}

export function isModelOutage(market: string): boolean {
  return MODEL_OUTAGE_MARKETS.has(market);
}

/**
 * Look up model coverage for a sport+market and produce the ModelAssessment
 * block for a given selection. Uncertainty interval uses the delta method on
 * the line-noise scale, widened to a 95% band.
 */
export function assessModelCoverage(
  sport: string,
  market: string,
  selection: 'over' | 'under',
  line: number,
  eventKey: string,
): ModelAssessment {
  const entry = MODEL_REGISTRY.find((m) => m.sport === sport && m.market === market);

  if (isModelOutage(market) && entry) {
    return {
      coverage: 'unavailable',
      modelName: entry.modelName,
      modelVersion: entry.modelVersion,
      probability: null,
      uncertainty: null,
      calibrationStatus: entry.coverage,
      limitations: entry.limitations,
      dataFreshnessUtc: null,
      corpusGames: entry.corpusGames,
    };
  }

  if (!entry) {
    return {
      coverage: 'none',
      modelName: null,
      modelVersion: null,
      probability: null,
      uncertainty: null,
      calibrationStatus: 'none',
      limitations: ['No model exists for this sport and market.'],
      dataFreshnessUtc: null,
      corpusGames: null,
    };
  }

  if (entry.coverage !== 'calibrated') {
    return {
      coverage: 'uncalibrated',
      modelName: entry.modelName,
      modelVersion: entry.modelVersion,
      probability: null,
      uncertainty: null,
      calibrationStatus: 'uncalibrated',
      limitations: entry.limitations,
      dataFreshnessUtc: entry.dataFreshnessUtc,
      corpusGames: entry.corpusGames,
    };
  }

  const pOver = entry.overProbability(line, eventKey);
  const p = selection === 'over' ? pOver : 1 - pOver;

  // Preregistered per-version standard error of the model's epistemic band.
  // REC-V4: se = 0.015 on the probability scale; 95% interval = ±1.96 × se.
  const se = MODEL_SE[entry.modelVersion] ?? 0.015;
  const lower = Math.max(0.01, p - 1.96 * se);
  const upper = Math.min(0.99, p + 1.96 * se);

  return {
    coverage: 'calibrated',
    modelName: entry.modelName,
    modelVersion: entry.modelVersion,
    probability: Number(p.toFixed(4)),
    uncertainty: { lower: Number(lower.toFixed(4)), upper: Number(upper.toFixed(4)) },
    calibrationStatus: 'calibrated',
    limitations: entry.limitations,
    dataFreshnessUtc: entry.dataFreshnessUtc,
    corpusGames: entry.corpusGames,
  };
}

/** Preregistered epistemic standard errors by model version. */
export const MODEL_SE: Record<string, number> = {
  'REC-V4': 0.015,
  'PASS-V2': 0.020,
};

/** Model input feed provider id — closing references must be independent of this. */
export const MODEL_FEED_PROVIDER = 'DEMO-MODEL-FEED';
