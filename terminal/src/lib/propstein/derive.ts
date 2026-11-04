/* ============================================================
   PropStein — derived board rows
   Joins projections with captured quotes and computes every
   published figure from the exact distribution laws. All
   derived values are memoized at module scope: deterministic
   and identical on server and client.
   ============================================================ */

import type {
  EvidenceStatus,
  MarketKey,
  Player,
  Quote,
  Projection,
  Sport,
} from "./types";
import { EVIDENCE_STATUS_META, MARKET_META, MARKET_KEYS_BY_SPORT, GOVERNANCE } from "./types";
import {
  PLAYERS,
  PROJECTIONS,
  QUOTES,
  UNAVAILABLE,
  gameFor,
  SEED_MAP,
} from "./data";
import {
  DistLaw,
  lawMedian,
  lawMean,
  lawSd,
  lawQuantile,
} from "./distributions";
import {
  ValueBoundaries,
  computeValueBoundaries,
  compareMarket,
  MarketComparison,
} from "./model";

export interface BoardRow {
  key: string;
  player: Player;
  market: MarketKey;
  projection: Projection;
  status: EvidenceStatus;
  quote: Quote | null;
  unavailableReason?: string;
  fairLine: number;
  projectedVolume: number;
  sd: number;
  p10: number;
  p90: number;
  comparison: MarketComparison;
  boundaries: ValueBoundaries | null;
}

let cachedRows: BoardRow[] | null = null;

export function getBoard(): BoardRow[] {
  if (cachedRows) return cachedRows;
  const rows: BoardRow[] = [];
  for (const player of PLAYERS) {
    for (const market of MARKET_KEYS_BY_SPORT[player.sport]) {
      const projection = PROJECTIONS.find(
        (p) => p.playerId === player.id && p.market === market
      )!;
      const quote = QUOTES.find((q) => q.playerId === player.id && q.market === market);
      const unavailableReason = UNAVAILABLE[`${player.id}:${market}`];

      const law: DistLaw = projection.law;
      const fairLine = lawMedian(law);
      const projectedVolume = lawMean(law);
      const sd = lawSd(law);
      const p10 = lawQuantile(0.1, law);
      const p90 = lawQuantile(0.9, law);

      let status: EvidenceStatus;
      if (quote) {
        status = quote.status;
      } else if (unavailableReason) {
        status = "UNAVAILABLE";
      } else {
        status = "MODEL_ONLY";
      }

      const boundaries =
        quote && quote.status !== "STALE"
          ? computeValueBoundaries(law, quote.overOdds, quote.underOdds, quote.line)
          : quote
            ? computeValueBoundaries(law, quote.overOdds, quote.underOdds, undefined)
            : null;

      rows.push({
        key: `${player.id}:${market}`,
        player,
        market,
        projection,
        status,
        quote: quote ?? null,
        unavailableReason,
        fairLine,
        projectedVolume,
        sd,
        p10,
        p90,
        comparison: compareMarket(
          law,
          fairLine,
          projectedVolume,
          sd,
          quote ? quote.line : null,
          quote?.overOdds,
          quote?.underOdds
        ),
        boundaries,
      });
    }
  }
  cachedRows = rows;
  return rows;
}

export function getRow(playerId: string, market: MarketKey): BoardRow | undefined {
  return getBoard().find((r) => r.key === `${playerId}:${market}`);
}

/** Board rows for one league. */
export function getBoardFor(sport: Sport): BoardRow[] {
  return getBoard().filter((r) => r.player.sport === sport);
}

/* ---------- invalidation factors (assumptions panel) ---------- */

export interface InvalidationFactor {
  severity: "material" | "moderate" | "minor";
  title: string;
  detail: string;
}

