"use client";

/* ============================================================
   PropStein — app state
   Hash router + board filters + saved research, all client-side
   within the single deployed route. Board filter state survives
   detail navigation (drawer or player page) by design.
   ============================================================ */

import { create } from "zustand";
import type { MarketKey, EvidenceStatus, Sport } from "./types";
import { MARKET_KEYS_BY_SPORT } from "./types";
import { playerById } from "./data";

export type ViewName =
  | "overview"
  | "markets"
  | "players"
  | "player"
  | "performance"
  | "methodology"
  | "boundaries"
  | "saved"
  | "status404";

export interface Route {
  view: ViewName;
  /** league context for overview / markets / players (deep-linkable) */
  sport?: Sport;
  /** player id when view === "player" */
  playerId?: string;
  /** market when view === "player" */
  market?: MarketKey;
  /** optional deep-link market for the board */
  boardMarket?: MarketKey;
}

const MARKET_KEYS = ["receptions", "receiving_yards", "points", "rebounds", "assists"] as const;
type AnyMarket = (typeof MARKET_KEYS)[number];

function isMarketKey(v: string | undefined): v is AnyMarket {
  return !!v && (MARKET_KEYS as readonly string[]).includes(v);
}

/** default market for a player — the flagship receiving market in the NFL,
    points in the NBA. */
export function defaultMarketFor(playerId: string): MarketKey {
  const player = playerById(playerId);
  return player ? MARKET_KEYS_BY_SPORT[player.sport][0] : "receptions";
}

export function parseHash(hash: string): Route {
  const clean = hash.replace(/^#\/?/, "");
  const parts = clean.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.length === 0) return { view: "overview", sport: "nfl" };

  // optional leading sport segment: #/nba/markets, #/nfl/overview
  let sport: Sport | undefined;
  if (parts[0] === "nba" || parts[0] === "nfl") {
    sport = parts[0];
    parts.shift();
    if (parts.length === 0) return { view: "overview", sport };
  }

  switch (parts[0]) {
    case "overview":
      return { view: "overview", sport: sport ?? "nfl" };
    case "markets": {
      const boardMarket = isMarketKey(parts[1]) ? parts[1] : undefined;
      return { view: "markets", sport: sport ?? "nfl", boardMarket };
    }
    case "players":
      return { view: "player", playerId: "jamarr-chase", market: "receiving_yards", sport: sport ?? "nfl" };
    case "player": {
      const playerId = parts[1];
      if (!playerId) return { view: "players", sport: sport ?? "nfl" };
      const market = isMarketKey(parts[2]) ? parts[2] : undefined;
      return { view: "player", playerId, market };
    }
    case "performance":
    case "audit":
      return { view: "performance" };
    case "research":
      if (parts[1] === "methodology") return { view: "methodology" };
      if (parts[1] === "value-boundaries") return { view: "boundaries" };
      return { view: "status404" };
    case "saved":
      return { view: "saved" };
    default:
      return { view: "status404", sport };
  }
}

export function routeToHash(route: Route): string {
  const prefix = route.sport === "nba" ? "nba/" : "";
  switch (route.view) {
    case "overview":
      return `#/${prefix}overview`;
    case "markets":
      return `#/${prefix}markets${route.boardMarket ? `/${route.boardMarket}` : ""}`;
    case "players":
      return `#/${prefix}players`;
    case "player":
      return `#/player/${route.playerId}/${route.market ?? defaultMarketFor(route.playerId ?? "")}`;
    case "performance":
      return "#/performance";
    case "methodology":
      return "#/research/methodology";
    case "boundaries":
      return "#/research/value-boundaries";
    case "saved":
      return "#/saved";
    default:
      return `#/${prefix}overview`;
  }
}

/* ---------- board filters ---------- */

export interface BoardFilters {
  query: string;
  market: MarketKey | "all";
  statuses: Set<EvidenceStatus>;
  gameSlot: string | "all";
  sortKey: "divergence" | "volume" | "player" | "status";
  sortDir: "desc" | "asc";
}

export interface AppState {
  route: Route;
  /** board detail drawer — keeps board state intact while open */
  drawer: { playerId: string; market: MarketKey } | null;
  searchOpen: boolean;
  filters: BoardFilters;
  savedPlayers: string[];
  recentSearches: string[];
  /** restore scroll positions when returning to the board */
  boardScrollY: number;

  setRoute: (route: Route) => void;
  /** switch league context, preserving the current view when it is league-scoped */
  setSport: (sport: Sport) => void;
  openDrawer: (playerId: string, market: MarketKey) => void;
  closeDrawer: () => void;
  setSearchOpen: (open: boolean) => void;
  setFilters: (patch: Partial<BoardFilters>) => void;
  toggleSaved: (playerId: string) => void;
  addRecentSearch: (q: string) => void;
  setBoardScrollY: (y: number) => void;
}

const DEFAULT_FILTERS: BoardFilters = {
  query: "",
  market: "all",
  statuses: new Set<EvidenceStatus>(),
  gameSlot: "all",
  sortKey: "divergence",
  sortDir: "desc",
};

export const useApp = create<AppState>((set, get) => ({
  route: { view: "overview" },
  drawer: null,
  searchOpen: false,
  filters: DEFAULT_FILTERS,
  savedPlayers: [],
  recentSearches: [],
  boardScrollY: 0,

  setRoute: (route) => {
    const hash = routeToHash(route);
    if (typeof window !== "undefined") {
      if (window.location.hash !== hash) {
        // hashchange listener in initFromHash updates the store and resets scroll
        window.location.hash = hash;
        return;
      }
    }
    set({ route, drawer: null });
  },
  setSport: (sport) => {
    const { route } = get();
    const leagueScoped =
      route.view === "overview" || route.view === "markets" || route.view === "players";
    if (leagueScoped) {
      get().setRoute({ ...route, sport, boardMarket: undefined });
    } else {
      set({ route: { ...route, sport } });
    }
  },
  openDrawer: (playerId, market) => set({ drawer: { playerId, market } }),
  closeDrawer: () => set({ drawer: null }),
  setSearchOpen: (open) => set({ searchOpen: open }),
  setFilters: (patch) => set((s) => ({ filters: { ...s.filters, ...patch } })),
  toggleSaved: (playerId) =>
    set((s) => ({
      savedPlayers: s.savedPlayers.includes(playerId)
        ? s.savedPlayers.filter((p) => p !== playerId)
        : [...s.savedPlayers, playerId],
    })),
  addRecentSearch: (q) =>
    set((s) => ({
      recentSearches: [q, ...s.recentSearches.filter((x) => x !== q)].slice(0, 6),
    })),
  setBoardScrollY: (y) => set({ boardScrollY: y }),
}));

/** Initialize store from the current hash (client mount only). */
export function initFromHash() {
  if (typeof window === "undefined") return;
  const route = parseHash(window.location.hash);
  useApp.setState({ route });
  const onHash = () => {
    useApp.setState({ route: parseHash(window.location.hash), drawer: null });
    window.scrollTo({ top: 0 });
  };
  window.addEventListener("hashchange", onHash);
}
