// src/components/VerifiedReceiptCard.tsx
import React from "react";

export interface VerifiedReceiptData {
  status: "success" | "error";
  integrity: {
    tamper_detected: boolean;
    lifecycle_stage:
      | "TAMPER_DETECTED"
      | "STAGE_1_ENTRY_PROVEN"
      | "STAGE_2_CLV_LOCKED"
      | "STAGE_3_SETTLEMENT_FINALIZED";
    entry_receipt_valid: boolean;
    closing_snapshot_valid: boolean | null;
    settlement_receipt_valid: boolean | null;
    overall_trust: "CRYPTOGRAPHICALLY_PROVEN" | "TAMPER_DETECTED";
  };
  lifecycle: {
    entry: {
      player: string;
      team: string;
      book: string;
      market: string;
      direction: "OVER" | "UNDER";
      line: number;
      price: number;
      fair_line_at_entry: number;
      edge_pct_at_entry: number;
      timestamp: number;
      receipt_hash: string;
      event_id?: string;
      player_id?: string;
      entry_raw_payload_sha256?: string;
    };
    closing: {
      line: number;
      over_odds: number;
      under_odds: number;
      fair_line: number;
      provider_update_ts: number;
      snapshot_hash: string;
    } | null;
    settlement: {
      outcome: string;
      settled_stat: number | null;
      offensive_snaps: number | null;
      clv_delta_yards: number;
      clv_no_vig_pct: number;
      settlement_hash: string;
    } | null;
  };
}

const shortHash = (h?: string | null) =>
  h ? `${h.slice(0, 8)}…${h.slice(-6)}` : "PENDING";

export const VerifiedReceiptCard: React.FC<{ data: VerifiedReceiptData }> = ({
  data,
}) => {
  const { integrity, lifecycle } = data;
  const { entry, closing, settlement } = lifecycle;

  if (integrity.tamper_detected) {
    return (
      <div className="max-w-md rounded-xl border border-red-500/60 bg-slate-950 p-6 font-mono text-red-400">
        <p className="text-xs uppercase tracking-widest">
          ⚠ Cryptographic Verification Failed
        </p>
        <h3 className="mt-2 text-lg font-bold text-white">
          RECEIPT HASH MISMATCH
        </h3>
        <p className="mt-1 text-xs text-slate-400">
          One or more payload fields do not match the canonical RFC-8785 SHA-256 digest.
        </p>
      </div>
    );
  }

  const arrow = entry.direction === "OVER" ? "↑" : "↓";
  const priceFormatted = entry.price > 0 ? `+${entry.price}` : `${entry.price}`;

  return (
    <div className="w-full max-w-md rounded-xl border border-emerald-500/30 bg-[#0b101b] p-6 font-mono text-slate-100 shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400" />
          <span className="text-sm font-bold tracking-wider text-white">
            PropWire
          </span>
          <span className="rounded bg-emerald-950/80 px-2 py-0.5 text-[10px] text-emerald-400 border border-emerald-500/30">
            {integrity.lifecycle_stage.replace(/_/g, " ")}
          </span>
        </div>
        <span className="text-[11px] text-slate-400">{entry.book}</span>
      </div>

      {/* Player & Position Line */}
      <div className="mt-4 flex items-baseline justify-between">
        <div>
          <p className="text-xs uppercase text-slate-400">
            {entry.team} · {entry.market.replace("_", " ")}
          </p>
          <h2 className="mt-0.5 text-xl font-bold text-white">
            {entry.player}
          </h2>
        </div>
        <div className="text-right">
          <span className="text-xl font-bold text-emerald-400">
            {arrow} {entry.line}
          </span>
          <span className="ml-1.5 text-xs text-slate-400">
            ({priceFormatted})
          </span>
          <p className="text-[11px] text-emerald-300/90">
            Fair {entry.fair_line_at_entry.toFixed(1)} · +{entry.edge_pct_at_entry.toFixed(1)}% Edge
          </p>
        </div>
      </div>

      {/* 3-Column Metrics Grid: Entry vs Close vs CLV/Outcome */}
      <div className="mt-5 grid grid-cols-3 gap-2 rounded-lg border border-slate-800/90 bg-slate-900/50 p-3 text-center">
        <div>
          <span className="block text-[10px] text-slate-500">ENTRY LINE</span>
          <span className="mt-1 block text-sm font-bold text-slate-100">
            {arrow} {entry.line}
          </span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-500">CLOSING LINE</span>
          <span className="mt-1 block text-sm font-bold text-slate-100">
            {closing ? `${closing.line}` : "PRE-KICKOFF"}
          </span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-500">VERIFIED CLV</span>
          <span
            className={`mt-1 block text-sm font-bold ${
              settlement && settlement.clv_no_vig_pct >= 0
                ? "text-emerald-400"
                : "text-slate-300"
            }`}
          >
            {settlement
              ? `${settlement.clv_no_vig_pct >= 0 ? "+" : ""}${settlement.clv_no_vig_pct.toFixed(2)}% (${settlement.clv_delta_yards >= 0 ? "+" : ""}${settlement.clv_delta_yards}y)`
              : "LOCKED AT T-0"}
          </span>
        </div>
      </div>

      {/* Cryptographic 3-Hash Chain Ledger */}
      <div className="mt-4 space-y-1.5 border-t border-slate-800/80 pt-3 text-[11px]">
        <div className="flex justify-between">
          <span className="text-slate-500">1. ENTRY SHA-256</span>
          <span className="text-emerald-400">
            ✓ #{shortHash(entry.receipt_hash)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">2. T-0 CLOSE SHA-256</span>
          <span className={closing ? "text-emerald-400" : "text-slate-500"}>
            {closing ? `✓ #${shortHash(closing.snapshot_hash)}` : "⧗ AWAITING T-0"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">3. SETTLEMENT SHA-256</span>
          <span className={settlement ? "text-emerald-400" : "text-slate-500"}>
            {settlement
              ? `✓ #${shortHash(settlement.settlement_hash)} (${settlement.outcome})`
              : "⧗ AWAITING FINAL"}
          </span>
        </div>
      </div>
    </div>
  );
};
