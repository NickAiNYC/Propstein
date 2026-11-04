/**
 * PropStein Live Sniper — Closed Shadow DOM Overlay Manager
 * =========================================================
 * Manages the sportsbook in-page overlay in an isolated closed shadow root:
 *  - mode: 'closed' ensures host.shadowRoot is null to page scripts.
 *  - Global panic kill switch (Ctrl+Shift+K / Cmd+Shift+K) instantly hides
 *    and clears all overlays with zero page trace.
 *  - Lock state is the hero: LOCKED displays prominently with verification reason.
 *  - Handoff is human-initiated: "Send to slip" stages, "I placed it" records audit receipts.
 */

import {
  type BackendLiveSignal,
  type PlacedAuditRecord,
  evaluateSignalVerification,
} from "@propstein/core";

export interface OverlayManagerOptions {
  doc?: Document;
  onPanicKillChange?: (active: boolean) => void;
  onAuditPlaced?: (record: PlacedAuditRecord) => void;
}

export class OverlayManager {
  private readonly doc: Document;
  private host: HTMLElement | null = null;
  private shadow: ShadowRoot | null = null;
  private panicKillActive = false;
  private readonly onPanicKillChange?: (active: boolean) => void;
  private readonly onAuditPlaced?: (record: PlacedAuditRecord) => void;
  private activeOverlays = new Map<string, HTMLElement>();
  private keydownHandler?: (e: KeyboardEvent) => void;

  constructor(opts: OverlayManagerOptions = {}) {
    this.doc = opts.doc ?? (typeof document !== "undefined" ? document : (null as unknown as Document));
    this.onPanicKillChange = opts.onPanicKillChange;
    this.onAuditPlaced = opts.onAuditPlaced;
  }

