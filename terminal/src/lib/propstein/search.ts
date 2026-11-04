/* PropStein — unified command search index.
   One ⌘K index across players, markets, research pages, and
   terminal destinations. No competing search surfaces. */

import { getBoard } from "./derive";
import { GAMES } from "./data";
import { MARKET_META, MARKET_KEYS_BY_SPORT, type Sport } from "./types";

export interface SearchItem {
  id: string;
  group: "Players" | "Markets" | "Research" | "Go to";
  title: string;
  subtitle: string;
  /** hash target */
  target: string;
  keywords: string;
}

let cachedIndex: SearchItem[] | null = null;

function periodLabel(sport: Sport): string {
  return sport === "nfl" ? "NFL WK 9" : "NBA Nov 6";
}

export function searchIndex(): SearchItem[] {
  if (cachedIndex) return cachedIndex;
  const items: SearchItem[] = [];

  // destinations
  const destinations: Array<[string, string, string]> = [
    ["Overview", "Research workspace — slate, model status, discovery", "#/overview"],
    ["NBA overview", "NBA Nov 6 slate — points, rebounds, assists", "#/nba/overview"],
    ["Market board", "NFL Week 9 receiving markets", "#/markets"],
    ["NBA market board", "NBA Nov 6 points · rebounds · assists", "#/nba/markets"],
    ["Player research index", "Browse modeled players", "#/players"],
    ["Performance & audit", "Full-board CLV, calibration, governance", "#/performance"],
    ["Saved research", "Your watchlist", "#/saved"],
  ];
  for (const [title, subtitle, target] of destinations) {
    items.push({ id: `go-${title}`, group: "Go to", title, subtitle, target, keywords: title.toLowerCase() });
  }

  // research pages
  const research: Array<[string, string, string]> = [
    ["Methodology", "Negative Binomial · Gamma · compound law — how the model works", "#/research/methodology"],
    ["Value boundaries", "How no-value bands are derived from prices and the model", "#/research/value-boundaries"],
    ["Evidence & verification states", "What VERIFIED, OBSERVED and STALE mean", "#/research/methodology#evidence"],
    ["Model version timeline", "v2.4.1 → v3.2.1 changes and deployment dates", "#/performance"],
  ];
  for (const [title, subtitle, target] of research) {
    items.push({ id: `res-${title}`, group: "Research", title, subtitle, target, keywords: `${title} ${subtitle}`.toLowerCase() });
  }

  // players (one entry per player, landing on their league's default market)
  for (const row of getBoard()) {
    const defaultMarket = MARKET_KEYS_BY_SPORT[row.player.sport][0];
    if (row.market !== defaultMarket) continue;
    const game = GAMES.find((g) => g.id === row.player.gameId)!;
    const isHome = row.player.team === game.home;
    items.push({
      id: `player-${row.player.id}`,
      group: "Players",
      title: row.player.name,
      subtitle: `${row.player.pos} · ${row.player.team} ${isHome ? "vs" : "at"} ${isHome ? game.away : game.home} · ${periodLabel(row.player.sport)}`,
      target: `#/player/${row.player.id}/${defaultMarket}`,
      keywords: `${row.player.name} ${row.player.team} ${row.player.pos} ${row.player.sport === "nba" ? "basketball nba point guard center forward" : "receiver tight end running back nfl"}`.toLowerCase(),
    });
  }

  // markets (player × market)
  for (const row of getBoard()) {
    const meta = MARKET_META[row.market];
    const fairLabel =
      row.market === "receptions" || row.market === "points" || row.market === "rebounds" || row.market === "assists"
        ? row.fairLine.toFixed(1)
        : row.fairLine.toFixed(1);
    items.push({
      id: `market-${row.key}`,
      group: "Markets",
      title: `${row.player.name} — ${meta.label}`,
      subtitle: `${meta.sport.toUpperCase()} · Fair ${fairLabel} · ${row.quote ? `captured line ${row.quote.line}` : "model only"}`,
      target: `#/player/${row.player.id}/${row.market}`,
      keywords: `${row.player.name} ${meta.label} ${meta.short} ${row.player.team} ${meta.sport}`.toLowerCase(),
    });
  }

  cachedIndex = items;
  return items;
}

export interface SearchHit extends SearchItem {
  score: number;
}

export function runSearch(query: string, limit = 12): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const terms = q.split(/\s+/);
  const hits: SearchHit[] = [];
  for (const item of searchIndex()) {
    const hay = `${item.title} ${item.keywords}`.toLowerCase();
    let score = 0;
    let allMatch = true;
    for (const t of terms) {
      if (item.title.toLowerCase().includes(t)) score += 3;
      else if (hay.includes(t)) score += 1;
      else {
        allMatch = false;
        break;
      }
    }
    if (allMatch) {
      score += item.group === "Players" ? 1.5 : item.group === "Markets" ? 0.5 : 0;
      hits.push({ ...item, score });
    }
  }
  hits.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title));
  return hits.slice(0, limit);
}
