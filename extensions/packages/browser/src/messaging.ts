/**
 * PropStein Live Sniper — Messaging
 * ================================
 * Typed, origin-validated message protocol between:
 *   content bridge (isolated world, sportsbook tab)
 *     ↕ chrome.runtime messages
 *   background service worker
 *     ↕ runtime ports / messages
 *   side panel / companion (extension pages)
 *
 * Security rules (spec §12):
 *  - Messages are only accepted when sender.id === chrome.runtime.id
 *    (same extension) AND, for content-bridge traffic, the sender origin is
 *    an explicitly granted, supported site.
 *  - All cross-boundary payloads are validated before use; page DOM content
 *    is untrusted input.
 */

import type { ObservedMarket, SignalSnapshot } from "@propstein/core";

// ---------------------------------------------------------------------------
// Protocol types
// ---------------------------------------------------------------------------

/** Background → content bridge. */
export type BackgroundToBridgeMessage =
  | { type: "SNIPE_START"; correlationId: string }
  | { type: "SNIPE_STOP"; correlationId: string };

/** Content bridge → background. */
export type BridgeToBackgroundMessage =
  | { type: "SNIPE_ACK"; correlationId: string; ok: boolean; detail?: string }
  | { type: "MARKET_EVENTS"; correlationId: string; events: Array<{ kind: string; signalKey?: string; market?: ObservedMarket }> }
  | { type: "BRIDGE_STATUS"; status: "OK" | "ADAPTER_DEGRADED" | "PAGE_UNSUPPORTED"; detail?: string };

/** Background → panel / companion. */
export type BackgroundToPanelMessage =
  | { type: "PANEL_STATE"; panelState: PanelState }
  | { type: "SIGNAL_SNAPSHOTS"; snapshots: SignalSnapshot[] }
  | { type: "ALERT_RAISED"; snapshot: SignalSnapshot }
  | { type: "ALERT_WITHDRAWN"; snapshot: SignalSnapshot; reason?: string }
  | { type: "DRIVE_INVALIDATED"; driveId: string; count: number }
  | { type: "SESSION_UPDATE"; session: SessionInfo | null }
  | { type: "PERMISSION_REQUIRED"; origin: string };

/** Panel → background. */
export type PanelToBackgroundMessage =
  | { type: "START_MONITORING" }
  | { type: "STOP_MONITORING" }
  | { type: "REQUEST_SITE_PERMISSION"; origin: string }
  | { type: "SIGN_IN"; token: string }
  | { type: "SIGN_OUT" }
  | { type: "REFRESH_SESSION" }
  | { type: "GET_STATE" }
  | { type: "UPDATE_SETTINGS"; settings: Record<string, unknown> }
  | { type: "GET_AUDIT" }
  | { type: "OPEN_DEMO_PAGE" };

export type PanelStatus =
  | "MONITORING"
  | "IDLE"
  | "DISCONNECTED"
  | "PERMISSION_REQUIRED"
  | "MARKET_UNSUPPORTED"
  | "SESSION_EXPIRED";

export interface PanelState {
  status: PanelStatus;
  monitoring: boolean;
  activeTabUrl: string | null;
  activeTabId: number | null;
  /** True when the tracked content tab resolves to an enabled adapter site. */
  contentTabReady: boolean;
  adapterPlatform: string | null;
  adapterReason: string | null;
  signalCount: number;
  lastUpdateIso: string | null;
}

export interface SessionInfo {
  tier: "pro" | "free";
  provider: string;
  expiresAtIso: string;
  refreshedAtIso: string;
}

// ---------------------------------------------------------------------------
// Sender validation
// ---------------------------------------------------------------------------

export interface SenderLike {
  id?: string;
  url?: string;
  tab?: { id?: number };
  origin?: string;
}

export interface RuntimeLike {
  id?: string;
}

/**
 * Validate that a runtime message comes from THIS extension.
 * Rejects web pages (externally_connectable), other extensions, and devtools.
 */
export function isTrustedExtensionSender(sender: SenderLike | undefined, runtime: RuntimeLike): boolean {
  if (!sender) return false;
  if (!runtime.id) return false;
  return sender.id === runtime.id;
}

/**
 * Validate content-bridge traffic: the sender must be this extension AND its
 * origin must be in the granted set for site detection.
 */
export function isTrustedBridgeSender(
  sender: SenderLike | undefined,
  runtime: RuntimeLike,
  grantedOrigins: ReadonlySet<string>,
): boolean {
  if (!sender) return false;
  if (!isTrustedExtensionSender(sender, runtime)) return false;
  const origin = sender.origin ?? (sender.url ? safeOrigin(sender.url) : undefined);
  if (!origin) return false;
  return grantedOrigins.has(origin);
}

export function safeOrigin(url: string): string | undefined {
  try {
    return new URL(url).origin;
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Payload validation — page data is untrusted input
// ---------------------------------------------------------------------------

const MAX_EVENTS_PER_MESSAGE = 200;
const MAX_STRING_LEN = 500;

export function clampString(value: unknown, max = MAX_STRING_LEN): string {
  if (typeof value !== "string") return "";
  // Strip control characters that could smuggle markup into any HTML sink.
  return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, max);
}

export function clampNumber(value: unknown, min: number, max: number): number | undefined {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return undefined;
  return Math.min(max, Math.max(min, n));
}

/** Validate an inbound market event batch from the bridge. */
export function validateMarketEventBatch(
  payload: unknown,
): { ok: true; events: Extract<BridgeToBackgroundMessage, { type: "MARKET_EVENTS" }> } | { ok: false; reason: string } {
  if (typeof payload !== "object" || payload === null) return { ok: false, reason: "payload not an object" };
  const p = payload as Record<string, unknown>;
  if (p.type !== "MARKET_EVENTS") return { ok: false, reason: "wrong message type" };
  if (!Array.isArray(p.events)) return { ok: false, reason: "events not an array" };
  if (p.events.length > MAX_EVENTS_PER_MESSAGE) return { ok: false, reason: `too many events (${p.events.length})` };
  const events = p.events.map((raw) => {
    const e = (raw ?? {}) as Record<string, unknown>;
    return {
      kind: clampString(e.kind, 40),
      ...(typeof e.signalKey === "string" ? { signalKey: clampString(e.signalKey, 400) } : {}),
      ...(isValidMarket(e.market) ? { market: sanitizeMarket(e.market) } : {}),
    };
  });
  return { ok: true, events: { type: "MARKET_EVENTS", correlationId: clampString(p.correlationId, 64), events } };
}

function isValidMarket(m: unknown): m is ObservedMarket {
  if (typeof m !== "object" || m === null) return false;
  const r = m as Record<string, unknown>;
  return typeof r.source === "string" && typeof r.playerName === "string" && typeof r.observedAt === "string";
}

/** Sanitize an observed market received from an untrusted page context. */
export function sanitizeMarket(m: ObservedMarket): ObservedMarket {
  return {
    ...m,
    playerName: clampString(m.playerName, 120),
    marketType: clampString(m.marketType),
    marketLabel: clampString(m.marketLabel),
    selection: clampString(m.selection, 40),
    driveId: m.driveId !== undefined ? clampString(m.driveId, 120) : undefined,
    eventId: m.eventId !== undefined ? clampString(m.eventId, 120) : undefined,
    americanOdds: clampNumber(m.americanOdds, -100000, 100000),
    line: clampNumber(m.line, -300, 300),
    detectionConfidence: clampNumber(m.detectionConfidence, 0, 1) ?? 0,
  };
}
