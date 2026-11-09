'use client';

/**
 * PropStein — Evidence-First Research Terminal (app shell).
 *
 * Single visible route with client-side surfaces: Slip, Ledger, Record,
 * Alerts, Gate Monitor, Docs. The persistent banner states the product's
 * posture on every surface. Footer is sticky per layout standards.
 */

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { SlipUploader } from '@/components/propstein/slip-uploader';
import { LedgerView } from '@/components/propstein/ledger-view';
import { LuckMeter } from '@/components/propstein/luck-meter';
import { AlertsView } from '@/components/propstein/alerts-view';
import { GateMonitor } from '@/components/propstein/gate-monitor';
import { DocsView } from '@/components/propstein/docs-view';
import { BookOpenText, ClipboardList, FileLock2, Gauge, LineChart, BellRing } from 'lucide-react';

type Surface = 'slip' | 'ledger' | 'record' | 'alerts' | 'gates' | 'docs';

const SURFACES: { id: Surface; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'slip', label: 'Slip', icon: ClipboardList },
  { id: 'ledger', label: 'Ledger', icon: FileLock2 },
  { id: 'record', label: 'Record', icon: LineChart },
  { id: 'alerts', label: 'Alerts', icon: BellRing },
  { id: 'gates', label: 'Gate Monitor', icon: Gauge },
  { id: 'docs', label: 'Docs', icon: BookOpenText },
];

export default function PropSteinTerminal() {
  const [surface, setSurface] = useState<Surface>('slip');
  const [refreshKey, setRefreshKey] = useState(0);
  const [pseudonym, setPseudonym] = useState<string | null>(null);

  const bump = () => setRefreshKey((k) => k + 1);

  if (!pseudonym) {
    fetch('/api/me')
      .then((r) => r.json())
      .then((j) => {
        if (j.ok) setPseudonym(j.user.pseudonym);
      })
      .catch(() => setPseudonym('PS-DEMO1'));
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#FAFAF8]">
      {/* Header */}
      <header className="border-b border-zinc-200 bg-white/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="flex items-center justify-between h-14 gap-4">
            <div className="flex items-baseline gap-3 min-w-0">
              <span className="font-semibold tracking-tight text-[15px] text-zinc-900">PROPSTEIN</span>
              <span className="hidden sm:inline text-[12px] text-zinc-400 truncate">Evidence-First Research Terminal</span>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {pseudonym && (
                <span className="pst-num text-[11px] text-zinc-400 border border-zinc-200 rounded-sm px-1.5 py-0.5">
                  {pseudonym}
                </span>
              )}
              <span className="hidden md:inline text-[11px] text-zinc-400 border border-zinc-200 rounded-sm px-1.5 py-0.5">
                plan: pro
              </span>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto -mb-px" aria-label="Terminal surfaces">
            {SURFACES.map((s) => {
              const Icon = s.icon;
              const activeNow = surface === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => setSurface(s.id)}
                  aria-current={activeNow ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-2 text-[12.5px] border-b-2 transition-colors whitespace-nowrap',
                    activeNow
                      ? 'border-zinc-900 text-zinc-900 font-medium'
                      : 'border-transparent text-zinc-500 hover:text-zinc-800',
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {s.label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Persistent posture banner */}
      <div className="bg-zinc-900 text-zinc-100" role="note">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-2">
          <p className="text-[11.5px] leading-snug text-zinc-300">
            This is not a betting recommendation. PropStein records prices, uncertainty, provenance, and your own
            record — nothing else. No picks. No sizing guidance. No urgency language. Actionable-signal surfaces stay
            disabled until a preregistered gate passes per sport.
          </p>
        </div>
      </div>

      {/* Main */}
      <main className="flex-1 mx-auto w-full max-w-6xl px-4 sm:px-6 py-6">
        {surface === 'slip' && (
          <SlipUploader
            onSaved={() => {
              bump();
              setSurface('ledger');
            }}
          />
        )}
        {surface === 'ledger' && <LedgerView refreshKey={refreshKey} />}
        {surface === 'record' && <LuckMeter refreshKey={refreshKey} />}
        {surface === 'alerts' && <AlertsView />}
        {surface === 'gates' && <GateMonitor />}
        {surface === 'docs' && <DocsView />}
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-zinc-200 bg-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-4 space-y-1.5">
          <p className="text-[11.5px] text-zinc-500 leading-snug">
            PropStein is a research and record-keeping product. It does not place, prepare, or automate wagers, and it
            makes no actionable-signal claims before preregistered evidence exists. This is not a betting
            recommendation.
          </p>
          <p className="text-[11.5px] text-zinc-500 leading-snug">
            21+. If gambling is causing problems for you or someone close to you, help is available: call 1-800-GAMBLER.
          </p>
          <p className="text-[10.5px] text-zinc-400 pst-num">
            Reference build — simulated market, closing, and settlement providers are labelled as simulated data.
          </p>
        </div>
      </footer>
    </div>
  );
}
