/* ============================================================
   PropStein — deterministic preview dataset
   NFL Week 9 (Nov 5–9, 2026) receiving markets + NBA Nov 6 slate
   points / rebounds / assists markets.

   This preview build ships a deterministic demonstration
   dataset that mirrors the production data contracts:
   • every quote carries a capturedAt timestamp and source
   • statuses fail closed (MODEL_ONLY / OBSERVED_UNVERIFIED /
     VERIFIED / STALE / ARCHIVED / UNAVAILABLE)
   • no value is ever presented as "live"
   Market lines are generated from the model median plus a
   fixed offset, so quote and model always share one math.
   ============================================================ */

import type {
  Player,
  GameInfo,
  Projection,
  Quote,
  Team,
  MarketKey,
  CaptureEvent,
  Sport,
} from "./types";
import { SNAPSHOT_AT, MODEL_VERSION, DATA_WINDOW } from "./types";
import { negBinMedian, compoundMedian, DistLaw } from "./distributions";

/* ---------- deterministic PRNG (mulberry32) ---------- */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---------- teams ---------- */
export const TEAMS: Record<string, Team> = {
  PIT: { abbr: "PIT", city: "Pittsburgh", name: "Steelers", color: "#F0A800" },
  BAL: { abbr: "BAL", city: "Baltimore", name: "Ravens", color: "#9B6BDF" },
  DET: { abbr: "DET", city: "Detroit", name: "Lions", color: "#58A6FF" },
  GB: { abbr: "GB", city: "Green Bay", name: "Packers", color: "#56B36A" },
  MIN: { abbr: "MIN", city: "Minnesota", name: "Vikings", color: "#A78BFA" },
  ATL: { abbr: "ATL", city: "Atlanta", name: "Falcons", color: "#E05C5C" },
  CIN: { abbr: "CIN", city: "Cincinnati", name: "Bengals", color: "#E8646B" },
  CLE: { abbr: "CLE", city: "Cleveland", name: "Browns", color: "#E0862F" },
  NYG: { abbr: "NYG", city: "New York", name: "Giants", color: "#5AA9E6" },
  PHI: { abbr: "PHI", city: "Philadelphia", name: "Eagles", color: "#A8C5E2" },
  NYJ: { abbr: "NYJ", city: "New York", name: "Jets", color: "#6FCF97" },
  MIA: { abbr: "MIA", city: "Miami", name: "Dolphins", color: "#4DD4E8" },
  KC: { abbr: "KC", city: "Kansas City", name: "Chiefs", color: "#E8483F" },
  DEN: { abbr: "DEN", city: "Denver", name: "Broncos", color: "#F5A623" },
  LAR: { abbr: "LAR", city: "Los Angeles", name: "Rams", color: "#D9B64A" },
  TB: { abbr: "TB", city: "Tampa Bay", name: "Buccaneers", color: "#E05C4B" },
  SF: { abbr: "SF", city: "San Francisco", name: "49ers", color: "#C9A24B" },
  ARI: { abbr: "ARI", city: "Arizona", name: "Cardinals", color: "#D96459" },
  BUF: { abbr: "BUF", city: "Buffalo", name: "Bills", color: "#5B8DEF" },
  IND: { abbr: "IND", city: "Indianapolis", name: "Colts", color: "#8FBCE6" },
  // NBA
  OKC: { abbr: "OKC", city: "Oklahoma City", name: "Thunder", color: "#56B3F5" },
  LAL: { abbr: "LAL", city: "Los Angeles", name: "Lakers", color: "#F5C26B" },
  GSW: { abbr: "GSW", city: "Golden State", name: "Warriors", color: "#5AC8E8" },
  MIL: { abbr: "MIL", city: "Milwaukee", name: "Bucks", color: "#7EC97E" },
  ORL: { abbr: "ORL", city: "Orlando", name: "Magic", color: "#9B8BDF" },
  BOS: { abbr: "BOS", city: "Boston", name: "Celtics", color: "#6FBF7A" },
  NYK: { abbr: "NYK", city: "New York", name: "Knicks", color: "#F0876E" },
};

