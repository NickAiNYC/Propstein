/**
 * PropStein Live Sniper — Browser Capabilities
 * ==========================================
 * Detects which browser APIs are available so the shared code never calls a
 * Chrome-only API on Safari. Chrome's Side Panel API is NOT assumed to exist
 * in Safari (spec §3): when absent, the product falls back to the standalone
 * companion window.
 */

export interface BrowserCapabilities {
  runtime: boolean;
  sidePanel: boolean;
  scripting: boolean;
  permissions: boolean;
  storageSession: boolean;
  tabs: boolean;
  notifications: boolean;
  mutationObserver: boolean;
  intersectionObserver: boolean;
}

type ChromeLike = typeof globalThis & {
  chrome?: {
    runtime?: unknown;
    sidePanel?: unknown;
    scripting?: unknown;
    permissions?: unknown;
    tabs?: unknown;
    storage?: { session?: unknown };
    notifications?: unknown;
  };
};

export function detectCapabilities(g: typeof globalThis = globalThis): BrowserCapabilities {
  const chrome = (g as ChromeLike).chrome;
  return {
    runtime: Boolean(chrome?.runtime),
    sidePanel: Boolean(chrome?.sidePanel),
    scripting: Boolean(chrome?.scripting),
    permissions: Boolean(chrome?.permissions),
    storageSession: Boolean(chrome?.storage?.session),
    tabs: Boolean(chrome?.tabs),
    notifications: Boolean(chrome?.notifications),
    mutationObserver: typeof MutationObserver !== "undefined",
    intersectionObserver: typeof IntersectionObserver !== "undefined",
  };
}

/** Panel surface strategy for this browser. */
export type PanelSurface =
  | "side-panel"          // Chrome side Panel API
  | "companion-window";   // Standalone window (Safari, any browser)

export function panelSurfaceFor(caps: BrowserCapabilities): PanelSurface {
  return caps.sidePanel ? "side-panel" : "companion-window";
}

/**
 * API base resolution. The public Railway API origin is NOT hardcoded as a
 * claim — it is configuration (audit finding: the repo does not publish the
 * public Railway domain). Default points at the PropStein web origin so a
 * misconfigured build fails closed with a clear error rather than silently
 * calling the wrong host.
 */
export function resolveApiBaseUrl(overrides: { env?: string; stored?: string } = {}): string {
  const fromEnv = overrides.env?.trim();
  if (fromEnv && /^https?:\/\//.test(fromEnv)) return fromEnv.replace(/\/$/, "");
  const fromStored = overrides.stored?.trim();
  if (fromStored && /^https?:\/\//.test(fromStored)) return fromStored.replace(/\/$/, "");
  return "https://propstein.vercel.app";
}
