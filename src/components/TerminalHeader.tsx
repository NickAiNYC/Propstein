// src/components/TerminalHeader.tsx
import React from "react";

interface TerminalHeaderProps {
  activeCount: number;
  latencySeconds: number;
  onOpenPro: () => void;
  onOpenLedger: () => void;
  onOpenAudit: () => void;
}

export const TerminalHeader: React.FC<TerminalHeaderProps> = ({
  activeCount,
  latencySeconds,
  onOpenPro,
  onOpenLedger,
  onOpenAudit,
}) => {
  return (
    // Medium gray quantitative terminal background (#252a34) replacing navy blue (#060913)
    <header className="sticky top-0 z-40 w-full border-b border-zinc-700/80 bg-[#252a34]/95 backdrop-blur-md px-4 py-2.5 font-mono">
      <div className="mx-auto flex max-w-7xl items-center justify-between">
        {/* Brand & Live Status */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
            <span className="text-sm font-extrabold tracking-widest text-white">
              PropWire
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-2 rounded-md border border-zinc-700 bg-zinc-900/60 px-2.5 py-1 text-[11px] text-zinc-300">
            <span className="text-emerald-400 font-semibold">{activeCount} Active</span>
            <span className="text-zinc-500">·</span>
            <span>Feed {latencySeconds}s</span>
          </div>
        </div>

        {/* Professional Navigation Actions (Zero Emojis, Clean Bloomberg Aesthetics) */}
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={onOpenPro}
            className="rounded border border-emerald-500/40 bg-emerald-950/30 px-3 py-1.5 font-semibold text-emerald-400 hover:bg-emerald-900/40 transition-colors"
          >
            PRO $29
          </button>
          <button
            onClick={onOpenLedger}
            className="rounded border border-zinc-700 bg-zinc-900/80 px-3 py-1.5 text-zinc-200 hover:bg-zinc-800 hover:text-white transition-colors"
          >
            Ledger
          </button>
          <button
            onClick={onOpenAudit}
            className="rounded border border-zinc-700 bg-zinc-900/80 px-3 py-1.5 text-zinc-200 hover:bg-zinc-800 hover:text-white transition-colors hidden md:block"
          >
            CLV Audit
          </button>
        </div>
      </div>
    </header>
  );
};
