/* ============================================================
   PropStein — historical archive (public performance cohorts)
   Deterministic generation of settled NFL receiving markets,
   Weeks 3–8 of the 2026 season. Full-board honesty:
   every generated market carries evaluable/exclusion state.
   ============================================================ */

import type { ArchivedMarket, MarketKey } from "./types";
import { mulberry32, NFL_SEEDS } from "./data";
import {
  DistLaw,
  negBinMedian,
  compoundMedian,
  lawSd,
  lawSurvival,
} from "./distributions";

/** model version active in each week of the 2026 season (timeline) */
export const VERSION_TIMELINE = [
  {
    version: "v2.4.1",
    since: "Week 1",
    deployedAt: "2026-09-09",
    note: "Opponent-adjusted NB2 dispersion; yards via normal approximation",
  },
  {
    version: "v3.0.0",
    since: "Week 5",
    deployedAt: "2026-10-06",
    note: "Gamma YPR by route depth; exact NB∘Gamma compound replaces normal approximation",
  },
  {
    version: "v3.1.0",
    since: "Week 6",
    deployedAt: "2026-10-13",
    note: "Red-zone target prior; weather adjustments on YPR scale",
  },
  {
    version: "v3.2.1",
    since: "Week 7",
    deployedAt: "2026-10-27",
    note: "Game-script conditioning on spread and total (current)",
  },
] as const;

function versionForWeek(week: number): string {
  if (week <= 4) return "v2.4.1";
  if (week === 5) return "v3.0.0";
  if (week === 6) return "v3.1.0";
  return "v3.2.1";
}

/** Box-Muller normal from a uniform generator */
function normal(rnd: () => number, mean: number, sd: number): number {
  const u1 = Math.max(rnd(), 1e-12);
  const u2 = rnd();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return mean + sd * z;
}

/** mild, realistic calibration imperfection: slight overconfidence in the tails */
function calibratedTruth(p: number): number {
  return Math.min(0.99, Math.max(0.01, p - 0.035 * (p - 0.5)));
}

function generateArchive(): ArchivedMarket[] {
  const rnd = mulberry32(20261116);
  const out: ArchivedMarket[] = [];
  const markets: MarketKey[] = ["receptions", "receiving_yards"];

  for (let week = 3; week <= 8; week++) {
    // each week samples a subset of the player pool with per-week usage noise
    const poolSize = 30 + Math.floor(rnd() * 8); // 30–37 of 38 players
    const pool = [...NFL_SEEDS].sort(() => rnd() - 0.5).slice(0, poolSize);
    for (const seed of pool) {
      for (const market of markets) {
        // weekly usage multiplier — healthy weekly variation, not white noise
        const usage = 0.82 + rnd() * 0.36; // 0.82–1.18
        const recMu = seed.recMu * usage;
        const law: DistLaw =
          market === "receptions"
            ? { kind: "negbin", nb: { r: seed.recR, mu: recMu } }
            : {
                kind: "compound",
                nb: { r: seed.recR, mu: recMu },
                gamma: { k: seed.yprK, theta: seed.yprT },
              };
        const fairLine =
          market === "receptions"
            ? negBinMedian(law.nb)
            : compoundMedian({
                r: law.nb.r,
                mu: law.nb.mu,
                k: law.gamma!.k,
                theta: law.gamma!.theta,
              });
        const sd = lawSd(law);

        const id = `w${week}-${seed.id}-${market}`;
        const roll = rnd();
        // full-board honesty: some markets are NOT evaluable, with reasons
        if (roll < 0.045) {
          out.push({
            id,
            week,
            season: 2026,
            playerId: seed.id,
            playerName: seed.name,
            market,
            modelVersion: versionForWeek(week),
            fairLine,
            closeLine: null,
            sd,
            predictedOverAtClose: null,
            overHit: null,
            evaluable: false,
            exclusionReason: "NO_CLOSE",
          });
          continue;
        }
        if (roll < 0.075) {
          out.push({
            id,
            week,
            season: 2026,
            playerId: seed.id,
            playerName: seed.name,
            market,
            modelVersion: versionForWeek(week),
            fairLine,
            closeLine: null,
            sd,
            predictedOverAtClose: null,
            overHit: null,
            evaluable: false,
            exclusionReason: "STALE_CLOSE",
          });
          continue;
        }
        if (roll < 0.085) {
          out.push({
            id,
            week,
            season: 2026,
            playerId: seed.id,
            playerName: seed.name,
            market,
            modelVersion: versionForWeek(week),
            fairLine,
            closeLine: null,
            sd,
            predictedOverAtClose: null,
            overHit: null,
            evaluable: false,
            exclusionReason: "POSTPONED",
          });
          continue;
        }

        // closing line = fair + noise (model roughly calibrated vs the close)
        const z = normal(rnd, 0.06, 0.86);
        const rawClose = fairLine + z * sd;
        const closeLine =
          market === "receptions"
            ? Math.max(0.5, Math.round(rawClose * 2) / 2)
            : Math.max(2.5, Math.round(rawClose / 0.5) * 0.5);

        const predictedOver = lawSurvival(closeLine, law);
        const truth = calibratedTruth(predictedOver);
        const overHit = rnd() < truth;

        out.push({
          id,
          week,
          season: 2026,
          playerId: seed.id,
          playerName: seed.name,
          market,
          modelVersion: versionForWeek(week),
          fairLine,
          closeLine,
          sd,
          predictedOverAtClose: predictedOver,
          overHit,
          evaluable: true,
        });
      }
    }
  }
  return out;
}

/** Deterministic module-level memo — identical on server and client. */
export const ARCHIVE: ArchivedMarket[] = generateArchive();

export function archiveExclusionCounts() {
  const counts = { NO_CLOSE: 0, STALE_CLOSE: 0, POSTPONED: 0, VOID: 0 } as Record<string, number>;
  for (const m of ARCHIVE) if (!m.evaluable) counts[m.exclusionReason!]++;
  return counts;
}

export const ARCHIVE_COHORT = (() => {
  const evaluable = ARCHIVE.filter((m) => m.evaluable);
  return {
    total: ARCHIVE.length,
    evaluable: evaluable.length,
    excluded: ARCHIVE.length - evaluable.length,
    exclusions: archiveExclusionCounts(),
    byWeek: [3, 4, 5, 6, 7, 8].map((w) => ({
      week: w,
      total: ARCHIVE.filter((m) => m.week === w).length,
      evaluable: ARCHIVE.filter((m) => m.week === w && m.evaluable).length,
    })),
    byVersion: [...new Set(ARCHIVE.map((m) => m.modelVersion))].map((v) => ({
      version: v,
      n: ARCHIVE.filter((m) => m.modelVersion === v && m.evaluable).length,
    })),
  };
})();
