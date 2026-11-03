/**
 * PropStein Live Sniper — Panel App (React entry for side panel + companion).
 * State-machine driven; renders only server-verified entitlement; every one
 * of the 14 required interaction states has a specific view.
 */
import { useEffect, useMemo, useState, useCallback } from "react";
import type { SignalSnapshot } from "@propstein/core";
import type { PanelState, SessionInfo } from "@propstein/browser";
import { SniperHeader } from "./components/SniperHeader.tsx";
import { SignalCard } from "./components/SignalCard.tsx";
import { EntitlementGate, type EntitlementState } from "./components/EntitlementGate.tsx";
import { SettingsPanel, DEFAULT_SETTINGS, type SniperSettings } from "./components/SettingsPanel.tsx";
import { StateView, deriveViewKind } from "./components/StateViews.tsx";
import { ConnectionState, type ConnectionQuality } from "./components/PriceComparison.tsx";
import { toSignalCardViewModel } from "./view-models.ts";

export interface PanelBridge {
  getState(): Promise<{ panelState: PanelState; session: SessionInfo | null; snapshots: SignalSnapshot[] }>;
  startMonitoring(): Promise<{ ok: boolean; reason?: string }>;
  stopMonitoring(): Promise<{ ok: boolean }>;
  signIn(token: string): Promise<{ ok: boolean; error?: string }>;
  signOut(): Promise<{ ok: boolean }>;
  requestSitePermission(origin: string): Promise<{ granted: boolean; reason: string }>;
  openDemoPage(): Promise<{ ok: boolean }>;
  updateSettings(settings: SniperSettings): Promise<{ ok: boolean }>;
  exportAudit(): Promise<{ records?: unknown[]; error?: string }>;
  onMessage(handler: (msg: Record<string, unknown>) => void): () => void;
}

const ADAPTER_STATUS = [
  { platform: "demobook", enabled: true, note: "Synthetic fixture — active" },
  { platform: "draftkings", enabled: false, note: "Disabled: requires capturable book source timestamp (DOM time fails closed), suspension state capture, and independent possession feed" },
  { platform: "fanduel", enabled: false, note: "Disabled: requires capturable book source timestamp, suspension state verification, and independent possession feed" },
  { platform: "polymarket", enabled: false, note: "Disabled: licensed Gamma/CLOB API preferred; event-level resolution lacks micro-market drive feeds" },
];

