/* Verify mockup headline numbers: medians, means, snapped quote lines. */
import { PROJECTIONS, QUOTES, PLAYERS } from "../src/lib/propstein/data";
import { lawMedian, lawMean, lawSd, lawQuantile } from "../src/lib/propstein/distributions";

const focus: Array<[string, "receiving_yards" | "points" | "rebounds" | "assists" | "receptions"]> = [
  ["jamarr-chase", "receiving_yards"],
  ["jamarr-chase", "receptions"],
  ["shai-gilgeous-alexander", "points"],
  ["luka-doncic", "points"],
  ["giannis-antetokounmpo", "points"],
  ["nikola-jokic", "rebounds"],
];

for (const [pid, mkt] of focus) {
  const proj = PROJECTIONS.find((p) => p.playerId === pid && p.market === mkt)!;
  const q = QUOTES.find((x) => x.playerId === pid && x.market === mkt);
  const median = lawMedian(proj.law);
  const mean = lawMean(proj.law);
  const sd = lawSd(proj.law);
  const p10 = lawQuantile(0.1, proj.law);
  const p90 = lawQuantile(0.9, proj.law);
  console.log(
    `${pid} ${mkt}: median=${median.toFixed(1)} mean=${mean.toFixed(1)} sd=${sd.toFixed(1)} p10-p90=${p10.toFixed(0)}-${p90.toFixed(0)} quote=${q ? q.line + " " + q.overOdds + "/" + q.underOdds + " " + q.status : "none"}`
  );
}

// every NBA quote line for the board
console.log("\n-- NBA quote lines --");
for (const q of QUOTES) {
  const p = PLAYERS.find((x) => x.id === q.playerId)!;
  if (p.sport !== "nba") continue;
  console.log(`${p.name} ${q.market}: ${q.line} (${q.status})`);
}