export function invalidationFactors(row: BoardRow): InvalidationFactor[] {
  const seed = SEED_MAP[row.player.id];
  const game = gameFor(row.player.gameId);
  const sport = row.player.sport;
  const out: InvalidationFactor[] = [];

  if (row.player.injury === "QUESTIONABLE") {
    out.push({
      severity: "material",
      title: "Injury designation",
      detail: `${row.player.name} is questionable (${row.player.injuryNote ?? "listed"}). If inactive, the market resolves void or the line re-prices sharply; if active at limited participation, volume may be capped. Model assumes active status at current usage rates.`,
    });
  }

  // game script from spread
  const isHome = game.home === row.player.team;
  const spreadFromTeam = isHome ? -game.spread : game.spread; // positive ⇒ player's team favored
  if (Math.abs(spreadFromTeam) >= 3) {
    const favored = spreadFromTeam > 0;
    out.push({
      severity: "moderate",
      title: "Game script",
      detail: favored
        ? sport === "nfl"
          ? `${row.player.team} is favored by ${Math.abs(spreadFromTeam).toFixed(1)}. A leading script historically shifts volume toward the run and drains late-game targets; the mean already conditions on this since v3.2.1, but blowout extension adds dispersion.`
          : `${row.player.team} is favored by ${Math.abs(spreadFromTeam).toFixed(1)}. A leading script historically drains late-game minutes for starters and shifts offense toward the bench; garbage-time extension fattens both tails relative to the published law.`
        : sport === "nfl"
          ? `${row.player.team} is a ${Math.abs(spreadFromTeam).toFixed(1)}-point underdog. Trailing scripts raise pass rate and garbage-time volume; the count dispersion widens and the median shifts later in the distribution.`
          : `${row.player.team} is a ${Math.abs(spreadFromTeam).toFixed(1)}-point underdog. Trailing scripts raise possession count and shot rate for starters who keep closes; usage share concentrates and event dispersion widens.`,
    });
  }

  // opponent scheme
  out.push({
    severity: "moderate",
    title: "Opponent scheme",
    detail: seed.oppNote,
  });

  // usage concentration
  if (row.player.targetShare >= (sport === "nfl" ? 0.24 : 0.3)) {
    out.push({
      severity: "minor",
      title: sport === "nfl" ? "Usage concentration" : "Usage concentration",
      detail: sport === "nfl"
        ? `A ${(row.player.targetShare * 100).toFixed(0)}% target share concentrates team passing volume. If game flow redistributes targets (early deficit, rotation), the model's volume assumption is the first thing to break.`
        : `A ${(row.player.targetShare * 100).toFixed(0)}% usage rate concentrates team possession volume. If foul trouble, bench units, or blowout flow redistribute creation, the model's volume assumption is the first thing to break.`,
    });
  }

  // structural model assumptions — always present, versioned
  out.push(
    sport === "nfl"
      ? {
          severity: "minor",
          title: "Independence of catches",
          detail:
            "Receiving yards assume per-catch gains are independent Gamma draws. In reality catch sequencing correlates with game flow (targets cluster on scripted drives), which fattens both tails relative to the published law.",
        }
      : {
          severity: "minor",
          title: "Independence of scoring events",
          detail:
            "Points assume scoring events follow one overdispersed count law. In reality free-throw trips, hot shooting stretches, and late-game fouling correlate events, which fattens both tails relative to the published NB2 law.",
        }
  );

  return out;
}

/* ---------- headline stats for overview ---------- */

export function boardSummary(sport?: Sport) {
  const players = sport ? PLAYERS.filter((p) => p.sport === sport) : PLAYERS;
  const rows = sport ? getBoard().filter((r) => r.player.sport === sport) : getBoard();
  const byStatus = new Map<EvidenceStatus, number>();
  for (const r of rows) byStatus.set(r.status, (byStatus.get(r.status) ?? 0) + 1);
  return {
    sport: sport ?? null,
    players: players.length,
    games: new Set(players.map((p) => p.gameId)).size,
    markets: rows.length,
    quoted: rows.filter((r) => r.quote).length,
    byStatus,
    verified: byStatus.get("VERIFIED") ?? 0,
    observed: byStatus.get("OBSERVED_UNVERIFIED") ?? 0,
    stale: byStatus.get("STALE") ?? 0,
    modelOnly: byStatus.get("MODEL_ONLY") ?? 0,
    unavailable: byStatus.get("UNAVAILABLE") ?? 0,
  };
}

/** Largest |standardized divergence| rows with quotes — framed as research, not touts. */
export function largestDivergences(sport?: Sport, n = 5): BoardRow[] {
  return getBoard()
    .filter((r) => (sport ? r.player.sport === sport : true))
    .filter((r) => r.quote && r.comparison.standardizedDivergence !== null)
    .sort(
      (a, b) =>
        Math.abs(b.comparison.standardizedDivergence!) -
        Math.abs(a.comparison.standardizedDivergence!)
    )
    .slice(0, n);
}

export function governanceStatus() {
  const evaluable = GOVERNANCE; // thresholds
  return evaluable;
}

export { EVIDENCE_STATUS_META, MARKET_META };