/* ---------- slate ---------- */
export const GAMES: GameInfo[] = [
  // NFL — Week 9
  { id: "wk09-pit-bal", sport: "nfl", week: 9, kickoff: "2026-11-05T20:15:00-05:00", away: "PIT", home: "BAL", spread: -2.5, total: 44.5, venue: "M&T Bank Stadium", venueShort: "M&T Bank", slot: "THU" },
  { id: "wk09-det-gb", sport: "nfl", week: 9, kickoff: "2026-11-08T13:00:00-05:00", away: "DET", home: "GB", spread: 2.5, total: 49, venue: "Lambeau Field", venueShort: "Lambeau", slot: "SUN_EARLY" },
  { id: "wk09-min-atl", sport: "nfl", week: 9, kickoff: "2026-11-08T13:00:00-05:00", away: "MIN", home: "ATL", spread: 3, total: 47.5, venue: "Mercedes-Benz Stadium (roof)", venueShort: "Mercedes-Benz", slot: "SUN_EARLY" },
  { id: "wk09-cin-bal", sport: "nfl", week: 9, kickoff: "2026-11-09T13:00:00-05:00", away: "CIN", home: "BAL", spread: 2.5, total: 47.5, venue: "M&T Bank Stadium", venueShort: "M&T Bank", slot: "SUN_EARLY" },
  { id: "wk09-nyg-phi", sport: "nfl", week: 9, kickoff: "2026-11-08T13:00:00-05:00", away: "NYG", home: "PHI", spread: 5.5, total: 45, venue: "Lincoln Financial Field", venueShort: "Lincoln Financial", slot: "SUN_EARLY" },
  { id: "wk09-nyj-mia", sport: "nfl", week: 9, kickoff: "2026-11-08T16:05:00-05:00", away: "NYJ", home: "MIA", spread: 3, total: 46, venue: "Hard Rock Stadium", venueShort: "Hard Rock", slot: "SUN_LATE" },
  { id: "wk09-kc-den", sport: "nfl", week: 9, kickoff: "2026-11-08T16:25:00-05:00", away: "KC", home: "DEN", spread: 6, total: 44.5, venue: "Empower Field at Mile High", venueShort: "Empower Field", slot: "SUN_LATE" },
  { id: "wk09-lar-tb", sport: "nfl", week: 9, kickoff: "2026-11-08T16:25:00-05:00", away: "LAR", home: "TB", spread: 1.5, total: 47, venue: "Raymond James Stadium", venueShort: "Raymond James", slot: "SUN_LATE" },
  { id: "wk09-sf-ari", sport: "nfl", week: 9, kickoff: "2026-11-08T20:20:00-05:00", away: "SF", home: "ARI", spread: 3, total: 45.5, venue: "State Farm Stadium (roof)", venueShort: "State Farm", slot: "SUN_NIGHT" },
  { id: "wk09-buf-ind", sport: "nfl", week: 9, kickoff: "2026-11-09T20:15:00-05:00", away: "BUF", home: "IND", spread: 4.5, total: 46, venue: "Lucas Oil Stadium (roof)", venueShort: "Lucas Oil", slot: "MON" },
  // NBA — Friday, Nov 6, 2026
  { id: "nba-okc-den", sport: "nba", week: 10, kickoff: "2026-11-06T19:00:00-05:00", away: "OKC", home: "DEN", spread: -1.5, total: 228.5, venue: "Ball Arena", venueShort: "Ball Arena", slot: "FRI" },
  { id: "nba-lal-gsw", sport: "nba", week: 10, kickoff: "2026-11-06T22:00:00-05:00", away: "LAL", home: "GSW", spread: 2.5, total: 231, venue: "Chase Center", venueShort: "Chase Center", slot: "FRI" },
  { id: "nba-mil-orl", sport: "nba", week: 10, kickoff: "2026-11-06T19:00:00-05:00", away: "MIL", home: "ORL", spread: -3.5, total: 224, venue: "Kia Center", venueShort: "Kia Center", slot: "FRI" },
  { id: "nba-bos-cle", sport: "nba", week: 10, kickoff: "2026-11-06T19:30:00-05:00", away: "BOS", home: "CLE", spread: 1.5, total: 226.5, venue: "Rocket Arena", venueShort: "Rocket Arena", slot: "FRI" },
];

export function gameFor(gameId: string): GameInfo {
  return GAMES.find((g) => g.id === gameId)!;
}

export function gamesForSport(sport: Sport): GameInfo[] {
  return GAMES.filter((g) => g.sport === sport);
}

/* ---------- NFL players + fitted parameters ---------- */
interface NflSeed {
  id: string;
  name: string;
  team: string;
  pos: "WR" | "TE" | "RB";
  gameId: string;
  snapShare: number;
  targetShare: number;
  injury?: "QUESTIONABLE" | "OUT";
  injuryNote?: string;
  role: string;
  depth: string;
  /** NB2 reception model */
  recMu: number;
  recR: number;
  /** Gamma yards-per-reception */
  yprK: number;
  yprT: number;
  /** opponent/coverage context for the assumptions panel */
  oppNote: string;
}

