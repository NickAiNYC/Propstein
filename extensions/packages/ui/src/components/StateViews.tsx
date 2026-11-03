/**
 * PropStein Live Sniper — Interaction State Views (spec §11).
 * Complete, specific views for all required states. No empty white panels,
 * no generic error messages, no indefinite loading indicators.
 */
import type { SignalSnapshot } from "@propstein/core";

export type PanelViewKind =
  | "no-supported-tab"
  | "ready-to-start"
  | "permission-not-granted"
  | "no-markets-visible"
  | "market-being-identified"
  | "verified-match"
  | "positive-ev"
  | "negative-ev"
  | "suspended-market"
  | "quote-expired"
  | "model-unavailable"
  | "subscription-expired"
  | "network-disconnected"
  | "site-layout-changed"
  | "unsupported-sportsbook"
  | "rate-limit-reached";

export interface StateViewProps {
  kind: PanelViewKind;
  snapshots?: SignalSnapshot[];
  onAction?: () => void;
  actionLabel?: string;
  detail?: string;
}

const COPY: Record<PanelViewKind, { title: string; body: string; tone: string }> = {
  "no-supported-tab": {
    title: "NO SUPPORTED TAB OPEN",
    body: "Open a supported live-market page (or the DemoBook fixture) in the active tab, then start monitoring. Live Sniper only ever reads the tab you are looking at.",
    tone: "neutral",
  },
  "ready-to-start": {
    title: "READY TO MONITOR",
    body: "A supported live-market tab is active. Press START MONITORING to begin reading its visible markets — Live Sniper only ever reads the tab you are looking at.",
    tone: "live",
  },
  "permission-not-granted": {
    title: "BROWSER ACCESS NOT GRANTED",
    body: "Site-level access for this origin has not been granted. Live Sniper requests per-site permission only — no broad host access, and you can revoke it at any time in Settings.",
    tone: "warn",
  },
  "no-markets-visible": {
    title: "NO MARKETS CURRENTLY VISIBLE",
    body: "The page is supported, but no market cards are inside the current viewport. Scroll the market list into view — detection runs only on what you can actually see.",
    tone: "neutral",
  },
  "market-being-identified": {
    title: "IDENTIFYING VISIBLE MARKETS",
    body: "Reading the visible market cards and binding them to PropStein's event and player registry. This typically completes within a second of a page change.",
    tone: "live",
  },
  "verified-match": {
    title: "VERIFIED MODEL MATCH",
    body: "The visible market is matched to a modeled player and event. Probabilities below are model estimates, not guarantees — see the confidence label on each card.",
    tone: "positive",
  },
  "positive-ev": {
    title: "POSITIVE ESTIMATED VALUE",
    body: "Estimated EV exceeds your threshold after the uncertainty haircut. This is an estimate of expected value — not a promise of profit. Prices shown are observed, not executable.",
    tone: "positive",
  },
  "negative-ev": {
    title: "NO POSITIVE ESTIMATED VALUE",
    body: "All visible markets price below your EV threshold at current model probabilities. Nothing is alerted — monitoring continues.",
    tone: "neutral",
  },
  "suspended-market": {
    title: "MARKET SUSPENDED",
    body: "The sportsbook has suspended this market. Signals are withdrawn immediately; no stale price is ever presented as actionable.",
    tone: "warn",
  },
  "quote-expired": {
    title: "QUOTE EXPIRED",
    body: "The displayed price has aged beyond its market-specific freshness limit. The signal is withdrawn until a new quote is observed on screen.",
    tone: "warn",
  },
  "model-unavailable": {
    title: "NO MODEL COVERAGE",
    body: "PropStein does not yet have calibrated coverage for this market. We will not substitute a full-game estimate for a drive-level probability, and we never fabricate confidence.",
    tone: "warn",
  },
  "subscription-expired": {
    title: "PRO SUBSCRIPTION REQUIRED",
    body: "Your PropStein membership is no longer active. Protected model responses fail closed until the subscription is restored — the panel keeps working in preview mode.",
    tone: "warn",
  },
  "network-disconnected": {
    title: "NETWORK DISCONNECTED",
    body: "The intelligence backend is unreachable. Local detection continues; model-backed values pause. Reconnection retries with exponential backoff.",
    tone: "warn",
  },
  "site-layout-changed": {
    title: "SITE LAYOUT CHANGED",
    body: "The adapter could not confidently identify market cards on this page. No markets are reported rather than risk invented matches. An adapter update will restore detection.",
    tone: "warn",
  },
  "unsupported-sportsbook": {
    title: "UNSUPPORTED SPORTSBOOK",
    body: "This site has no enabled adapter. DraftKings and FanDuel page detection ships disabled pending authorization; the licensed data path remains the PropStein terminal.",
    tone: "neutral",
  },
  "rate-limit-reached": {
    title: "RATE LIMIT REACHED",
    body: "Your account's evaluation quota is temporarily exhausted. Monitoring pauses for the quota window and resumes automatically — no alerts are lost, they are simply deferred.",
    tone: "warn",
  },
};

export function StateView({ kind, onAction, actionLabel, detail }: StateViewProps) {
  const copy = COPY[kind];
  return (
    <section className={`state-view state-view--${copy.tone}`}>
      <h2 className="state-view__title">{copy.title}</h2>
      <p className="state-view__body">{detail ? `${copy.body} ${detail}` : copy.body}</p>
      {onAction && (
        <button type="button" className="btn btn--primary" onClick={onAction}>
          {actionLabel ?? "CONTINUE"}
        </button>
      )}
    </section>
  );
}

/** Derive the dominant view kind from panel status + snapshots. */
export function deriveViewKind(
  status: string,
  snapshots: SignalSnapshot[],
  adapterDegraded: boolean,
  contentTabReady = false,
): PanelViewKind {
  if (status === "SESSION_EXPIRED") return "subscription-expired";
  if (status === "DISCONNECTED") return "network-disconnected";
  if (status === "PERMISSION_REQUIRED") return "permission-not-granted";
  if (status === "MARKET_UNSUPPORTED") return adapterDegraded ? "site-layout-changed" : "unsupported-sportsbook";
  if (status === "IDLE") return contentTabReady ? "ready-to-start" : "no-supported-tab";
  if (snapshots.length === 0) return "no-markets-visible";
  const live = snapshots.filter((s) => !s.withdrawn);
  if (live.length === 0) {
    const anySuspended = snapshots.some((s) => s.withdrawalReason === "SUSPENDED");
    const anyExpired = snapshots.some((s) => s.withdrawalReason === "QUOTE_EXPIRED" || s.withdrawalReason === "DRIVE_ENDED" || s.withdrawalReason === "SOURCE_TIMESTAMP_UNVERIFIED");
    if (anySuspended) return "suspended-market";
    if (anyExpired) return "quote-expired";
    return "no-markets-visible";
  }
  if (live.some((s) => s.state === "MODEL_UNAVAILABLE")) return "model-unavailable";
  if (live.some((s) => s.state === "ALERTABLE")) return "positive-ev";
  return "negative-ev";
}