export function LiveSniperPanel({ bridge }: { bridge: PanelBridge }) {
  const [panelState, setPanelState] = useState<PanelState | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [snapshots, setSnapshots] = useState<SignalSnapshot[]>([]);
  const [settings, setSettings] = useState<SniperSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [signInOpen, setSignInOpen] = useState(false);
  const [tokenDraft, setTokenDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const state = await bridge.getState();
      setPanelState(state.panelState);
      setSession(state.session);
      setSnapshots(state.snapshots);
    } catch {
      setPanelState((p) => p ?? { status: "DISCONNECTED", monitoring: false, activeTabUrl: null, activeTabId: null, contentTabReady: false, adapterPlatform: null, adapterReason: null, signalCount: 0, lastUpdateIso: null });
    }
  }, [bridge]);

  useEffect(() => {
    void refresh();
    const off = bridge.onMessage((msg) => {
      const type = msg["type"];
      if (type === "PANEL_STATE") setPanelState(msg["panelState"] as PanelState);
      else if (type === "SIGNAL_SNAPSHOTS") setSnapshots(msg["snapshots"] as SignalSnapshot[]);
      else if (type === "SESSION_UPDATE") setSession(msg["session"] as SessionInfo | null);
      else if (type === "ALERT_RAISED" || type === "ALERT_WITHDRAWN" || type === "DRIVE_INVALIDATED") void refresh();
    });
    const ticker = setInterval(() => void refresh(), 2000);
    return () => { off(); clearInterval(ticker); };
  }, [bridge, refresh]);

  const entitlement: EntitlementState = useMemo(() => {
    if (!session) return { kind: "signed-out" };
    if (session.tier !== "pro") return { kind: "free" };
    if (Date.parse(session.expiresAtIso) <= Date.now()) return { kind: "expired" };
    return { kind: "pro", expiresAtIso: session.expiresAtIso, provider: session.provider };
  }, [session]);

  const connection: ConnectionQuality = panelState?.status === "DISCONNECTED" ? "offline" : panelState?.monitoring ? "live" : "reconnecting";
  const adapterDegraded = panelState?.adapterReason?.includes("layout") ?? false;
  const contentTabReady = panelState?.contentTabReady === true;
  const viewKind = panelState ? deriveViewKind(panelState.status, snapshots, adapterDegraded, contentTabReady) : "no-supported-tab";

  const liveSnapshots = snapshots.filter((s) => !s.withdrawn);
  const withdrawnSnapshots = snapshots.filter((s) => s.withdrawn);
  const viewModels = [...liveSnapshots, ...withdrawnSnapshots].map(toSignalCardViewModel);

  return (
    <div id="panel-root">
      <SniperHeader
        status={panelState?.status ?? "IDLE"}
        signalCount={liveSnapshots.length}
        lastUpdateIso={panelState?.lastUpdateIso ?? null}
      />

      <div className="panel-body">
        <div className="state-view state-view--warn" role="status">
          <h2 className="state-view__title">RESEARCH TRIAL · SYNTHETIC FIXTURE ONLY</h2>
          <p className="state-view__body">DemoBook and its model are SYNTHETIC. Real-book observations without a prospectively calibrated model or independent possession feed are RESEARCH ONLY, with no &ldquo;has edge&rdquo; or bet recommendation. PropStein never places or confirms wagers.</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
          <ConnectionState quality={connection} detail={panelState?.adapterPlatform ? `adapter: ${panelState.adapterPlatform}` : undefined} />
          <EntitlementGate
            state={entitlement}
            onSignIn={() => setSignInOpen(true)}
            onOpenPricing={() => setSignInOpen(true)}
          />
        </div>

        {error && (
          <div className="state-view state-view--warn">
            <h2 className="state-view__title">ACTION REQUIRED</h2>
            <p className="state-view__body">{error}</p>
          </div>
        )}

        {!panelState?.monitoring && (
          <StateView
            kind={viewKind}
            detail={panelState?.adapterReason ?? undefined}
            onAction={async () => {
              setError(null);
              if (!contentTabReady) {
                await bridge.openDemoPage();
                setError("Demo fixture page opened — switch to it and press START MONITORING.");
                return;
              }
              const r = await bridge.startMonitoring();
              if (!r.ok && r.reason) setError(r.reason);
              await refresh();
            }}
            actionLabel={contentTabReady ? "START MONITORING" : "OPEN DEMO FIXTURE PAGE"}
          />
        )}

        {panelState?.monitoring && viewModels.length === 0 && (
          <StateView kind={viewKind} />
        )}

        {panelState?.monitoring && viewModels.length > 0 && (
          <>
            <StateView kind={viewKind} />
            {viewModels.map((vm) => (
              <SignalCard key={vm.key} vm={vm} />
            ))}
          </>
        )}

        {signInOpen && (
          <div className="state-view state-view--neutral">
            <h2 className="state-view__title">SIGN IN TO PROPSTEIN</h2>
            <p className="state-view__body">
              Paste your PropStein session token (from the PropStein terminal). The token is exchanged
              server-side for a short-lived scoped access token; it is never sent in a URL parameter.
            </p>
            <input
              type="password"
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 4, color: "var(--text-main)", fontFamily: "var(--mono)" }}
              placeholder="PropStein session token"
              value={tokenDraft}
              onChange={(e) => setTokenDraft(e.target.value)}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className="btn btn--primary"
                onClick={async () => {
                  const r = await bridge.signIn(tokenDraft);
                  if (!r.ok) setError(r.error ?? "sign-in failed");
                  else { setSignInOpen(false); setError(null); setTokenDraft(""); }
                  await refresh();
                }}
              >
                SIGN IN
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => setSignInOpen(false)}>CANCEL</button>
            </div>
          </div>
        )}
      </div>

      <div className="panel-toolbar">
        {panelState?.monitoring ? (
          <button type="button" className="btn btn--danger" onClick={async () => { await bridge.stopMonitoring(); await refresh(); }}>
            PAUSE MONITORING
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            onClick={async () => {
              if (!contentTabReady) {
                await bridge.openDemoPage();
                setError("Demo fixture page opened — switch to it and press START MONITORING.");
                return;
              }
              setError(null);
              const r = await bridge.startMonitoring();
              if (!r.ok && r.reason) setError(r.reason);
              await refresh();
            }}
          >
            START MONITORING
          </button>
        )}
        {session && (
          <button type="button" className="btn btn--ghost" onClick={async () => { await bridge.signOut(); await refresh(); }}>
            SIGN OUT
          </button>
        )}
        <button type="button" className="btn btn--ghost" onClick={() => setShowSettings((v) => !v)}>SETTINGS</button>
        <button type="button" className="btn btn--ghost" onClick={async () => {
          const result = await bridge.exportAudit();
          if (result.error || !result.records) { setError(result.error ?? "Audit export unavailable"); return; }
          const blob = new Blob([result.records.map((record) => JSON.stringify(record)).join("\n") + "\n"], { type: "application/x-ndjson" });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `propstein-trial-audit-${new Date().toISOString().slice(0, 10)}.jsonl`;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 60_000);
        }}>EXPORT TRIAL LOG</button>
      </div>

      {showSettings && (
        <SettingsPanel
          settings={settings}
          onChange={(next) => { setSettings(next); void bridge.updateSettings(next); }}
          onClose={() => setShowSettings(false)}
          adapterStatus={ADAPTER_STATUS}
        />
      )}
    </div>
  );
}