export const NFL_SEEDS: NflSeed[] = [
  // — THU: PIT @ BAL —
  { id: "dk-metcalf", name: "DK Metcalf", team: "PIT", pos: "WR", gameId: "wk09-pit-bal", snapShare: 0.87, targetShare: 0.24, role: "X receiver; primary boundary target", depth: "62% boundary · 21% slot", recMu: 5.6, recR: 6.0, yprK: 2.2, yprT: 5.6, oppNote: "Baltimore shadows with Travelon White; outside leverage biased to press-man." },
  { id: "george-pickens", name: "George Pickens", team: "PIT", pos: "WR", gameId: "wk09-pit-bal", snapShare: 0.82, targetShare: 0.19, role: "Z receiver; contested-shot specialist", depth: "71% boundary", recMu: 4.6, recR: 4.8, yprK: 2.0, yprT: 6.0, oppNote: "Ravens zone-heavy on third down; slant volume depends on box count." },
  { id: "zay-flowers", name: "Zay Flowers", team: "BAL", pos: "WR", gameId: "wk09-pit-bal", snapShare: 0.84, targetShare: 0.26, role: "Primary slot; separation engine", depth: "58% slot", recMu: 6.8, recR: 7.2, yprK: 2.4, yprT: 5.4, oppNote: "Pittsburgh bracket slot looks with safety help over the middle." },
  { id: "mark-andrews", name: "Mark Andrews", team: "BAL", pos: "TE", gameId: "wk09-pit-bal", snapShare: 0.71, targetShare: 0.21, role: "Red-zone tight end; seam targets", depth: "81% inline/short", recMu: 5.1, recR: 7.5, yprK: 3.2, yprT: 3.6, oppNote: "Steelers match 12 personnel with base; red-zone target share holds." },
  // — SUN early: DET @ GB —
  { id: "amon-ra-st-brown", name: "Amon-Ra St. Brown", team: "DET", pos: "WR", gameId: "wk09-det-gb", snapShare: 0.9, targetShare: 0.29, role: "Slot anchor; volume floor engine", depth: "64% slot", recMu: 8.1, recR: 9.0, yprK: 2.9, yprT: 4.9, oppNote: "Green Bay plays outside-zone Cover-6; quick-game targets avoid Jaire Alexander's side." },
  { id: "sam-laporta", name: "Sam LaPorta", team: "DET", pos: "TE", gameId: "wk09-det-gb", snapShare: 0.75, targetShare: 0.18, role: "Move tight end; middle-of-field volume", depth: "46% slot · 39% inline", recMu: 5.4, recR: 7.8, yprK: 3.1, yprT: 3.7, oppNote: "Packers safety depth softens play-action seams; red-zone role stable." },
  { id: "romeo-doubs", name: "Romeo Doubs", team: "GB", pos: "WR", gameId: "wk09-det-gb", snapShare: 0.79, targetShare: 0.2, role: "Boundary Z; red-zone complement", depth: "68% boundary", recMu: 5.0, recR: 5.8, yprK: 2.3, yprT: 5.2, oppNote: "Detroit's zone-match corners funnel outside; targets concentrated on drive-extenders." },
  // — SUN early: MIN @ ATL —
  { id: "justin-jefferson", name: "Justin Jefferson", team: "MIN", pos: "WR", gameId: "wk09-min-atl", snapShare: 0.93, targetShare: 0.31, role: "X alpha; full-route-tree volume", depth: "59% boundary · 33% slot", recMu: 7.9, recR: 8.8, yprK: 2.7, yprT: 5.3, oppNote: "Atlanta rolls A.J. Terrell coverage with post-safety help; usage plan shifts inside." },
  { id: "drake-london", name: "Drake London", team: "ATL", pos: "WR", gameId: "wk09-min-atl", snapShare: 0.88, targetShare: 0.27, role: "Big-slot hybrid; contested volume", depth: "47% slot · 43% boundary", recMu: 7.2, recR: 6.8, yprK: 2.5, yprT: 5.5, oppNote: "Vikings play two-shell zone; underneath targets replace downfield shots." },
  { id: "kyle-pitts", name: "Kyle Pitts", team: "ATL", pos: "TE", gameId: "wk09-min-atl", snapShare: 0.73, targetShare: 0.15, role: "Flex tight end; vertical seams", depth: "34% slot · 30% boundary", recMu: 4.4, recR: 5.4, yprK: 2.6, yprT: 5.0, oppNote: "Minnesota bracket seams from two-high; big-play law carries fat right tail." },
  { id: "bijan-robinson", name: "Bijan Robinson", team: "ATL", pos: "RB", gameId: "wk09-min-atl", snapShare: 0.68, targetShare: 0.12, role: "Every-down back; checkdown volume", depth: "84% backfield", recMu: 4.1, recR: 5.6, yprK: 2.9, yprT: 4.6, oppNote: "Vikings rally underneath; screen usage spikes vs two-high shells." },
  // — SUN early: CIN @ BAL —
  { id: "jamarr-chase", name: "Ja'Marr Chase", team: "CIN", pos: "WR", gameId: "wk09-cin-bal", snapShare: 0.91, targetShare: 0.324, role: "Alpha X; league-high target quality", depth: "WR · CIN · #1", recMu: 7.0, recR: 5.21, yprK: 4.38, yprT: 0.17, oppNote: "Double coverage rate ↑ vs BAL" },
  { id: "tee-higgins", name: "Tee Higgins", team: "CIN", pos: "WR", gameId: "wk09-cin-bal", snapShare: 0.78, targetShare: 0.22, injury: "QUESTIONABLE", injuryNote: "Ankle — limited Wednesday", role: "Z boundary; jump-ball complement", depth: "72% boundary", recMu: 5.9, recR: 6.2, yprK: 2.4, yprT: 5.5, oppNote: "Questionable tag compresses route tree if active; see invalidation factors." },
  { id: "jerry-jeudy", name: "Jerry Jeudy", team: "CLE", pos: "WR", gameId: "wk09-cin-bal", snapShare: 0.85, targetShare: 0.25, role: "Primary slot; separation-led volume", depth: "61% slot", recMu: 6.3, recR: 6.6, yprK: 2.3, yprT: 5.3, oppNote: "Cincinnati blitz rate forces hot-route throws; catch radius caps YPR tail." },
  // — SUN early: NYG @ PHI —
  { id: "malik-nabers", name: "Malik Nabers", team: "NYG", pos: "WR", gameId: "wk09-nyg-phi", snapShare: 0.89, targetShare: 0.32, role: "Full-route-tree alpha", depth: "52% boundary · 40% slot", recMu: 8.0, recR: 7.4, yprK: 2.5, yprT: 5.4, oppNote: "Philadelphia zones with Darius Slay travel on early downs; man on third." },
  { id: "aj-brown", name: "A.J. Brown", team: "PHI", pos: "WR", gameId: "wk09-nyg-phi", snapShare: 0.86, targetShare: 0.26, role: "Physical X; middle-field after-catch", depth: "66% boundary", recMu: 6.7, recR: 6.9, yprK: 2.6, yprT: 5.5, oppNote: "Giants single-high looks feed slant/rally YPR; deep shots vs man-pressure rate." },
  { id: "devonta-smith", name: "DeVonta Smith", team: "PHI", pos: "WR", gameId: "wk09-nyg-phi", snapShare: 0.8, targetShare: 0.19, role: "Slim-fast Z; vertical spacing", depth: "69% boundary", recMu: 5.3, recR: 6.1, yprK: 2.4, yprT: 5.4, oppNote: "New York two-high caps aDOT; efficiency skews to intermediate cuts." },
  // — SUN late: NYJ @ MIA —
  { id: "breece-hall", name: "Breece Hall", team: "NYJ", pos: "RB", gameId: "wk09-nyj-mia", snapShare: 0.64, targetShare: 0.14, role: "Three-down back; flats/checkdowns", depth: "82% backfield", recMu: 4.7, recR: 5.3, yprK: 2.8, yprT: 4.7, oppNote: "Miami's fast-flow defense concedes swing passes; red-zone targets episodic." },
  { id: "garrett-wilson", name: "Garrett Wilson", team: "NYJ", pos: "WR", gameId: "wk09-nyj-mia", snapShare: 0.9, targetShare: 0.28, role: "Volume alpha from slot and boundary", depth: "49% boundary · 41% slot", recMu: 7.4, recR: 7.0, yprK: 2.4, yprT: 5.4, oppNote: "Dolphins man-free on Wilson with deep-half help; YPR driven by catch-and-run." },
  { id: "tyreek-hill", name: "Tyreek Hill", team: "MIA", pos: "WR", gameId: "wk09-nyj-mia", snapShare: 0.81, targetShare: 0.24, injury: "QUESTIONABLE", injuryNote: "Wrist — limited all week", role: "Vertical slot; field-tilting speed", depth: "55% slot", recMu: 6.6, recR: 6.2, yprK: 2.2, yprT: 6.0, oppNote: "If active, Jets soft-shell invites crossers; usage monitoring through Saturday." },
  { id: "jaylen-waddle", name: "Jaylen Waddle", team: "MIA", pos: "WR", gameId: "wk09-nyj-mia", snapShare: 0.85, targetShare: 0.22, role: "Complementary speed; middle cuts", depth: "46% boundary · 44% slot", recMu: 6.5, recR: 6.8, yprK: 2.3, yprT: 5.6, oppNote: "New York bracket over the middle moves targets to flat concepts." },
  // — SUN late: KC @ DEN —
  { id: "travis-kelce", name: "Travis Kelce", team: "KC", pos: "TE", gameId: "wk09-kc-den", snapShare: 0.76, targetShare: 0.23, role: "Y-option tight end; chain-mover", depth: "58% inline/slot", recMu: 6.2, recR: 8.6, yprK: 3.4, yprT: 3.4, oppNote: "Denver's zone-match concedes the flat; low-dispersion volume profile." },
  { id: "rashee-rice", name: "Rashee Rice", team: "KC", pos: "WR", gameId: "wk09-kc-den", snapShare: 0.83, targetShare: 0.26, role: "YAC slot; primary option on schedule", depth: "57% slot", recMu: 7.3, recR: 7.6, yprK: 2.6, yprT: 5.2, oppNote: "Broncos rally from zone; yards-after-catch distribution right-skewed." },
  { id: "courtland-sutton", name: "Courtland Sutton", team: "DEN", pos: "WR", gameId: "wk09-kc-den", snapShare: 0.86, targetShare: 0.25, role: "Boundary X; jump-ball specialist", depth: "74% boundary", recMu: 5.2, recR: 5.9, yprK: 2.2, yprT: 5.7, oppNote: "Kansas City corners sit on comebacks; end-zone targets drive the tail." },
  // — SUN late: LAR @ TB —
  { id: "puka-nacua", name: "Puka Nacua", team: "LAR", pos: "WR", gameId: "wk09-lar-tb", snapShare: 0.88, targetShare: 0.28, role: "Possession alpha; middle-of-field", depth: "51% slot", recMu: 8.2, recR: 7.8, yprK: 2.7, yprT: 5.2, oppNote: "Tampa's blitz-man leaves slant windows; target floor elite when healthy." },
  { id: "davante-adams", name: "Davante Adams", team: "LAR", pos: "WR", gameId: "wk09-lar-tb", snapShare: 0.8, targetShare: 0.21, role: "Route-technician boundary Z", depth: "63% boundary", recMu: 6.0, recR: 6.6, yprK: 2.5, yprT: 5.3, oppNote: "Bucs zone-match on early downs; red-zone share concentrated." },
  { id: "mike-evans", name: "Mike Evans", team: "TB", pos: "WR", gameId: "wk09-lar-tb", snapShare: 0.84, targetShare: 0.25, role: "X boundary; deep-ball winner", depth: "76% boundary", recMu: 5.7, recR: 6.4, yprK: 2.4, yprT: 6.1, oppNote: "Rams single-high press invites go-balls; boom-bust catch law." },
  { id: "jalen-mcmillan", name: "Jalen McMillan", team: "TB", pos: "WR", gameId: "wk09-lar-tb", snapShare: 0.72, targetShare: 0.16, role: "Slot speedster; big-play lean", depth: "54% slot", recMu: 4.3, recR: 5.2, yprK: 2.2, yprT: 5.3, oppNote: "Los Angeles soft zone yields crossers; touch count volatile." },
  // — SUN night: SF @ ARI —
  { id: "george-kittle", name: "George Kittle", team: "SF", pos: "TE", gameId: "wk09-sf-ari", snapShare: 0.77, targetShare: 0.22, role: "Y tight end; play-action fulcrum", depth: "71% inline/slot", recMu: 5.8, recR: 8.2, yprK: 3.3, yprT: 3.8, oppNote: "Arizona's light box fuels boot-action targets; consistent floor profile." },
  { id: "jauan-jennings", name: "Jauan Jennings", team: "SF", pos: "WR", gameId: "wk09-sf-ari", snapShare: 0.74, targetShare: 0.19, role: "Slot possession; third-down role", depth: "48% slot", recMu: 5.5, recR: 6.0, yprK: 2.3, yprT: 5.5, oppNote: "Cardinals zone-match concedes sticks routes; moderate dispersion." },
  { id: "marvin-harrison-jr", name: "Marvin Harrison Jr.", team: "ARI", pos: "WR", gameId: "wk09-sf-ari", snapShare: 0.87, targetShare: 0.26, role: "Alpha X; boundary separation", depth: "70% boundary", recMu: 6.4, recR: 6.5, yprK: 2.4, yprT: 5.8, oppNote: "San Francisco's shadow plan with Deommodore Lenoir caps aDOT mix." },
  { id: "trey-mcbride", name: "Trey McBride", team: "ARI", pos: "TE", gameId: "wk09-sf-ari", snapShare: 0.8, targetShare: 0.24, role: "Volume tight end; yards-after-catch", depth: "43% slot · 41% inline", recMu: 7.1, recR: 8.4, yprK: 3.2, yprT: 3.9, oppNote: "49ers funnel to flats vs zone; high-floor reception law." },
  // — MON: BUF @ IND —
  { id: "keon-coleman", name: "Keon Coleman", team: "BUF", pos: "WR", gameId: "wk09-buf-ind", snapShare: 0.76, targetShare: 0.19, role: "Boundary X; shot-play specialist", depth: "77% boundary", recMu: 4.8, recR: 5.5, yprK: 2.2, yprT: 5.9, oppNote: "Indianapolis off-man invites fades; volatile catch distribution." },
  { id: "khalil-shakir", name: "Khalil Shakir", team: "BUF", pos: "WR", gameId: "wk09-buf-ind", snapShare: 0.82, targetShare: 0.23, role: "Slot separator; catch-rate anchor", depth: "72% slot", recMu: 5.9, recR: 7.4, yprK: 2.9, yprT: 4.4, oppNote: "Colts zone-match gives quick-game windows; low-variance profile." },
  { id: "michael-pittman-jr", name: "Michael Pittman Jr.", team: "IND", pos: "WR", gameId: "wk09-buf-ind", snapShare: 0.85, targetShare: 0.24, role: "Possession X; chain-mover", depth: "64% boundary", recMu: 6.1, recR: 6.7, yprK: 2.5, yprT: 5.0, oppNote: "Buffalo soft zone allows curl volume; moderate YPR ceiling." },
  { id: "josh-downs", name: "Josh Downs", team: "IND", pos: "WR", gameId: "wk09-buf-ind", snapShare: 0.78, targetShare: 0.2, role: "Slot separator; option routes", depth: "68% slot", recMu: 5.7, recR: 6.3, yprK: 2.4, yprT: 4.9, oppNote: "Bills bracket slot with nickel help; target quality hinges on man-rate." },
];