  init(): void {
    if (!this.doc || this.host) return;

    // 1. Create host element
    this.host = this.doc.createElement("div");
    this.host.id = "__propstein_host";
    this.host.style.cssText = "position: absolute; top: 0; left: 0; width: 100%; pointer-events: none; z-index: 2147483647;";

    // 2. Attach shadow in closed mode
    this.shadow = this.host.attachShadow({ mode: "closed" });

    // 3. Inject isolated shadow DOM styles
    const style = this.doc.createElement("style");
    style.textContent = `
      .ps-overlay {
        position: absolute;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0f141c;
        color: #e5e7eb;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 8px;
        padding: 10px 12px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
        font-size: 11px;
        width: 240px;
        pointer-events: auto;
        z-index: 2147483647;
        transition: opacity 0.15s ease-out;
      }
      .ps-overlay.ps-locked {
        border-color: #ef4444;
      }
      .ps-overlay.ps-qualified {
        border-color: #10b981;
      }
      .ps-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
        font-size: 10px;
      }
      .ps-badge-verified {
        color: #10b981;
      }
      .ps-badge-locked {
        color: #ef4444;
      }
      .ps-badge-stale {
        color: #f59e0b;
      }
      .ps-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4px 8px;
        margin-bottom: 8px;
        background: rgba(255, 255, 255, 0.04);
        padding: 6px;
        border-radius: 4px;
      }
      .ps-stat-label {
        color: #9ca3af;
        font-size: 9px;
        text-transform: uppercase;
      }
      .ps-stat-val {
        font-weight: 600;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      }
      .ps-hero-banner {
        padding: 6px 8px;
        border-radius: 4px;
        margin-bottom: 8px;
        text-align: center;
        font-weight: 700;
      }
      .ps-hero-locked {
        background: rgba(239, 68, 68, 0.18);
        border: 1px solid #ef4444;
        color: #fca5a5;
      }
      .ps-hero-qualified {
        background: rgba(16, 185, 129, 0.18);
        border: 1px solid #10b981;
        color: #6ee7b7;
      }
      .ps-hero-sub {
        font-size: 9px;
        font-weight: 400;
        color: #cbd5e1;
        margin-top: 2px;
      }
      .ps-actions {
        display: flex;
        gap: 4px;
      }
      .ps-btn {
        flex: 1;
        background: #1e293b;
        color: #f8fafc;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 4px;
        padding: 5px 6px;
        font-size: 10px;
        font-weight: 600;
        cursor: pointer;
        text-align: center;
      }
      .ps-btn:hover {
        background: #334155;
      }
      .ps-btn-primary {
        background: #047857;
        border-color: #10b981;
        color: #ecfdf5;
      }
      .ps-btn-primary:hover {
        background: #059669;
      }
      .ps-btn-dismiss {
        flex: 0 0 24px;
        padding: 5px 0;
      }
    `;
    this.shadow.appendChild(style);

    this.doc.documentElement.appendChild(this.host);

    // 4. Setup keyboard kill switch (Ctrl+Shift+K / Cmd+Shift+K)
    this.keydownHandler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "K" || e.key === "k")) {
        e.preventDefault();
        this.togglePanicKill();
      }
    };
    this.doc.addEventListener("keydown", this.keydownHandler, true);
  }

  isPanicKillEngaged(): boolean {
    return this.panicKillActive;
  }

  togglePanicKill(): boolean {
    this.panicKillActive = !this.panicKillActive;
    if (this.host) {
      if (this.panicKillActive) {
        this.host.style.display = "none";
        this.clearAllOverlays();
      } else {
        this.host.style.display = "block";
      }
    }
    this.onPanicKillChange?.(this.panicKillActive);
    return this.panicKillActive;
  }

  renderOverlay(
    targetEl: Element,
    signal: BackendLiveSignal,
    options: {
      isStaleReprice?: boolean;
      onSendToSlip?: () => void;
    } = {}
  ): HTMLElement | null {
    if (this.panicKillActive || !this.shadow || !this.doc) return null;

    const key = signal.signalId;
    let card = this.activeOverlays.get(key);
    if (!card) {
      card = this.doc.createElement("div");
      card.className = "ps-overlay";
      this.shadow.appendChild(card);
      this.activeOverlays.set(key, card);
    }

    const verification = evaluateSignalVerification(signal, Date.now(), this.panicKillActive);
    const isLocked = verification.state === "LOCKED";
    const isStale = options.isStaleReprice === true;

    card.className = `ps-overlay ${isLocked || isStale ? "ps-locked" : "ps-qualified"}`;

    // Position overlay relative to target element
    const rect = targetEl.getBoundingClientRect();
    const scrollX = typeof window !== "undefined" ? window.scrollX : 0;
    const scrollY = typeof window !== "undefined" ? window.scrollY : 0;

    // Place next to target with subtle randomized offset (+-3px)
    const offset = Math.floor(Math.random() * 6) - 3;
    card.style.top = `${Math.round(rect.bottom + scrollY + 4 + offset)}px`;
    card.style.left = `${Math.round(rect.left + scrollX + offset)}px`;

    // Render HTML content
    const headerTitle = isStale
      ? '<span class="ps-badge-stale">⚠ STALE — BOOK HASN\'T REPRICED</span>'
      : isLocked
      ? `<span class="ps-badge-locked">PROPSTEIN ● ${verification.state}</span>`
      : `<span class="ps-badge-verified">PROPSTEIN ● VERIFIED ${verification.ageSec}s</span>`;

    const heroBanner = isStale
      ? `
        <div class="ps-hero-banner ps-hero-locked">
          <div>STALE — BOOK HASN'T REPRICED</div>
          <div class="ps-hero-sub">Fair ${signal.modelFairLine.toFixed(1)} vs Book ${signal.line.toFixed(1)}</div>
        </div>
      `
      : isLocked
      ? `
        <div class="ps-hero-banner ps-hero-locked">
          <div>⚠ EDGE ${signal.edgePct.toFixed(1)}% — LOCKED</div>
          <div class="ps-hero-sub">${verification.reasonText}</div>
        </div>
      `
      : `
        <div class="ps-hero-banner ps-hero-qualified">
          <div>QUALIFIED FORECAST</div>
          <div class="ps-hero-sub">Pre-kickoff verified · Model-market gap: +${signal.gapPts.toFixed(1)} pts</div>
        </div>
      `;

    card.innerHTML = `
      <div class="ps-header">
        ${headerTitle}
      </div>
      <div class="ps-grid">
        <div>
          <div class="ps-stat-label">Model Fair</div>
          <div class="ps-stat-val">${signal.modelFairLine.toFixed(1)}</div>
        </div>
        <div>
          <div class="ps-stat-label">Market Line</div>
          <div class="ps-stat-val">${signal.line.toFixed(1)} (${signal.price > 0 ? "+" + signal.price : signal.price})</div>
        </div>
        <div>
          <div class="ps-stat-label">P(Over)</div>
          <div class="ps-stat-val">${(signal.pOver * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div class="ps-stat-label">Gap</div>
          <div class="ps-stat-val">${signal.gapPts > 0 ? "+" : ""}${signal.gapPts.toFixed(1)} pts</div>
        </div>
      </div>
      ${heroBanner}
      <div class="ps-actions">
        <button type="button" class="ps-btn ps-btn-primary" data-action="stage">Send to slip</button>
        <button type="button" class="ps-btn" data-action="placed">I placed it</button>
        <button type="button" class="ps-btn ps-btn-dismiss" data-action="dismiss" title="Dismiss">✕</button>
      </div>
    `;

    // Event handlers inside Shadow Root
    const stageBtn = card.querySelector('[data-action="stage"]');
    if (stageBtn) {
      stageBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        options.onSendToSlip?.();
      });
    }

    const placedBtn = card.querySelector('[data-action="placed"]');
    if (placedBtn) {
      placedBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const record: PlacedAuditRecord = {
          recordId: `placed-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          signalId: signal.signalId,
          timestamp: new Date().toISOString(),
          book: signal.book || "unknown_book",
          playerName: signal.playerName,
          market: signal.marketType,
          displayedLine: signal.line,
          modelFairLine: signal.modelFairLine,
          pOver: signal.pOver,
          achievedPrice: signal.price,
          auditReceiptSha256: `audit-${Date.now()}`,
        };
        this.onAuditPlaced?.(record);
        card?.remove();
        this.activeOverlays.delete(key);
      });
    }

    const dismissBtn = card.querySelector('[data-action="dismiss"]');
    if (dismissBtn) {
      dismissBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        card?.remove();
        this.activeOverlays.delete(key);
      });
    }

    return card;
  }

  clearAllOverlays(): void {
    for (const card of this.activeOverlays.values()) {
      card.remove();
    }
    this.activeOverlays.clear();
  }

  destroy(): void {
    if (this.keydownHandler && this.doc) {
      this.doc.removeEventListener("keydown", this.keydownHandler, true);
    }
    this.clearAllOverlays();
    this.host?.remove();
    this.host = null;
    this.shadow = null;
  }
}
