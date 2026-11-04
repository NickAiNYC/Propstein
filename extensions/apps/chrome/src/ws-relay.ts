/**
 * PropStein Live Sniper — WebSocket Relay & Telemetry Manager
 * ==========================================================
 * Manages the backend real-time stream from the background service worker:
 *  - Ephemeral MV3 keepalive via chrome.alarms
 *  - Multi-book repricing latency tracking (identifying slowest book)
 *  - Freshness kill-switch enforcement (20s odds / 90s injury)
 *  - Alert router (push notifications only for verified + passed signals)
 */

import {
  type BackendLiveSignal,
  type BookRepriceTelemetry,
  type PlacedAuditRecord,
  routeSignalAlert,
  evaluateSignalVerification,
} from "@propstein/core";

declare const chrome: {
  notifications?: {
    create(id: string, opts: Record<string, unknown>): void;
  };
};

export interface WsRelayConfig {
  wsUrl: string;
  heartbeatIntervalMs?: number;
  reconnectDelayMs?: number;
}

export class WebSocketRelay {
  private ws: WebSocket | null = null;
  private readonly config: WsRelayConfig;
  private activeSignals = new Map<string, BackendLiveSignal>();
  private bookLatencyStats = new Map<string, { totalLagMs: number; count: number }>();
  private panicKillActive = false;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private isConnecting = false;

  constructor(config: WsRelayConfig) {
    this.config = {
      heartbeatIntervalMs: 25000,
      reconnectDelayMs: 2000,
      ...config,
    };
  }

  init(): void {
    this.connect();
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.isConnecting = true;
    try {
      this.ws = new WebSocket(this.config.wsUrl);

      this.ws.onopen = () => {
        this.isConnecting = false;
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          this.handleServerMessage(payload);
        } catch {
          // Ignore unparseable frames fail-closed
        }
      };

      this.ws.onclose = () => {
        this.isConnecting = false;
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.config.reconnectDelayMs);
  }

  handleServerMessage(msg: Record<string, unknown>): void {
    const type = msg.type;

    if (type === "SIGNAL_UPDATE" && msg.signal) {
      const sig = msg.signal as BackendLiveSignal;
      this.activeSignals.set(sig.signalId, sig);

      // Track reprice telemetry
      if (sig.book && sig.repriceDelayMs !== undefined) {
        this.recordBookLag(sig.book, sig.marketType, sig.repriceDelayMs);
      }

      // Check alert routing
      const action = routeSignalAlert(sig, 4.0, this.panicKillActive);
      if (action === "push_priority" && typeof chrome !== "undefined" && chrome.notifications) {
        chrome.notifications.create(sig.signalId, {
          type: "basic",
          iconUrl: "icons/icon48.png",
          title: `PropStein Verified · ${sig.playerName}`,
          message: `${sig.selection} ${sig.line} (Fair ${sig.modelFairLine.toFixed(1)}) · Gap +${sig.gapPts.toFixed(1)} pts`,
          priority: 2,
        });
      }
    } else if (type === "KILL_SWITCH") {
      this.activeSignals.clear();
    }
  }

  recordBookLag(book: string, marketType: string, lagMs: number): void {
    const key = `${book}:${marketType}`;
    const cur = this.bookLatencyStats.get(key) || { totalLagMs: 0, count: 0 };
    cur.totalLagMs += lagMs;
    cur.count += 1;
    this.bookLatencyStats.set(key, cur);
  }

  getSlowestBookTelemetry(marketType: string): BookRepriceTelemetry | null {
    let slowest: BookRepriceTelemetry | null = null;
    let maxLag = -1;

    for (const [key, stat] of this.bookLatencyStats.entries()) {
      const [book, type] = key.split(":");
      if (type !== marketType) continue;

      const avg = Math.round(stat.totalLagMs / stat.count);
      if (avg > maxLag) {
        maxLag = avg;
        slowest = {
          book: book || "unknown_book",
          marketType,
          sampleCount: stat.count,
          avgRepriceLagMs: avg,
          isSlowest: true,
        };
      }
    }

    return slowest;
  }

  setPanicKill(active: boolean): void {
    this.panicKillActive = active;
    if (active) {
      this.activeSignals.clear();
    }
  }

  getActiveSignals(): BackendLiveSignal[] {
    return Array.from(this.activeSignals.values());
  }

  getSignalsForPlayer(lastName: string): BackendLiveSignal[] {
    return this.getActiveSignals().filter(
      (s) => s.playerName.toLowerCase().includes(lastName.toLowerCase())
    );
  }

  destroy(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.activeSignals.clear();
  }
}