/* ---------- NBA players + fitted parameters ----------
   Each market is an NB2 count law. snapShare = share of available
   minutes; targetShare = usage rate (share of team possessions). */
interface NbaSeed {
  id: string;
  name: string;
  team: string;
  pos: "PG" | "SG" | "SF" | "PF" | "C";
  gameId: string;
  snapShare: number;
  targetShare: number;
  injury?: "QUESTIONABLE";
  injuryNote?: string;
  role: string;
  depth: string;
  ptsMu: number;
  ptsR: number;
  rebMu: number;
  rebR: number;
  astMu: number;
  astR: number;
  oppNote: string;
}

export const NBA_SEEDS: NbaSeed[] = [
  { id: "shai-gilgeous-alexander", name: "Shai Gilgeous-Alexander", team: "OKC", pos: "PG", gameId: "nba-okc-den", snapShare: 0.92, targetShare: 0.34, role: "Primary initiator; mid-post volume engine", depth: "38% pick-and-roll · 22% isolation", ptsMu: 32.6, ptsR: 48, rebMu: 5.4, rebR: 9, astMu: 6.6, astR: 10, oppNote: "Denver switches 1-through-4; Christian Braun takes the primary assignment with weak-side help loaded to stop drives." },
  { id: "nikola-jokic", name: "Nikola Jokić", team: "DEN", pos: "C", gameId: "nba-okc-den", snapShare: 0.94, targetShare: 0.31, role: "Hub center; elbow and post distribution", depth: "44% post/elbow · 30% high pick-and-roll", ptsMu: 28.8, ptsR: 38, rebMu: 12.8, rebR: 18, astMu: 10.2, astR: 14, oppNote: "Oklahoma City fronts the post with Chet Holmgren and rotates low man early; passing lanes remain the release valve." },
  { id: "luka-doncic", name: "Luka Dončić", team: "LAL", pos: "PG", gameId: "nba-lal-gsw", snapShare: 0.93, targetShare: 0.36, role: "Ball-dominant initiator; step-back volume", depth: "47% pick-and-roll · 25% isolation", ptsMu: 31.6, ptsR: 42, rebMu: 8.3, rebR: 14, astMu: 8.6, astR: 13, oppNote: "Golden State drops with Draymond Green at the level and funnels to aggressive closeouts; free-throw rate is the swing variable." },
  { id: "stephen-curry", name: "Stephen Curry", team: "GSW", pos: "PG", gameId: "nba-lal-gsw", snapShare: 0.85, targetShare: 0.3, injury: "QUESTIONABLE", injuryNote: "Right ankle — game-time decision", role: "Motion off-guard; relocation shooting", depth: "41% off-screen · 26% pick-and-roll", ptsMu: 25.9, ptsR: 30, rebMu: 4.5, rebR: 8, astMu: 6.1, astR: 10, oppNote: "Los Angeles top-locks the pin-downs with Austin Reaves chasing over the top; if Curry is limited, volume shifts to Young and Podziemski." },
  { id: "giannis-antetokounmpo", name: "Giannis Antetokounmpo", team: "MIL", pos: "PF", gameId: "nba-mil-orl", snapShare: 0.91, targetShare: 0.33, role: "Downhill rim pressure in transition", depth: "52% transition/rim · 24% short roll", ptsMu: 31.0, ptsR: 40, rebMu: 11.6, rebR: 16, astMu: 5.9, astR: 10, oppNote: "Orlando builds the wall with Banchero and Isaac at the nail; the free-throw line is where the projection breathes." },
  { id: "paolo-banchero", name: "Paolo Banchero", team: "ORL", pos: "PF", gameId: "nba-mil-orl", snapShare: 0.88, targetShare: 0.29, role: "Forward hub; bully-drive creation", depth: "39% isolation · 27% post", ptsMu: 24.2, ptsR: 28, rebMu: 7.4, rebR: 12, astMu: 4.9, astR: 9, oppNote: "Milwaukee drops Giannis onto the matchup and packs the paint; kick-out three volume rises when the drive is taken away." },
  { id: "jayson-tatum", name: "Jayson Tatum", team: "BOS", pos: "SF", gameId: "nba-bos-cle", snapShare: 0.9, targetShare: 0.31, role: "Wing scorer; three-level volume", depth: "35% pick-and-roll · 24% spot-up", ptsMu: 27.4, ptsR: 34, rebMu: 8.2, rebR: 13, astMu: 5.6, astR: 10, oppNote: "Cleveland throws long, switching wings with Okoro taking first crack and Mobson shading the drive from the weak side." },
  { id: "darius-garland", name: "Darius Garland", team: "CLE", pos: "PG", gameId: "nba-bos-cle", snapShare: 0.87, targetShare: 0.27, role: "Pick-and-roll guard; screen navigation", depth: "46% pick-and-roll · 21% spot-up", ptsMu: 21.8, ptsR: 26, rebMu: 3.4, rebR: 7, astMu: 7.8, astR: 12, oppNote: "Boston shoots the gap with Derrick White and drops Kristaps Porziņģis to the level; pull-up efficiency decides the ceiling." },
];

