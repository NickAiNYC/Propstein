// src/components/RootHashInspectModal.tsx
import React, { useState, useEffect } from "react";
import type { VerifiedReceiptData } from "./VerifiedReceiptCard";

interface InspectModalProps {
  rootHash: string;
  onClose: () => void;
}

export const RootHashInspectModal: React.FC<InspectModalProps> = ({
  rootHash,
  onClose,
}) => {
  const [auditData, setAuditData] = useState<VerifiedReceiptData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 1. Handle ESC key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // 2. Fetch the audit chain
  useEffect(() => {
    async function fetchAuditChain() {
      setLoading(true);
      setError(null);
      try {
        // Strip the '#' if it was passed from the UI
        const cleanHash = rootHash.replace(/^#/, "");
        
        const res = await fetch("/api/v1/verify-receipt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ receipt_hash: cleanHash }),
        });
        
        const json = await res.json();
        
        if (!res.ok) {
          throw new Error(json.error || "Failed to resolve cryptographic root.");
        }
        
        setAuditData(json);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchAuditChain();
  }, [rootHash]);

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 font-mono"
      onClick={onClose} // Click outside to close
    >
      <div 
        className="relative w-full max-w-2xl rounded-xl border border-emerald-500/40 bg-[#090d16] p-6 text-slate-100 shadow-2xl"
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <span className="text-xs uppercase tracking-widest text-emerald-400">
              Cryptographic Root Audit
            </span>
            <h3 className="text-lg font-bold text-white mt-0.5">
              Chain Head: #{rootHash.replace(/^#/, "").slice(0, 16)}…
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
          >
            [ESC / Close]
          </button>
        </div>

        {/* Content Body */}
        <div className="mt-4 max-h-[60vh] overflow-y-auto space-y-4 text-xs pr-2">
          {loading ? (
            <div className="py-12 text-center text-slate-400 animate-pulse">
              Re-computing RFC-8785 SHA-256 chain verification across nodes...
            </div>
          ) : error ? (
            <div className="py-8 text-center text-red-400 border border-red-500/20 bg-red-950/20 rounded">
              ⚠ {error}
            </div>
          ) : auditData ? (
            <>
              {/* Trust State Banner */}
              <div className="rounded border border-emerald-500/30 bg-emerald-950/20 p-3 flex items-center justify-between">
                <div>
                  <span className="text-slate-400">OVERALL TRUST STATE:</span>
                  <span className="ml-2 font-bold text-emerald-400">
                    {auditData.integrity.overall_trust}
                  </span>
                </div>
                <div className="text-right text-[11px] text-slate-400">
                  Stage: <span className="text-emerald-300">{auditData.integrity.lifecycle_stage}</span>
                </div>
              </div>

              {/* 3-Hash Visual Chain */}
              <div className="space-y-3 mt-4">
                {/* Stage 1 */}
                <div className="rounded bg-slate-900/50 p-3 border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-emerald-400 font-bold">1. ENTRY RECEIPT</span>
                    <span className="text-slate-500">
                      Valid: {auditData.integrity.entry_receipt_valid ? "✅" : "❌"}
                    </span>
                  </div>
                  <div className="text-slate-300">
                    {auditData.lifecycle.entry.player} ({auditData.lifecycle.entry.direction} {auditData.lifecycle.entry.line})
                  </div>
                  <div className="text-[10px] text-slate-500 break-all mt-1">
                    SHA-256: {auditData.lifecycle.entry.receipt_hash}
                  </div>
                </div>

                {/* Stage 2 */}
                <div className="rounded bg-slate-900/50 p-3 border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-emerald-400 font-bold">2. T-0 CLOSING LOCK</span>
                    <span className="text-slate-500">
                      Valid: {auditData.integrity.closing_snapshot_valid === null ? "⧗ PENDING" : auditData.integrity.closing_snapshot_valid ? "✅" : "❌"}
                    </span>
                  </div>
                  {auditData.lifecycle.closing ? (
                    <>
                      <div className="text-slate-300">
                        Close Line: {auditData.lifecycle.closing.line} (Fair: {auditData.lifecycle.closing.fair_line})
                      </div>
                      <div className="text-[10px] text-slate-500 break-all mt-1">
                        SHA-256: {auditData.lifecycle.closing.snapshot_hash}
                      </div>
                    </>
                  ) : (
                    <div className="text-slate-500 italic">Awaiting kickoff...</div>
                  )}
                </div>

                {/* Stage 3 */}
                <div className="rounded bg-slate-900/50 p-3 border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-emerald-400 font-bold">3. SETTLEMENT</span>
                    <span className="text-slate-500">
                      Valid: {auditData.integrity.settlement_receipt_valid === null ? "⧗ PENDING" : auditData.integrity.settlement_receipt_valid ? "✅" : "❌"}
                    </span>
                  </div>
                  {auditData.lifecycle.settlement ? (
                    <>
                      <div className="text-slate-300">
                        Outcome: {auditData.lifecycle.settlement.outcome} (CLV: {auditData.lifecycle.settlement.clv_no_vig_pct}%)
                      </div>
                      <div className="text-[10px] text-slate-500 break-all mt-1">
                        SHA-256: {auditData.lifecycle.settlement.settlement_hash}
                      </div>
                    </>
                  ) : (
                    <div className="text-slate-500 italic">Awaiting final boxscore...</div>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </div>

        {/* Footer info */}
        <div className="mt-4 border-t border-slate-800 pt-3 flex justify-between text-[10px] text-slate-500">
          <span>Git Anchor: git:commit:9f8e7d6c5b</span>
          <span>RFC-8785 Canonical JSON</span>
        </div>
      </div>
    </div>
  );
};
