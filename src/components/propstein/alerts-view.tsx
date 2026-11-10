'use client';

/**
 * PropStein — Alerts view (module 6 UI).
 * Opt-in by type, daily push cap, factual feed with snapshot time + source +
 * ledger linkage. No urgency language anywhere.
 */

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/hooks/use-toast';
import { Note, SectionLabel, fmtEt } from './shared';
import type { AlertType } from '@/lib/domain/types';

const TYPE_LABELS: Record<string, string> = {
  quote_changed: 'Saved quote changed',
  quote_aged: 'Saved quote aged',
  player_status: 'Player status changed',
  market_suspended: 'Market suspended',
  closing_available: 'Closing reference available',
  entry_settled: 'Saved entry settled',
  entry_unevaluable: 'Saved entry unevaluable',
};

interface FeedItem {
  id: string;
  ledgerEntryId: string | null;
  type: string;
  message: string;
  snapshotTimeUtc: string;
  sourceProvider: string;
  createdAtUtc: string;
}

export function AlertsView() {
  const { toast } = useToast();
  const [prefs, setPrefs] = useState<{ type: string; enabled: boolean }[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [p, f] = await Promise.all([fetch('/api/alerts').then((r) => r.json()), fetch('/api/alerts/preferences').then((r) => r.json())]);
    if (f.ok) setPrefs(f.preferences ?? []);
    if (p.ok) setFeed(p.feed ?? []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = useCallback(
    async (type: string, enabled: boolean) => {
      setPrefs((prev) => prev.map((p) => (p.type === type ? { ...p, enabled } : p)));
      await fetch('/api/alerts/preferences', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ enabled: { [type]: enabled } }),
      });
    },
    [],
  );

  const evaluate = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetch('/api/alerts/evaluate', { method: 'POST' });
      const json = await res.json();
      if (json.ok) {
        setFeed(json.feed ?? []);
        toast({
          title: 'Alert evaluation complete',
          description: `${json.created} delivered · ${json.suppressed.length} suppressed (muted, daily cap, stale, or disabled by preference).`,
        });
      }
    } finally {
      setBusy(false);
    }
  }, [toast]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Tracked-entry alerts</h2>
        <p className="mt-0.5 text-[12.5px] text-zinc-500 max-w-2xl">
          Opt-in, low-volume, factual updates on entries you saved. Alerts carry snapshot time and source, link to the
          immutable ledger entry, and never contain entry, exit, sizing, or timing instructions. Daily cap: at most 3
          push notifications per user; non-urgent updates are batched.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="pst-card rounded-md p-4">
          <SectionLabel>Alert preferences</SectionLabel>
          <div className="mt-2 space-y-2">
            {prefs.map((p) => (
              <div key={p.type} className="flex items-center justify-between gap-3">
                <span className="text-[12.5px] text-zinc-300">{TYPE_LABELS[p.type] ?? p.type}</span>
                <Switch checked={p.enabled} onCheckedChange={(v) => toggle(p.type, v)} aria-label={`Toggle ${TYPE_LABELS[p.type] ?? p.type} alerts`} />
              </div>
            ))}
          </div>
          <Note>
            If freshness cannot be verified, a STALE QUOTE state is sent or the alert is suppressed. No model-derived
            content appears until the sport-specific preregistered gate passes.
          </Note>
          <Button variant="outline" size="sm" className="mt-3" onClick={evaluate} disabled={busy}>
            {busy ? 'Evaluating…' : 'Evaluate updates on saved entries'}
          </Button>
        </div>

        <div className="pst-card rounded-md p-4">
          <SectionLabel>Alert feed</SectionLabel>
          <div className="mt-2 space-y-2 max-h-80 overflow-y-auto">
            {feed.length === 0 && <p className="text-[12.5px] text-zinc-500 py-6 text-center">No alerts yet. Alerts appear for entries you saved and opted into.</p>}
            {feed.map((a) => (
              <div key={a.id} className="border-l-2 border-white/[0.07] pl-3 py-1">
                <div className="text-[13px] text-zinc-200">{a.message}</div>
                <div className="text-[11px] text-zinc-400 pst-num mt-0.5">
                  {TYPE_LABELS[a.type] ?? a.type} · snapshot {fmtEt(a.snapshotTimeUtc)} · source {a.sourceProvider} · entry{' '}
                  {a.ledgerEntryId ?? '—'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