/* ---------- players ---------- */
export const PLAYERS: Player[] = [
  ...NFL_SEEDS.map((s) => ({
    id: s.id,
    sport: "nfl" as const,
    name: s.name,
    team: s.team,
    pos: s.pos,
    gameId: s.gameId,
    snapShare: s.snapShare,
    targetShare: s.targetShare,
    injury: s.injury ?? ("OK" as const),
    injuryNote: s.injuryNote,
    role: s.role,
    depth: s.depth,
  })),
  ...NBA_SEEDS.map((s) => ({
    id: s.id,
    sport: "nba" as const,
    name: s.name,
    team: s.team,
    pos: s.pos,
    gameId: s.gameId,
    snapShare: s.snapShare,
    targetShare: s.targetShare,
    injury: s.injury ?? ("OK" as const),
    injuryNote: s.injuryNote,
    role: s.role,
    depth: s.depth,
  })),
];

export interface AnySeed {
  oppNote: string;
  sport: Sport;
}

const SEED_MAP: Record<string, AnySeed> = Object.fromEntries([
  ...NFL_SEEDS.map((s) => [s.id, { oppNote: s.oppNote, sport: "nfl" as const }]),
  ...NBA_SEEDS.map((s) => [s.id, { oppNote: s.oppNote, sport: "nba" as const }]),
]);

