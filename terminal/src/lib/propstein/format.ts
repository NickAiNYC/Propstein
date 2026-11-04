/* PropStein — formatting utilities.
   All times relative to the fixed snapshot instant (never Date.now()
   during render — hydration-safe and honest about capture times). */

import { SNAPSHOT_AT } from "./types";

const SNAPSHOT_MS = new Date(SNAPSHOT_AT).getTime();

/** "2.1h" / "3d 4h" style age, computed against the snapshot instant. */
export function ageHours(iso: string): number {
  return (SNAPSHOT_MS - new Date(iso).getTime()) / 3_600_000;
}

export function formatAge(iso: string): string {
  const h = ageHours(iso);
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
  if (h < 24) return `${h.toFixed(h < 10 ? 1 : 0)}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${Math.round(h % 24)}h`;
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  });
}

export function formatKickoff(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
}

/** Compact slate-card kickoff: "Nov 8 · 1:00 PM" (ET). */
export function formatKickoffShort(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
  const time = d.toLocaleString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  return `${date} · ${time} ET`;
}

/** Quantitative values: fixed decimals, tabular-friendly. */
export function fmt(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(decimals);
}

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value).toString();
}

export function fmtPct(p: number | null | undefined, decimals = 1): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(decimals)}%`;
}

/** Signed value with explicit + for positive — used for divergences. */
export function fmtSigned(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = value.toFixed(decimals);
  return value > 0 ? `+${s}` : s;
}

export function fmtOdds(american: number): string {
  return american > 0 ? `+${american}` : `${american}`;
}

export function fmtMarketLine(line: number, market: "receptions" | "receiving_yards"): string {
  // market lines: receptions on half steps, yards on 2.5 steps
  return market === "receptions" ? line.toFixed(1) : line.toFixed(1);
}

/** Team chip: "MIN · at ATL" style context. */
export function matchupLabel(team: string, opponent: string, homeTeam: string): string {
  return team === homeTeam ? `vs ${opponent}` : `at ${opponent}`;
}
