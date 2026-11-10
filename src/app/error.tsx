'use client';

/**
 * PropStein — route error boundary (fail closed, dark themed).
 * Renders an explicit degraded state; never a blank screen.
 */

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Structured client-side error report (mirrors server audit events).
    console.error(
      JSON.stringify({
        level: 'error',
        surface: 'app',
        digest: error.digest ?? null,
        message: error.message,
        at: new Date().toISOString(),
      }),
    );
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#090A0F] px-6">
      <div className="max-w-md w-full rounded-lg border border-white/[0.07] bg-[#12141C] p-6 pst-sheen text-center">
        <p className="text-[13px] font-medium tracking-wide text-rose-300">TERMINAL STATE: DEGRADED</p>
        <p className="text-[12.5px] text-zinc-400 mt-2 leading-relaxed">
          A surface failed to render. No stored records were affected — the ledger is append-only and every computation
          remains reproducible from its snapshot, model version, and seed.
        </p>
        {error.digest && <p className="text-[11px] text-zinc-600 pst-num mt-2">digest: {error.digest}</p>}
        <button
          onClick={reset}
          className="mt-4 rounded-md border border-indigo-500/50 bg-indigo-500/15 px-4 py-1.5 text-[12.5px] text-indigo-200 hover:bg-indigo-500/25 transition-colors"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
