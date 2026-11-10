'use client';

/**
 * PropStein — unhandled root error boundary (last line of defense).
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body style={{ backgroundColor: '#090A0F', color: '#e7e9ee', fontFamily: 'var(--font-sans), system-ui, sans-serif' }}>
        <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1.5rem' }}>
          <div style={{ maxWidth: '28rem', width: '100%', border: '1px solid rgba(255,255,255,0.07)', background: '#12141C', borderRadius: 8, padding: 24, textAlign: 'center' }}>
            <p style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', color: '#fda4af' }}>TERMINAL STATE: DEGRADED</p>
            <p style={{ fontSize: 12.5, color: '#8b90a0', marginTop: 8, lineHeight: 1.5 }}>
              The terminal hit an unrecoverable rendering error. Your ledger records are stored server-side and were not
              affected.
            </p>
            {error.digest && (
              <p style={{ fontSize: 11, color: '#5c6270', marginTop: 8, fontFamily: 'var(--font-mono), monospace' }}>
                digest: {error.digest}
              </p>
            )}
            <button
              onClick={reset}
              style={{ marginTop: 16, border: '1px solid rgba(99,102,241,0.5)', background: 'rgba(99,102,241,0.15)', color: '#c7d2fe', borderRadius: 6, padding: '6px 16px', fontSize: 12.5, cursor: 'pointer' }}
            >
              Retry
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
