/**
 * PropStein Live Sniper — Panel Bridge (chrome.runtime adapter).
 * Implements the UI PanelBridge contract over the background service worker.
 * When chrome.runtime is unavailable (standalone companion in a plain
 * browser tab), a degraded bridge is returned so the same UI renders honest
 * "not available" states instead of throwing.
 */
import type { SignalSnapshot } from "@propstein/core";
import type { PanelState, SessionInfo } from "@propstein/browser";
import type { PanelBridge } from "@propstein/ui";
import type { SniperSettings } from "@propstein/ui";

type ChromeLike = {
  runtime: {
    sendMessage(msg: unknown): Promise<unknown>;
    onMessage: { addListener(cb: (msg: unknown) => void): void };
  };
  permissions?: {
    contains(p: { origins: string[] }): Promise<boolean>;
    request(p: { origins: string[] }): Promise<boolean>;
  };
};

function chromeRuntime(): ChromeLike["runtime"] | undefined {
  return (globalThis as { chrome?: ChromeLike }).chrome?.runtime;
}

export function createChromePanelBridge(): PanelBridge {
  const runtime = chromeRuntime();

  if (!runtime) {
    // Standalone companion (no extension APIs): every capability reports
    // unavailable; the UI shows its dedicated degraded state views.
    const unavailable = async (): Promise<never> => {
      throw new Error("Standalone companion mode — monitoring requires the browser extension.");
    };
    return {
      getState: async () => ({
        panelState: {
          status: "IDLE",
          monitoring: false,
          activeTabUrl: null,
          activeTabId: null,
          contentTabReady: false,
          adapterPlatform: null,
          adapterReason: "standalone companion — install the extension for active-screen monitoring",
          signalCount: 0,
          lastUpdateIso: new Date().toISOString(),
        } satisfies PanelState,
        session: null,
        snapshots: [] as SignalSnapshot[],
      }),
      startMonitoring: unavailable as PanelBridge["startMonitoring"],
      stopMonitoring: unavailable as PanelBridge["stopMonitoring"],
      signIn: unavailable as PanelBridge["signIn"],
      signOut: unavailable as PanelBridge["stopMonitoring"],
      requestSitePermission: unavailable as PanelBridge["requestSitePermission"],
      openDemoPage: unavailable as PanelBridge["openDemoPage"],
      updateSettings: unavailable as PanelBridge["updateSettings"],
      exportAudit: unavailable as PanelBridge["exportAudit"],
      onMessage: () => () => undefined,
    };
  }

  const send = async <T,>(msg: unknown): Promise<T> => (await runtime.sendMessage(msg)) as T;

  // chrome.permissions.request requires a USER GESTURE, which does not survive
  // the runtime-message hop to the service worker. Extension pages (the panel)
  // hold the gesture context, so the request is made here directly; the
  // background's REQUEST_SITE_PERMISSION handler remains as a contains()-only
  // fallback for callers without page-level API access.
  const requestSitePermissionInPage = async (origin: string): Promise<{ granted: boolean; reason: string }> => {
    const perms = (globalThis as { chrome?: ChromeLike }).chrome?.permissions;
    if (!perms) {
      return send<{ granted: boolean; reason: string }>({ type: "REQUEST_SITE_PERMISSION", origin });
    }
    const pattern = `${origin.replace(/\/$/, "")}/*`;
    try {
      if (await perms.contains({ origins: [pattern] })) return { granted: true, reason: "already granted" };
      const granted = await perms.request({ origins: [pattern] });
      return granted
        ? { granted: true, reason: "granted by user" }
        : { granted: false, reason: "the user declined the site permission prompt" };
    } catch (err) {
      return { granted: false, reason: `permission API error: ${String(err)}` };
    }
  };

  return {
    getState: () => send<{ panelState: PanelState; session: SessionInfo | null; snapshots: SignalSnapshot[] }>({ type: "GET_STATE" }),
    startMonitoring: () => send<{ ok: boolean; reason?: string }>({ type: "START_MONITORING" }),
    stopMonitoring: () => send<{ ok: boolean }>({ type: "STOP_MONITORING" }),
    signIn: (token: string) => send<{ ok: boolean; error?: string }>({ type: "SIGN_IN", token }),
    signOut: () => send<{ ok: boolean }>({ type: "SIGN_OUT" }),
    requestSitePermission: (origin: string) => requestSitePermissionInPage(origin),
    openDemoPage: () => send<{ ok: boolean }>({ type: "OPEN_DEMO_PAGE" }),
    updateSettings: (settings: SniperSettings) => send<{ ok: boolean }>({ type: "UPDATE_SETTINGS", settings }),
    exportAudit: () => send<{ records?: unknown[]; error?: string }>({ type: "GET_AUDIT" }),
    onMessage: (handler) => {
      const listener = (msg: unknown) => {
        if (msg && typeof msg === "object" && "type" in msg) handler(msg as Record<string, unknown>);
      };
      runtime.onMessage.addListener(listener);
      return () => {
        // chrome.runtime.onMessage lacks removeListener in the minimal typing;
        // extension pages live for the panel lifetime, so this is a no-op.
      };
    },
  };
}
