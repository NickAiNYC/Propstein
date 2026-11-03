/**
 * PropStein Live Sniper — PriceComparison, MarketStatus, ConnectionState.
 */
import { formatAmerican, formatPercent, formatEvPerUnit } from "@propstein/core";

export function PriceComparison({
  americanOdds,
  breakEven,
  modelProbability,
  evPerUnit,
}: {
  americanOdds?: number;
  breakEven?: number;
  modelProbability?: number;
  evPerUnit?: number;
}) {
  const hasData = americanOdds !== undefined || breakEven !== undefined;
  if (!hasData) {
    return <div className="price-comparison price-comparison--empty">NO VERIFIED PRICE</div>;
  }
  return (
    <div className="price-comparison">
      <div>
        <span className="label">SPORTSBOOK PRICE</span>
        <span className="value num">{americanOdds !== undefined ? formatAmerican(americanOdds) : "—"}</span>
      </div>
      <div>
        <span className="label">BREAK-EVEN</span>
        <span className="value num">{breakEven !== undefined ? formatPercent(breakEven) : "—"}</span>
      </div>
      <div>
        <span className="label">MODEL</span>
        <span className="value num">{modelProbability !== undefined ? formatPercent(modelProbability, 1) : "—"}</span>
      </div>
      <div>
        <span className="label">EV</span>
        <span className={`value num num--${(evPerUnit ?? 0) > 0 ? "positive" : (evPerUnit ?? 0) < 0 ? "negative" : "neutral"}`}>
          {evPerUnit !== undefined ? formatEvPerUnit(evPerUnit) : "—"}
        </span>
      </div>
    </div>
  );
}

export function MarketStatus({ status, observed = true }: { status: string; observed?: boolean }) {
  const tone = status === "OPEN" ? "ok" : status === "SUSPENDED" || status === "CLOSED" ? "warn" : "muted";
  return (
    <span className={`market-status market-status--${tone}`}>
      {status}
      {observed ? " (OBSERVED)" : ""}
    </span>
  );
}

export type ConnectionQuality = "live" | "reconnecting" | "offline";

export function ConnectionState({ quality, detail }: { quality: ConnectionQuality; detail?: string }) {
  const label = quality === "live" ? "CONNECTED" : quality === "reconnecting" ? "RECONNECTING…" : "OFFLINE";
  return (
    <span className={`connection connection--${quality}`}>
      <i className="dot" aria-hidden="true" />
      {label}
      {detail ? <em> · {detail}</em> : null}
    </span>
  );
}
