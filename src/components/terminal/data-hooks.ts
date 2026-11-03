"use client";

// Terminal data hooks — thin typed fetchers over the API routes.

import { useCallback, useEffect, useRef, useState } from "react";

export interface GameDTO {
  id: string;
  league: string;
  season: number;
  week: number | null;
  startTime: string;
  state: string;
  detail: string | null;
  homeTeam: string;
  homeScore: number | null;
  awayTeam: string;
  awayScore: number | null;
  venue: string | null;
  broadcast: string | null;
  oddsLine: string | null;
}

export interface PlayerDTO {
  id: string;
  league: string;
  name: string;
  team: string | null;
  position: string | null;
  jersey: number | null;
  headshot: string | null;
  source: string;
  statsSummary: Record<string, number> | null;
  formSummary?: Array<Record<string, unknown>> | null;
}

export interface PropDTO {
  id: string;
  slate: string;
  league: string;
  market: string;
  line: number;
  book: string;
  overOdds: number | null;
  underOdds: number | null;
  bestSide: string | null;
  lean: string | null;
  verified: boolean;
  observedAt: string;
  player: { id: string; name: string; team: string | null; position: string | null; headshot: string | null };
  game: { id: string; startTime: string; state: string; homeTeam: string; awayTeam: string; slug: string | null } | null;
  fairLine?: number | null;
  probWin?: number | null;
  fairOdds?: number | null;
  ev?: number | null;
  kelly?: number | null;
}

export interface GamesResp { league: string; count: number; games: GameDTO[] }
export interface PlayersResp { tier: string; count: number; formIncluded: boolean; players: PlayerDTO[] }
export interface PropsResp {
  tier: string;
  slate: string | null;
  count: number;
  totalForSlate: number;
  teaser: boolean;
  delayMinutes: number;
  exportEnabled: boolean;
  props: PropDTO[];
}

export type Tier = "free" | "pro";

function usePoll<T>(url: string | null, intervalMs: number, rev: unknown = null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(!!url);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef(url);
  urlRef.current = url;

  const refresh = useCallback(async () => {
    const u = urlRef.current;
    if (!u) return;
    try {
      const res = await fetch(u, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as T);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(t);
  }, [url, refresh, intervalMs, rev]);

  return { data, loading, error, refresh };
}

export function useGames(league: string, tier: Tier) {
  return usePoll<GamesResp>(`/api/games?league=${league}`, 60_000, tier);
}

export function usePlayers(league: string, search: string, tier: Tier) {
  const q = search.trim() ? `&search=${encodeURIComponent(search.trim())}` : "";
  return usePoll<PlayersResp>(`/api/players?league=${league}&limit=80${q}`, 120_000, tier);
}

export function useProps(slate: string | null, tier: Tier) {
  // no slate -> /api/props picks the latest slate server-side
  const url = slate ? `/api/props?slate=${encodeURIComponent(slate)}` : "/api/props";
  return usePoll<PropsResp>(url, 60_000, tier);
}

export function useTier() {
  const [tier, setTierState] = useState<Tier>("free");
  const [demoTier, setDemoTier] = useState(false);
  const [pending, setPending] = useState(false);

  // authoritative state comes from the server: in production (demo off)
  // it always resolves to free until real auth is wired
  useEffect(() => {
    let alive = true;
    fetch("/api/tier")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive || !d) return;
        if (d.tier === "pro") setTierState("pro");
        setDemoTier(Boolean(d.demoTier));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const setTier = useCallback(
    async (next: Tier) => {
      if (!demoTier) return; // production: tier comes from auth, not a toggle
      setPending(true);
      try {
        const res = await fetch("/api/tier", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tier: next }),
        });
        if (res.ok) setTierState(next);
      } finally {
        setPending(false);
      }
    },
    [demoTier],
  );

  return { tier, setTier, pending, demoTier };
}