export function playerById(id: string): Player | undefined {
  return PLAYERS.find((p) => p.id === id);
}

export function playersForSport(sport: Sport): Player[] {
  return PLAYERS.filter((p) => p.sport === sport);
}

/* ---------- research context (deterministic preview data) ----------
   The research-workspace Context panel mirrors the production
   terminal's context block:
     NFL — target share · air yards share · projected pass rate ·
           opponent pass defense
     NBA — usage · minutes share · projected pace · opponent
           defensive rating
   Values are DERIVED deterministically from the published seeds
   and slate (formulas inline, no RNG), so every render is
   identical and the panel is labeled demonstration data — same
   contract as the recent-game log. */

export interface PlayerContext {
  /** share of team air yards (0-1) — NFL only */
  airYardsShare?: number;
  /** projected team dropback rate (0-1) — NFL only */
  passRateProj?: number;
  /** opponent pass-defense summary — NFL only */
  oppPassDefense?: string;
  /** projected possessions per 48 — NBA only */
  paceProj?: number;
  /** opponent defensive rating, pts/100 — NBA only */
  oppDefRtg?: number;
}

/** stable 32-bit FNV-1a hash — same family as the recent-log seeding */
function fnv1a(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
}

const CONTEXT_CACHE = new Map<string, PlayerContext>();

export function contextFor(playerId: string): PlayerContext {
  const cached = CONTEXT_CACHE.get(playerId);
  if (cached) return cached;
  const player = playerById(playerId);
  const seed = SEED_MAP[playerId];
  let ctx: PlayerContext = {};
  if (player && seed) {
    const game = gameFor(player.gameId);
    const isHome = game.home === player.team;
    const oppAbbr = isHome ? game.away : game.home;
    if (player.sport === "nfl") {
      if (playerId === "jamarr-chase") {
        ctx = {
          airYardsShare: 0.418,
          passRateProj: 0.615,
          oppPassDefense: "28th (vs WR1)",
        };
      } else {
        const nfl = NFL_SEEDS.find((s) => s.id === playerId)!;
        // air-yards share tracks target share scaled by route depth (θ of the
        // Gamma YPR law): deep threats clear a larger share of air yards.
        const depthFactor = 0.85 + nfl.yprT / 11;
        ctx = {
          airYardsShare: Math.min(0.55, player.targetShare * depthFactor),
          // pass rate leans on game environment: total pushes scoring, and the
          // trailing side drops back more.
          passRateProj: Math.min(
            0.68,
            Math.max(
              0.5,
              0.55 + (game.total! - 44.5) * 0.0025 + ((isHome ? -game.spread : game.spread) < 0 ? 0.03 : -0.005)
            )
          ),
          // opponent rank/efficiency derived deterministically from the abbr
          oppPassDefense: (() => {
            const rank = (fnv1a(`def:${oppAbbr}`) % 32) + 1;
            const netYpa = 5.2 + (rank - 1) * 0.045;
            return `${ordinal(rank)} · ${netYpa.toFixed(1)} net Y/A allowed`;
          })(),
        };
      }
    } else {
      ctx = {
        paceProj: 97 + (game.total! - 224) * 0.28,
        oppDefRtg: 104 + (fnv1a(`drtg:${oppAbbr}`) % 25) * 0.5,
      };
    }
  }
  CONTEXT_CACHE.set(playerId, ctx);
  return ctx;
}

/* ---------- projections (one law per player × market) ---------- */
const PRODUCED_AT = "2026-11-04T06:40:00-05:00";

const NFL_PROJECTIONS: Projection[] = NFL_SEEDS.flatMap((s) => {
  const recLaw: DistLaw = { kind: "negbin", nb: { r: s.recR, mu: s.recMu } };
  const ydsLaw: DistLaw = {
    kind: "compound",
    nb: { r: s.recR, mu: s.recMu },
    gamma: { k: s.yprK, theta: s.yprT },
  };
  return [
    {
      playerId: s.id,
      market: "receptions" as MarketKey,
      law: recLaw,
      modelVersion: MODEL_VERSION,
      dataWindow: DATA_WINDOW,
      producedAt: PRODUCED_AT,
      snapshotKey: `snapshots/nfl/2026/wk09/${s.id}-receptions.json`,
    },
    {
      playerId: s.id,
      market: "receiving_yards" as MarketKey,
      law: ydsLaw,
      modelVersion: MODEL_VERSION,
      dataWindow: DATA_WINDOW,
      producedAt: PRODUCED_AT,
      snapshotKey: `snapshots/nfl/2026/wk09/${s.id}-receiving-yards.json`,
    },
  ];
});

const NBA_PROJECTIONS: Projection[] = NBA_SEEDS.flatMap((s) => {
  const law = (mu: number, r: number, market: MarketKey, slug: string): Projection => ({
    playerId: s.id,
    market,
    law: { kind: "negbin", nb: { r, mu } },
    modelVersion: MODEL_VERSION,
    dataWindow: DATA_WINDOW,
    producedAt: PRODUCED_AT,
    snapshotKey: `snapshots/nba/2026/${slug}/${s.id}-${market}.json`,
  });
  return [
    law(s.ptsMu, s.ptsR, "points", "nov06"),
    law(s.rebMu, s.rebR, "rebounds", "nov06"),
    law(s.astMu, s.astR, "assists", "nov06"),
  ];
});

export const PROJECTIONS: Projection[] = [...NFL_PROJECTIONS, ...NBA_PROJECTIONS];

