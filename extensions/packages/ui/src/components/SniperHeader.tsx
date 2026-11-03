/**
 * PropStein Live Sniper — SniperHeader component (spec §11).
 * PROPSTEIN / LIVE SNIPER / PRO with status chip.
 */
import type { PanelStatus } from "@propstein/browser";

export interface SniperHeaderProps {
  status: PanelStatus;
  signalCount: number;
  lastUpdateIso: string | null;
}

const STATUS_TONE: Record<PanelStatus, string> = {
  MONITORING: "status status--live",
  IDLE: "status status--idle",
  DISCONNECTED: "status status--warn",
  PERMISSION_REQUIRED: "status status--warn",
  MARKET_UNSUPPORTED: "status status--warn",
  SESSION_EXPIRED: "status status--expired",
};

const STATUS_LABEL: Record<PanelStatus, string> = {
  MONITORING: "MONITORING",
  IDLE: "IDLE",
  DISCONNECTED: "DISCONNECTED",
  PERMISSION_REQUIRED: "PERMISSION REQUIRED",
  MARKET_UNSUPPORTED: "MARKET UNSUPPORTED",
  SESSION_EXPIRED: "SESSION EXPIRED",
};

export function SniperHeader({ status, signalCount, lastUpdateIso }: SniperHeaderProps) {
  const stamp = lastUpdateIso ? new Date(lastUpdateIso).toLocaleTimeString("en-US", { hour12: false }) : "--:--:--";
  return (
    <header className="sniper-header">
      <div className="sniper-header__brand">
        <span className="sniper-header__wordmark">PROPSTEIN</span>
        <span className="sniper-header__sub">LIVE SNIPER <span className="sniper-header__pro">/ PRO</span></span>
      </div>
      <div className="sniper-header__right">
        <span className={STATUS_TONE[status]}>
          <i className="dot" aria-hidden="true" />
          {STATUS_LABEL[status]}
        </span>
        <span className="sniper-header__meta">
          {signalCount} SIGNAL{signalCount === 1 ? "" : "S"} · {stamp}
        </span>
      </div>
    </header>
  );
}
