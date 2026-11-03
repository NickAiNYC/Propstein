// src/components/LegalTermsModal.tsx
import React, { useEffect } from "react";

interface LegalTermsModalProps {
  onClose: () => void;
}

export const LegalTermsModal: React.FC<LegalTermsModalProps> = ({ onClose }) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 backdrop-blur-sm p-4 font-mono text-slate-200"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl rounded-xl border border-zinc-700 bg-[#161a23] p-6 shadow-2xl space-y-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-700 pb-3">
          <div>
            <span className="text-[10px] uppercase tracking-widest text-emerald-400 font-bold">
              Institutional Compliance & Terms
            </span>
            <h3 className="text-base font-bold text-white mt-0.5">
              PropWire Service Disclaimers &amp; Terms of Use
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs text-zinc-300 hover:text-white"
          >
            [ESC / Close]
          </button>
        </div>

        <div className="space-y-4 text-xs text-zinc-300 leading-relaxed">
          <section>
            <h4 className="font-bold text-white uppercase text-[11px] mb-1">
              1. Quantitative Research Software Only
            </h4>
            <p>
              PropWire is an independent quantitative research terminal, mathematical modeling engine, and cryptographic data clearinghouse. PropWire is not a sportsbook, bookmaker, gambling operator, or gaming vendor. We do not accept, broker, facilitate, or place wagers of any kind.
            </p>
          </section>

          <section>
            <h4 className="font-bold text-white uppercase text-[11px] mb-1">
              2. Zero Outcome Guarantees
            </h4>
            <p>
              All metrics—including fair lines, compound negative binomial-gamma distributions, break-even hurdles, expected values, and closing line value (CLV) realization—are algorithmic statistical estimates derived from historical data. Past performance and positive expected return (+EV) do not guarantee future results.
            </p>
          </section>

          <section>
            <h4 className="font-bold text-white uppercase text-[11px] mb-1">
              3. User Jurisdiction &amp; Legal Responsibility
            </h4>
            <p>
              Users are solely responsible for ensuring that their use of analytical data complies with all applicable municipal, state, federal, and national laws in their jurisdiction. If sports wagering is prohibited in your jurisdiction, you may only use this software for statistical analysis and educational purposes.
            </p>
          </section>

          <section>
            <h4 className="font-bold text-white uppercase text-[11px] mb-1">
              4. Responsible Gaming
            </h4>
            <p>
              Wagering involves financial risk. Never wager funds you cannot afford to lose. If you or someone you know has a gambling problem and wants help, crisis counseling and referral services can be accessed by calling 1-800-GAMBLER (1-800-426-2537) or visiting ncpgambling.org. 21+ only.
            </p>
          </section>

          <section>
            <h4 className="font-bold text-white uppercase text-[11px] mb-1">
              5. Fail-Closed Anomaly Defense
            </h4>
            <p>
              PropWire enforces hardcoded execution gates (12% anomaly ceiling) to safeguard bankrolls against unmodeled news, provider typos, and suspended alt-lines. Data provided through diagnostic feeds flagged with AGENT_EXECUTION_DIRECTIVE: DO_NOT_BET_QUARANTINED_RECORD must never be executed automatically.
            </p>
          </section>
        </div>

        {/* Mandatory Legal Acceptance Checkbox */}
        <div className="border-t border-zinc-700/80 pt-4 space-y-3">
          <label className="flex items-start gap-2.5 text-xs text-zinc-300 cursor-pointer select-none">
            <input
              type="checkbox"
              id="acceptTermsCheckbox"
              className="mt-0.5 rounded border-zinc-700 bg-zinc-900 text-emerald-500 focus:ring-0 focus:ring-offset-0"
              onChange={(e) => {
                const btn = document.getElementById("confirmTermsBtn") as HTMLButtonElement;
                if (btn) btn.disabled = !e.target.checked;
              }}
            />
            <span>
              I have read, understood, and accept the Quantitative Research Terms of Service and Disclaimers.
            </span>
          </label>

          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-zinc-500">Version: v1.0.0-2026-10 · RFC-8785 Audit Log</span>
            <button
              id="confirmTermsBtn"
              disabled
              onClick={async () => {
                try {
                  await fetch("/api/legal/accept-terms", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ terms_version: "v1.0.0-2026-10" }),
                  });
                } catch (_) {}
                onClose();
              }}
              className="rounded bg-emerald-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              Accept &amp; Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
