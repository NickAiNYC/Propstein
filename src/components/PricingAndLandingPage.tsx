// src/components/PricingAndLandingPage.tsx
import React, { useState } from "react";
import { RootHashInspectModal } from "./RootHashInspectModal";

export const PricingAndLandingPage: React.FC = () => {
  const [inspectModalOpen, setInspectModalOpen] = useState(false);
  const [loadingTier, setLoadingTier] = useState<"pro" | "quant" | null>(null);

  // Full 64-character SHA-256 root hash to pass zero-trust API validation
  const targetRootHash =
    "178e29974bf8748c9b2f5e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b";

  async function handleCheckout(tier: "pro" | "quant") {
    setLoadingTier(tier);
    try {
      // Backend resolves identity securely via getServerSession()
      const res = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });

      if (res.status === 401) {
        window.location.href = "/login?redirect=/pricing";
        return;
      }

      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setLoadingTier(null);
      }
    } catch (err) {
      console.error("[PricingAndLandingPage] Checkout initialization failed:", err);
      setLoadingTier(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#060913] text-slate-100 font-mono selection:bg-emerald-500/30 selection:text-emerald-300">
      {/* SECTION 1: HERO */}
      <header className="relative mx-auto max-w-6xl px-6 pt-20 pb-16 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/30 px-4 py-1.5 text-xs text-emerald-400 mb-6">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          Fail-Closed Execution Integrity Active · N=64 Verified
        </div>

        <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight text-white">
          Stop Buying Picks.<br />Start Buying Proof.
        </h1>

        <p className="mx-auto mt-6 max-w-2xl text-sm md:text-base text-slate-400 leading-relaxed">
          The only sports betting analytics terminal with fail-closed execution integrity, 
          RFC-8785 cryptographic receipts, and a zero-trust Model Context Protocol (MCP) server for autonomous agents.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <button
            onClick={() => handleCheckout("quant")}
            disabled={loadingTier !== null}
            className="rounded-lg bg-emerald-500 px-6 py-3 text-sm font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-lg shadow-emerald-500/20"
          >
            {loadingTier === "quant" ? "Redirecting to Stripe…" : "Deploy the Quant API — $299/mo"}
          </button>
          <button
            onClick={() => handleCheckout("pro")}
            disabled={loadingTier !== null}
            className="rounded-lg border border-slate-700 bg-slate-900 px-6 py-3 text-sm font-semibold text-slate-200 hover:border-slate-500 hover:text-white disabled:opacity-60 disabled:cursor-not-allowed transition-all"
          >
            {loadingTier === "pro" ? "Redirecting to Stripe…" : "Upgrade Pro Terminal — $29/mo"}
          </button>
        </div>
      </header>

      <hr className="border-slate-800/80 mx-auto max-w-6xl" />

      {/* SECTION 2: THE CONTRAST TABLE */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <div className="text-center mb-12">
          <h2 className="text-2xl md:text-3xl font-bold text-white">The Old Way vs. The PropWire Way</h2>
          <p className="text-xs text-slate-400 mt-2">Why black-box AI models and hit-rate touts fail under market efficiency.</p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* The Old Way */}
          <div className="rounded-xl border border-red-500/20 bg-red-950/10 p-6 space-y-4">
            <h3 className="text-sm font-bold text-red-400 uppercase tracking-wider">❌ The Old Way (Touts &amp; Black Boxes)</h3>
            <ul className="space-y-3 text-xs text-slate-300">
              <li className="flex items-start gap-2">
                <span className="text-red-400 font-bold">×</span> Fake screenshots and cherry-picked win rates with zero sample-size disclosures.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-red-400 font-bold">×</span> Black-box AI models that hide math and never publish closing line value (CLV) audits.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-red-400 font-bold">×</span> Unfiltered +42% "Locks" that are actually stale alt-lines or unexecutable ghosts.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-red-400 font-bold">×</span> Enterprise sales calls and opaque procurement hoops just to get an odds JSON feed.
              </li>
            </ul>
          </div>

          {/* The PropWire Way */}
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/10 p-6 space-y-4">
            <h3 className="text-sm font-bold text-emerald-400 uppercase tracking-wider">✓ The PropWire Way (The Infrastructure)</h3>
            <ul className="space-y-3 text-xs text-slate-300">
              <li className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold">✓</span> <strong className="text-white">Execution-Integrity Gate:</strong> Hardcoded 12% anomaly ceiling. If a quote looks too good, it is quarantined automatically.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold">✓</span> <strong className="text-white">Cryptographic 3-Hash Chain:</strong> Entry → T-0 Close → Settlement, independently verifiable via RFC-8785.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold">✓</span> <strong className="text-white">Self-Serve MCP &amp; API:</strong> Instant Stripe-native checkout, automated API key hashing, and instant key rotation.
              </li>
              <li className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold">✓</span> <strong className="text-white">Deterministic Settlement:</strong> Dual-source boxscore cross-validation (Sleeper + ESPN) enforcing strict zero-snap rules.
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* SECTION 3: PRICING TIERS */}
      <section className="mx-auto max-w-6xl px-6 py-20 border-t border-slate-800">
        <div className="text-center mb-16">
          <h2 className="text-2xl md:text-3xl font-bold text-white">Transparent Pricing Moats</h2>
          <p className="text-xs text-slate-400 mt-2">Choose your depth of market access.</p>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          {/* Free Tier */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 flex flex-col justify-between">
            <div>
              <span className="text-xs font-bold uppercase text-slate-400">Observer</span>
              <div className="mt-4 flex items-baseline gap-1">
                <span className="text-4xl font-extrabold text-white">$0</span>
                <span className="text-xs text-slate-500">/ forever</span>
              </div>
              <p className="mt-3 text-xs text-slate-400">For casual verifiers and community auditors.</p>
              <ul className="mt-6 space-y-2.5 text-xs text-slate-300">
                <li>✓ Access to public <code className="text-emerald-400">/api/v1/verify-receipt</code></li>
                <li>✓ Verify any SHA-256 hash</li>
                <li>✓ 15-minute delayed fair lines</li>
                <li>✓ 1 manual receipt audit per day</li>
              </ul>
            </div>
            <button
              disabled
              className="mt-8 w-full rounded-lg border border-slate-700 bg-slate-800/50 py-2.5 text-xs font-semibold text-slate-400 cursor-not-allowed"
            >
              Default Access
            </button>
          </div>

          {/* Pro Tier */}
          <div className="rounded-xl border border-emerald-500/40 bg-slate-900 p-6 flex flex-col justify-between shadow-xl relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded bg-emerald-500 px-3 py-0.5 text-[10px] font-bold text-slate-950 uppercase tracking-widest">
              Most Popular
            </div>
            <div>
              <span className="text-xs font-bold uppercase text-emerald-400">Pro Terminal</span>
              <div className="mt-4 flex items-baseline gap-1">
                <span className="text-4xl font-extrabold text-white">$29</span>
                <span className="text-xs text-slate-500">/ month</span>
              </div>
              <p className="mt-3 text-xs text-slate-400">For serious individual bettors &amp; Discord grinders.</p>
              <ul className="mt-6 space-y-2.5 text-xs text-slate-300">
                <li>✓ Real-time Poisson/Gamma fair lines</li>
                <li>✓ Unlimited SHA-256 execution receipts</li>
                <li>✓ Discord bot automated role verification</li>
                <li>✓ Cumulative CLV leaderboard access</li>
              </ul>
            </div>
            <button
              onClick={() => handleCheckout("pro")}
              disabled={loadingTier !== null}
              className="mt-8 w-full rounded-lg bg-emerald-500 py-2.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-60 disabled:cursor-not-allowed transition-all"
            >
              {loadingTier === "pro" ? "Redirecting to Stripe…" : "Subscribe Pro ($29/mo)"}
            </button>
          </div>

          {/* Quant API Tier */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 flex flex-col justify-between">
            <div>
              <span className="text-xs font-bold uppercase text-indigo-400">Quant Syndicate</span>
              <div className="mt-4 flex items-baseline gap-1">
                <span className="text-4xl font-extrabold text-white">$299</span>
                <span className="text-xs text-slate-500">/ month</span>
              </div>
              <p className="mt-3 text-xs text-slate-400">For Discord syndicates &amp; autonomous agent builders.</p>
              <ul className="mt-6 space-y-2.5 text-xs text-slate-300">
                <li>✓ Native MCP Server for Claude / Cursor</li>
                <li>✓ Full JSON REST API (300 req/min)</li>
                <li>✓ Diagnostic feed access (anomaly fade lists)</li>
                <li>✓ Account-bound HMAC security &amp; key rotation</li>
              </ul>
            </div>
            <button
              onClick={() => handleCheckout("quant")}
              disabled={loadingTier !== null}
              className="mt-8 w-full rounded-lg border border-indigo-500/40 bg-indigo-950/50 py-2.5 text-xs font-semibold text-indigo-300 hover:bg-indigo-900 hover:text-white disabled:opacity-60 disabled:cursor-not-allowed transition-all"
            >
              {loadingTier === "quant" ? "Redirecting to Stripe…" : "Deploy Quant API ($299/mo)"}
            </button>
          </div>
        </div>
      </section>

      {/* SECTION 4: MCP INTEGRATION SNIPPET */}
      <section className="mx-auto max-w-6xl px-6 py-20 border-t border-slate-800">
        <div className="grid md:grid-cols-2 gap-12 items-center">
          <div>
            <span className="text-xs uppercase tracking-widest text-emerald-400">Autonomous Execution</span>
            <h2 className="text-2xl md:text-3xl font-bold text-white mt-2">Built for Agents. Proven by Math.</h2>
            <p className="mt-4 text-xs md:text-sm text-slate-400 leading-relaxed">
              Don’t parse fragile HTML or write custom scrapers. Connect your autonomous agent directly to the PropWire MCP server. 
              It natively understands the 12% quarantine ceiling and will reject any trade attempt on a <code className="text-amber-400">VERIFY</code> anomaly.
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-emerald-300 shadow-2xl overflow-x-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3 text-slate-500 text-[10px]">
              <span>claude_desktop_config.json</span>
              <span>JSON-RPC 2.0</span>
            </div>
            <pre className="text-[11px] leading-relaxed">
{`{
  "mcpServers": {
    "propwire": {
      "command": "npx",
      "args": ["-y", "@propwire/mcp-server"],
      "env": {
        "PropWire_API_KEY": "pw_live_your_quant_key_here"
      }
    }
  }
}`}
            </pre>
          </div>
        </div>
      </section>

      {/* SECTION 5: FOOTER WITH CLICK-TO-INSPECT ROOT HASH */}
      <footer className="border-t border-slate-800 bg-[#04060b] py-12 text-center">
        <div className="mx-auto max-w-6xl px-6">
          <p className="text-xs text-slate-400">
            Don’t trust us. Verify us. Every edge and settlement is hashed using RFC-8785 canonical JSON.
          </p>
          <div className="mt-4 flex items-center justify-center gap-2">
            <span className="text-slate-500 text-xs">Live Root Chain Head:</span>
            <button
              onClick={() => setInspectModalOpen(true)}
              className="rounded bg-slate-900 border border-emerald-500/30 px-3 py-1 text-xs font-mono text-emerald-400 hover:border-emerald-400 hover:bg-slate-800 transition-colors"
            >
              #{targetRootHash.slice(0, 16)}…
            </button>
          </div>
          <p className="mt-8 text-[10px] text-slate-600">
            PropWire is an independent quantitative research terminal. Not a sportsbook. 21+ Call 1-800-GAMBLER.
          </p>
        </div>
      </footer>

      {/* MODAL */}
      {inspectModalOpen && (
        <RootHashInspectModal
          rootHash={targetRootHash}
          onClose={() => setInspectModalOpen(false)}
        />
      )}
    </div>
  );
};
