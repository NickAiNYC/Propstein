// src/components/SubscriberDashboard.tsx
import React, { useState } from "react";

interface SubscriberDashboardProps {
  userEmail: string;
  tier: "PRO" | "QUANT";
  keyPrefix?: string;
  onLogout?: () => void;
}

export const SubscriberDashboard: React.FC<SubscriberDashboardProps> = ({
  userEmail,
  tier,
  keyPrefix = "pw_live_••••••••",
  onLogout,
}) => {
  const [rotating, setRotating] = useState(false);
  const [rotationStatus, setRotationStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRotateKey() {
    const confirmRotate = window.confirm(
      "Rotate API Key?\n\nYour existing key will be immediately invalidated. A newly generated cryptographic key will be dispatched to your account email."
    );
    if (!confirmRotate) return;

    setRotating(true);
    setRotationStatus(null);
    setError(null);

    try {
      const res = await fetch("/api/billing/rotate-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Failed to rotate API key.");
      }

      setRotationStatus(
        data.message || "New API key dispatched to your verified email address."
      );
    } catch (err: any) {
      setError(err.message || "Key rotation failed.");
    } finally {
      setRotating(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#080c14] text-slate-100 font-mono p-4 sm:p-8">
      <div className="mx-auto max-w-4xl space-y-6">
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <h1 className="text-lg font-bold text-white tracking-wider">
              PropWire SUBSCRIBER PORTAL
            </h1>
          </div>
          {onLogout && (
            <button
              onClick={onLogout}
              className="rounded border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-slate-300 hover:bg-zinc-800 hover:text-white transition-colors"
            >
              Sign Out
            </button>
          )}
        </div>

        {/* Status Alerts */}
        {rotationStatus && (
          <div className="rounded border border-emerald-500/40 bg-emerald-950/20 p-4 text-xs text-emerald-300 flex items-center justify-between">
            <span>✓ {rotationStatus}</span>
            <button
              onClick={() => setRotationStatus(null)}
              className="text-emerald-400 hover:text-white"
            >
              ×
            </button>
          </div>
        )}
        {error && (
          <div className="rounded border border-red-500/40 bg-red-950/20 p-4 text-xs text-red-300 flex items-center justify-between">
            <span>⚠ {error}</span>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-white"
            >
              ×
            </button>
          </div>
        )}

        {/* Subscription Metadata Card */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[11px] text-zinc-400 uppercase tracking-widest">
                Account Status
              </span>
              <div className="text-sm font-semibold text-white mt-0.5">
                {userEmail}
              </div>
            </div>
            <span className="rounded border border-emerald-500/40 bg-emerald-950/40 px-3 py-1 text-xs font-bold text-emerald-400">
              {tier} TIER ACTIVE
            </span>
          </div>

          <div className="grid sm:grid-cols-2 gap-4 pt-2">
            <div className="rounded bg-zinc-950/70 p-3 border border-zinc-800/80">
              <span className="text-[10px] text-zinc-400 uppercase">
                Zero-Trust Ingestion Access
              </span>
              <div className="text-xs text-emerald-300 font-semibold mt-1">
                {tier === "QUANT" ? "300 req/min · WebSocket Surge Stream" : "50 req/min · Low-Latency Terminal"}
              </div>
            </div>
            <div className="rounded bg-zinc-950/70 p-3 border border-zinc-800/80">
              <span className="text-[10px] text-zinc-400 uppercase">
                Discord Community Status
              </span>
              <div className="text-xs text-emerald-300 font-semibold mt-1">
                {tier === "QUANT" ? "@Quant Syndicate Verified" : "@Receipt Verified"}
              </div>
            </div>
          </div>
        </div>

        {/* API Key Management (Zero-Trust) */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
          <div>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Cryptographic Key Lifecycle
            </h2>
            <p className="text-xs text-zinc-400 mt-1">
              Plaintext API keys are never stored in our database. We store only SHA-256 digests. If you misplace your key, execute an immediate on-demand rotation.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 rounded-lg bg-zinc-950 p-4 border border-zinc-800">
            <div>
              <span className="text-[10px] text-zinc-500 uppercase">Key Fingerprint</span>
              <div className="text-xs text-zinc-200 font-mono mt-0.5">{keyPrefix}</div>
            </div>
            <button
              onClick={handleRotateKey}
              disabled={rotating}
              className="rounded border border-indigo-500/40 bg-indigo-950/40 px-4 py-2 text-xs font-semibold text-indigo-300 hover:bg-indigo-900/50 hover:text-white transition-all disabled:opacity-50"
            >
              {rotating ? "Generating & Dispatching…" : "Rotate API Key"}
            </button>
          </div>
        </div>

        {/* Claude Desktop / MCP Configuration Snippet */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Model Context Protocol (MCP) Setup
            </h2>
            <span className="text-[10px] text-zinc-400">claude_desktop_config.json</span>
          </div>
          <pre className="rounded bg-zinc-950 p-4 text-[11px] text-emerald-300 overflow-x-auto border border-zinc-800">
{`{
  "mcpServers": {
    "propwire": {
      "command": "npx",
      "args": ["-y", "@propwire/mcp-server"],
      "env": {
        "PropWire_API_KEY": "${keyPrefix.includes("•") ? "pw_live_your_key_here" : keyPrefix}"
      }
    }
  }
}`}
          </pre>
        </div>
      </div>
    </div>
  );
};
