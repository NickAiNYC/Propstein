import { getBoard, boardSummary, largestDivergences } from "../src/lib/propstein/derive";
import { ARCHIVE, ARCHIVE_COHORT } from "../src/lib/propstein/archive";
import { QUOTES } from "../src/lib/propstein/data";
import { summarizeClv } from "../src/lib/propstein/model";

const t0 = Date.now();
const board = getBoard();
const t1 = Date.now();

console.log(`board derivation: ${t1 - t0}ms for ${board.length} rows`);
const s = boardSummary();
console.log("summary:", s);
console.log("quotes:", QUOTES.length);

const statusCount = new Map<string, number>();
for (const r of board) statusCount.set(r.status, (statusCount.get(r.status) ?? 0) + 1);
console.log("statuses:", Object.fromEntries(statusCount));

console.log("\nlargest divergences:");
for (const r of largestDivergences(undefined, 8)) {
  console.log(
    `  ${r.player.name.padEnd(22)} ${r.market === "receptions" ? "REC" : "YDS"} fair=${r.fairLine.toFixed(1)} line=${r.quote?.line} z=${r.comparison.standardizedDivergence?.toFixed(2)} status=${r.status}`
  );
}

console.log("\nsample rows:");
for (const id of ["justin-jefferson", "breece-hall", "tyreek-hill", "kyle-pitts", "davante-adams"]) {
  for (const m of ["receptions", "receiving_yards"] as const) {
    const r = board.find((x) => x.key === `${id}:${m}`)!;
    console.log(
      `  ${r.player.name.padEnd(20)} ${m === "receptions" ? "REC" : "YDS"} median=${r.fairLine} mean=${r.projectedVolume.toFixed(1)} sd=${r.sd.toFixed(1)} p10=${r.p10.toFixed(1)} p90=${r.p90.toFixed(1)} status=${r.status} line=${r.quote?.line ?? "—"} band=${r.boundaries ? `${r.boundaries.lower.toFixed(1)}–${r.boundaries.upper.toFixed(1)}` : "—"}`
    );
  }
}

console.log(`\narchive: ${ARCHIVE.length} markets, ${ARCHIVE_COHORT.evaluable} evaluable, ${ARCHIVE_COHORT.excluded} excluded`);
console.log("exclusions:", ARCHIVE_COHORT.exclusions);
console.log("byWeek:", ARCHIVE_COHORT.byWeek);
console.log("byVersion:", ARCHIVE_COHORT.byVersion);

const t2 = Date.now();
const clv = summarizeClv(
  ARCHIVE.filter((m) => m.evaluable).map((m) => ({
    fairLine: m.fairLine,
    closeLine: m.closeLine!,
    sd: m.sd,
  }))
);
console.log(`clv: ${Date.now() - t2}ms`, clv);

// calibration deciles
const evaluable = ARCHIVE.filter((m) => m.evaluable && m.predictedOverAtClose !== null);
const sorted = [...evaluable].sort((a, b) => a.predictedOverAtClose! - b.predictedOverAtClose!);
console.log("\ncalibration deciles (n=" + sorted.length + "):");
for (let d = 0; d < 10; d++) {
  const slice = sorted.slice(Math.floor(d * sorted.length / 10), Math.floor((d + 1) * sorted.length / 10));
  const avgP = slice.reduce((a, b) => a + b.predictedOverAtClose!, 0) / slice.length;
  const obs = slice.filter((m) => m.overHit).length / slice.length;
  console.log(`  d${d + 1}: predicted=${avgP.toFixed(3)} observed=${obs.toFixed(3)} n=${slice.length}`);
}
console.log(`\ntotal time: ${Date.now() - t0}ms`);