export function projectionFor(playerId: string, market: MarketKey): Projection | undefined {
  return PROJECTIONS.find((p) => p.playerId === playerId && p.market === market);
}

/* ---------- captured quotes ----------
   line = model median + fixed offset on the market's posting grid,
   so the captured market always sits at a defined divergence from
   the model. status follows the fail-closed contract.            */

interface QuoteSeed {
  id: string;
  market: MarketKey;
  offset: number; // line units added to the model median
  overOdds: number;
  underOdds: number;
  status: "OBSERVED_UNVERIFIED" | "VERIFIED" | "STALE";
  source?: string;
  /** hours before SNAPSHOT_AT that the quote was captured */
  capturedHoursAgo: number;
  verifiedAgainst?: string;
}

const Q = (
  market: MarketKey,
  offset: number,
  overOdds: number,
  underOdds: number,
  status: QuoteSeed["status"],
  capturedHoursAgo: number
): QuoteSeed => ({
  id: `${market}`,
  market,
  offset,
  overOdds,
  underOdds,
  status,
  capturedHoursAgo,
});

/** hours before SNAPSHOT_AT for each capture cohort */
const CAPTURE_SOURCES = {
  primary: "Book A · primary capture feed",
  verification: "Book B · verification feed",
};

const QUOTE_SEEDS: Record<string, QuoteSeed[]> = {
  "dk-metcalf": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.2),
    Q("receiving_yards", -6, -110, -110, "OBSERVED_UNVERIFIED", 3.2),
  ],
  "george-pickens": [
    Q("receptions", -0.5, -115, -105, "OBSERVED_UNVERIFIED", 2.1),
    // yards: market not currently posted
  ],
  "zay-flowers": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.6),
    Q("receiving_yards", 5, -105, -115, "OBSERVED_UNVERIFIED", 2.4),
  ],
  "mark-andrews": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.6),
    Q("receiving_yards", -4, -115, -105, "OBSERVED_UNVERIFIED", 2.4),
  ],
  "amon-ra-st-brown": [
    Q("receptions", -0.5, -115, -105, "OBSERVED_UNVERIFIED", 5.1),
    Q("receiving_yards", 0, -110, -110, "OBSERVED_UNVERIFIED", 5.1),
  ],
  "sam-laporta": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.2),
    Q("receiving_yards", -3, -105, -115, "OBSERVED_UNVERIFIED", 2.2),
  ],
  "romeo-doubs": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.2),
    // yards MODEL_ONLY
  ],
  "justin-jefferson": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 5.4),
    Q("receiving_yards", -2.5, -115, -105, "OBSERVED_UNVERIFIED", 5.4),
  ],
  "drake-london": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.9),
    Q("receiving_yards", -5, -110, -110, "OBSERVED_UNVERIFIED", 4.9),
  ],
  "kyle-pitts": [
    Q("receptions", -1, -105, -115, "STALE", 74),
    Q("receiving_yards", -8, -110, -110, "STALE", 74),
  ],
  "bijan-robinson": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.8),
    // yards UNAVAILABLE
  ],
  "jamarr-chase": [
    Q("receptions", 0.5, -105, -115, "OBSERVED_UNVERIFIED", 1.7),
    Q("receiving_yards", -2.5, -110, -110, "OBSERVED_UNVERIFIED", 1.7),
  ],
  "tee-higgins": [
    Q("receptions", 1.5, -115, -105, "OBSERVED_UNVERIFIED", 2.6),
    Q("receiving_yards", 8, -110, -110, "OBSERVED_UNVERIFIED", 2.6),
  ],
  "jerry-jeudy": [
    Q("receptions", -0.5, -110, -110, "STALE", 62),
    Q("receiving_yards", 4, -115, -105, "STALE", 62),
  ],
  "malik-nabers": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.2),
    Q("receiving_yards", -7, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
  ],
  "aj-brown": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.0),
    Q("receiving_yards", 0, -105, -115, "OBSERVED_UNVERIFIED", 3.0),
  ],
  "devonta-smith": [
    Q("receptions", 1, -110, -110, "OBSERVED_UNVERIFIED", 3.0),
    Q("receiving_yards", 5, -115, -105, "OBSERVED_UNVERIFIED", 3.0),
  ],
  "breece-hall": [
    Q("receptions", -0.5, -115, -105, "OBSERVED_UNVERIFIED", 2.7),
    Q("receiving_yards", -10, -110, -110, "OBSERVED_UNVERIFIED", 2.7),
  ],
  "garrett-wilson": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.4),
    Q("receiving_yards", -6, -110, -110, "OBSERVED_UNVERIFIED", 4.4),
  ],
  "tyreek-hill": [
    Q("receptions", -1, -110, -110, "OBSERVED_UNVERIFIED", 2.9),
    // yards UNAVAILABLE (pulled pending injury resolution)
  ],
  "jaylen-waddle": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.9),
    Q("receiving_yards", -7, -110, -110, "OBSERVED_UNVERIFIED", 4.1),
  ],
  "travis-kelce": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.8),
    Q("receiving_yards", -4, -110, -110, "OBSERVED_UNVERIFIED", 2.3),
  ],
  "rashee-rice": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.8),
    Q("receiving_yards", -5, -110, -110, "OBSERVED_UNVERIFIED", 2.3),
  ],
  "courtland-sutton": [
    Q("receptions", -0.5, -115, -105, "OBSERVED_UNVERIFIED", 3.4),
    Q("receiving_yards", 6, -110, -110, "OBSERVED_UNVERIFIED", 3.4),
  ],
  "puka-nacua": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 5.2),
    Q("receiving_yards", -2.5, -110, -110, "OBSERVED_UNVERIFIED", 5.2),
  ],
  "davante-adams": [
    // both MODEL_ONLY — no quote captured yet this week
  ],
  "mike-evans": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.6),
    Q("receiving_yards", 4, -110, -110, "OBSERVED_UNVERIFIED", 3.6),
  ],
  "jalen-mcmillan": [
    Q("receptions", -0.5, -110, -110, "STALE", 68),
    Q("receiving_yards", -5, -115, -105, "STALE", 68),
  ],
  "george-kittle": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.7),
    Q("receiving_yards", 0, -110, -110, "OBSERVED_UNVERIFIED", 4.7),
  ],
  "jauan-jennings": [
    // both MODEL_ONLY
  ],
  "marvin-harrison-jr": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.9),
    Q("receiving_yards", 3, -110, -110, "OBSERVED_UNVERIFIED", 3.9),
  ],
  "trey-mcbride": [
    Q("receptions", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.7),
    Q("receiving_yards", -4, -105, -115, "OBSERVED_UNVERIFIED", 2.6),
  ],
  "keon-coleman": [
    Q("receptions", -0.5, -110, -110, "STALE", 65),
    // yards MODEL_ONLY
  ],
  "khalil-shakir": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
    Q("receiving_yards", 3, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
  ],
  "michael-pittman-jr": [
    Q("receptions", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
    Q("receiving_yards", 0, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
  ],
  "josh-downs": [
    Q("receptions", -0.5, -110, -110, "STALE", 59),
    Q("receiving_yards", -6, -110, -110, "OBSERVED_UNVERIFIED", 2.5),
  ],
  // NBA — Nov 6 slate
  "shai-gilgeous-alexander": [
    Q("points", 0.5, 100, -120, "OBSERVED_UNVERIFIED", 3.4),
    Q("rebounds", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.4),
    Q("assists", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 3.4),
  ],
  "nikola-jokic": [
    Q("points", -1.5, -110, -110, "OBSERVED_UNVERIFIED", 4.1),
    Q("rebounds", 0.5, -115, -105, "OBSERVED_UNVERIFIED", 4.1),
    Q("assists", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.2),
  ],
  "luka-doncic": [
    Q("points", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.8),
    Q("rebounds", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.4),
    // assists MODEL_ONLY
  ],
  "stephen-curry": [
    Q("points", 1.5, -110, -110, "STALE", 71),
    // rebounds UNAVAILABLE
    Q("assists", 0.5, -110, -110, "STALE", 71),
  ],
  "giannis-antetokounmpo": [
    Q("points", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.0),
    Q("rebounds", -0.5, -105, -115, "OBSERVED_UNVERIFIED", 4.0),
    Q("assists", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.0),
  ],
  "paolo-banchero": [
    Q("points", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.6),
    Q("rebounds", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.6),
    Q("assists", 0.5, -115, -105, "OBSERVED_UNVERIFIED", 2.6),
  ],
  "jayson-tatum": [
    Q("points", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 4.6),
    Q("rebounds", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.3),
    Q("assists", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.3),
  ],
  "darius-garland": [
    Q("points", 0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.4),
    // rebounds MODEL_ONLY
    Q("assists", -0.5, -110, -110, "OBSERVED_UNVERIFIED", 2.4),
  ],
};

/** markets explicitly not offered right now */
const UNAVAILABLE_MARKETS: Array<{ playerId: string; market: MarketKey; reason: string }> = [
  { playerId: "tyreek-hill", market: "receiving_yards", reason: "Market pulled pending injury designation" },
  { playerId: "bijan-robinson", market: "receiving_yards", reason: "No line posted at capture time" },
  { playerId: "george-pickens", market: "receiving_yards", reason: "No line posted at capture time" },
  { playerId: "stephen-curry", market: "rebounds", reason: "Market pulled pending injury designation" },
];

function hoursBeforeISO(hours: number): string {
  const t = new Date(SNAPSHOT_AT).getTime() - hours * 3600_000;
  return new Date(t).toISOString();
}

function snapLine(median: number, market: MarketKey, offset: number): number {
  // sportsbooks post half-step grids; snap the captured line to the nearest 0.5
  const step = 0.5;
  return Math.round((median + offset) / step) * step;
}

export const QUOTES: Quote[] = [];
export const UNAVAILABLE: Record<string, string> = {};
for (const u of UNAVAILABLE_MARKETS) {
  UNAVAILABLE[`${u.playerId}:${u.market}`] = u.reason;
}
for (const [playerId, seeds] of Object.entries(QUOTE_SEEDS)) {
  for (const seed of seeds) {
    const proj = projectionFor(playerId, seed.market)!;
    const median =
      proj.law.kind === "negbin"
        ? negBinMedian(proj.law.nb)
        : compoundMedian({ r: proj.law.nb.r, mu: proj.law.nb.mu, k: proj.law.gamma!.k, theta: proj.law.gamma!.theta });
    QUOTES.push({
      playerId,
      market: seed.market,
      line: snapLine(median, seed.market, seed.offset),
      overOdds: seed.overOdds,
      underOdds: seed.underOdds,
      source: CAPTURE_SOURCES.primary,
      capturedAt: hoursBeforeISO(seed.capturedHoursAgo),
      status: seed.status,
      verifiedAgainst: undefined,
    });
  }
}

export function quoteFor(playerId: string, market: MarketKey): Quote | undefined {
  return QUOTES.find((q) => q.playerId === playerId && q.market === market);
}

/* ---------- capture events (notification feed) ---------- */
export const CAPTURE_EVENTS: CaptureEvent[] = [
  { id: "ev1", at: hoursBeforeISO(0.6), kind: "verification", text: "Verification pass complete — 13 NFL Week 9 quotes verified against Book B" },
  { id: "ev1b", at: hoursBeforeISO(1.2), kind: "capture", text: "NBA Nov 6 quote capture — 19 markets across 4 games (Book A)" },
  { id: "ev2", at: hoursBeforeISO(1.8), kind: "capture", text: "NFL Week 9 quote capture — 54 markets across 10 games (Book A)" },
  { id: "ev3", at: hoursBeforeISO(2.4), kind: "system", text: "Stale-capture sweep — 7 quotes flagged STALE and demoted from current context" },
  { id: "ev4", at: hoursBeforeISO(26), kind: "grades", text: "Week 8 grades posted — 62 markets settled, full-board CLV updated" },
  { id: "ev5", at: hoursBeforeISO(164), kind: "model", text: "Model v3.2.1 deployed — game-script conditioning on spread and total" },
];

/* ---------- deterministic snapshot label ---------- */
export const SNAPSHOT_LABEL = "Wed Nov 4, 2026 · 2:15 PM ET";

export { SEED_MAP };
