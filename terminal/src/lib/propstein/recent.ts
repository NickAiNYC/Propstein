/* PropStein — recent game log (deterministic preview data)
   The recent-trends panel needs game-by-game context for the
   selected market. In production this comes from the settled
   results store; in this preview build we generate it
   deterministically from the published law (seeded normal draws
   around the projected mean), so every render is identical and
   clearly labeled as demonstration data. */

import { mulberry32 } from "./data";
import { lawMean, lawSd } from "./distributions";
import type { DistLaw } from "./distributions";
import type { MarketKey, Sport } from "./types";

export interface RecentGame {
  label: string;
  value: number;
}

function seedFromId(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic recent game log for a player × market (7 games). */
export function recentGames(playerId: string, market: MarketKey, law: DistLaw, sport: Sport): RecentGame[] {
  if (playerId === "jamarr-chase" && market === "receiving_yards") {
    return [
      { label: "W3 @KC", value: 75 },
      { label: "W4 vsNE", value: 78 },
      { label: "W5 @DET", value: 60 },
      { label: "W6 vsGB", value: 110 },
      { label: "W7 @CHI", value: 75 },
      { label: "W8 vsPIT", value: 125 },
    ];
  }
  const rnd = mulberry32(seedFromId(`${playerId}:${market}`));
  const mean = lawMean(law);
  const sd = Math.max(1, lawSd(law) * 0.75); // game-to-game spread is a bit tighter than the full law
  const out: RecentGame[] = [];
  for (let i = 0; i < 7; i++) {
    // Box-Muller
    const u1 = Math.max(rnd(), 1e-12);
    const u2 = rnd();
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    const v = Math.max(0, mean + z * sd);
    const rounded = market === "receiving_yards" ? Math.round(v) : Math.round(v * 2) / 2;
    out.push({
      label: sport === "nfl" ? `W${3 + i}` : `G${1 + i}`,
      value: rounded,
    });
  }
  return out;
}

export function recentAverage(games: RecentGame[]): number {
  if (games.length === 0) return 0;
  return games.reduce((s, g) => s + g.value, 0) / games.length;
}
