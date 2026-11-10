'use client';

/**
 * PropStein — Slip Uploader (module 1).
 *
 * Flow: upload/paste/manual -> editable extraction with confidence badges ->
 * explicit confirmation -> Hurdle Router assessment -> save to ledger.
 *
 * Rules enforced by this UI:
 *   - Nothing is analyzed before the confirmation checkbox + button.
 *   - OCR confidence below 0.75 highlights fields for manual review.
 *   - Screenshots retained only on opt-in.
 *   - Wager amount is optional and record-only.
 *   - Demo scenario selector injects fail-closed paths (reference build).
 */

import { useCallback, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useToast } from '@/hooks/use-toast';
import { RatingCard } from './rating-card';
import { EvidenceDna } from './evidence-dna';
import { Note, SectionLabel, marketLabel } from './shared';
import type { AssessmentBundle } from '@/lib/server/assessment-service';
import { cn } from '@/lib/utils';

interface ExtractionFields {
  sportsbook: string | null;
  sport: string | null;
  league: string | null;
  eventLabel: string | null;
  eventDate: string | null;
  playerId: string | null;
  playerName: string | null;
  market: string | null;
  marketLabel: string | null;
  selection: 'over' | 'under' | null;
  line: number | null;
  americanOdds: number | null;
  wagerAmount: number | null;
}

interface UploadResponse {
  ok: boolean;
  slipUploadId?: string;
  provider?: string;
  confidence?: number;
  fieldConfidence?: Record<string, number>;
  needsManualConfirmation?: boolean;
  ocrThreshold?: number;
  fields?: ExtractionFields;
  detail?: string;
}

const SCENARIOS: { value: string; label: string }[] = [
  { value: 'none', label: 'Normal pipeline' },
  { value: 'no_market_data', label: 'No market data (INSUFFICIENT MARKET DATA)' },
  { value: 'entitlement_failure', label: 'Entitlement failure (fail closed)' },
  { value: 'stale_quote', label: 'Stale comparison (STALE QUOTE)' },
  { value: 'unverified_context', label: 'Missing weather observed-at (UNVERIFIED CONTEXT)' },
  { value: 'model_outage', label: 'Model surface outage (MODEL UNAVAILABLE)' },
];

const CONF_THRESHOLD = 0.75;

export function SlipUploader({ onSaved }: { onSaved: () => void }) {
  const { toast } = useToast();
  const [inputMode, setInputMode] = useState<'screenshot' | 'paste' | 'manual'>('paste');
  const [pasteText, setPasteText] = useState(
    'NFL · TB @ KC · Nov 8, 1:00 PM ET\nD. Adams — Receiving Yards Over 62.5 (-115)',
  );
  const [retain, setRetain] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [extraction, setExtraction] = useState<{
    slipUploadId: string | null;
    provider: string;
    confidence: number;
    fieldConfidence: Record<string, number>;
    needsManualConfirmation: boolean;
  } | null>(null);
  const [fields, setFields] = useState<ExtractionFields>({
    sportsbook: null,
    sport: 'NFL',
    league: 'NFL',
    eventLabel: 'TB @ KC',
    eventDate: null,
    playerId: null,
    playerName: '',
    market: 'player_reception_yds',
    marketLabel: 'Receiving Yards',
    selection: 'over',
    line: null,
    americanOdds: null,
    wagerAmount: null,
  });
  const [counterpartOdds, setCounterpartOdds] = useState<string>('-105');
  const [book, setBook] = useState<string>('user_entered');
  const [scenario, setScenario] = useState('none');
  const [mode, setMode] = useState<'market' | 'model'>('market');
  const [confirmed, setConfirmed] = useState(false);
  const [assessing, setAssessing] = useState(false);
  const [bundle, setBundle] = useState<AssessmentBundle | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedLedgerId, setSavedLedgerId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const applyExtraction = useCallback((r: UploadResponse) => {
    if (!r.ok || !r.fields) {
      toast({ title: 'Upload failed', description: r.detail ?? 'Nothing was analyzed.' });
      return;
    }
    setExtraction({
      slipUploadId: r.slipUploadId ?? null,
      provider: r.provider ?? 'unknown',
      confidence: r.confidence ?? 0,
      fieldConfidence: r.fieldConfidence ?? {},
      needsManualConfirmation: r.needsManualConfirmation ?? true,
    });
    const f = r.fields;
    setFields({
      sportsbook: f.sportsbook ?? null,
      sport: f.sport ?? 'NFL',
      league: f.league ?? f.sport ?? 'NFL',
      eventLabel: f.eventLabel ?? '',
      eventDate: f.eventDate ?? null,
      playerId: f.playerId ?? null,
      playerName: f.playerName ?? '',
      market: f.market ?? '',
      marketLabel: f.marketLabel ?? null,
      selection: f.selection ?? 'over',
      line: f.line ?? null,
      americanOdds: f.americanOdds ?? null,
      wagerAmount: f.wagerAmount ?? null,
    });
    setBundle(null);
    setSavedLedgerId(null);
    setConfirmed(false);
  }, [toast]);

  const uploadFile = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const form = new FormData();
        form.append('file', file);
        form.append('retain', retain ? 'true' : 'false');
        const res = await fetch('/api/slips/upload', { method: 'POST', body: form });
        applyExtraction(await res.json());
      } catch {
        toast({ title: 'Upload failed', description: 'The screenshot could not be processed. Nothing was analyzed.' });
      } finally {
        setUploading(false);
      }
    },
    [retain, applyExtraction, toast],
  );

  const submitPaste = useCallback(async () => {
    setUploading(true);
    try {
      const res = await fetch('/api/slips/upload', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: pasteText }),
      });
      applyExtraction(await res.json());
    } catch {
      toast({ title: 'Parsing failed', description: 'The slip text could not be parsed. Nothing was analyzed.' });
    } finally {
      setUploading(false);
    }
  }, [pasteText, applyExtraction, toast]);

  const runAssessment = useCallback(async () => {
    if (!confirmed) return;
    setAssessing(true);
    try {
      const res = await fetch('/api/slips/confirm', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          slipUploadId: extraction?.slipUploadId ?? null,
          confirm: true,
          retainScreenshot: retain,
          scenario,
          mode,
          wagerAmount: fields.wagerAmount ?? null,
          fields: {
            sport: fields.sport,
            league: fields.league,
            eventLabel: fields.eventLabel || 'Event TBD',
            eventId: undefined,
            playerName: fields.playerName,
            playerId: undefined,
            market: fields.market,
            marketLabel: fields.marketLabel ?? marketLabel(fields.market ?? ''),
            selection: fields.selection,
            line: fields.line,
            enteredAmericanOdds: fields.americanOdds,
            enteredCounterpartOdds: Number(counterpartOdds),
            book,
            capturedAtUtc: new Date().toISOString(),
          },
        }),
      });
      const json = await res.json();
      if (json.ok) {
        setBundle(json.bundle);
      } else {
        toast({ title: 'Assessment blocked', description: json.detail ?? 'The assessment failed closed.' });
      }
    } catch {
      toast({ title: 'Assessment failed', description: 'The service is unavailable. Nothing was invented to fill the gap.' });
    } finally {
      setAssessing(false);
    }
  }, [confirmed, extraction, retain, scenario, mode, fields, counterpartOdds, book, toast]);

  const saveToLedger = useCallback(async () => {
    if (!bundle) return;
    setSaving(true);
    try {
      const res = await fetch('/api/ledger/entries', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ assessmentId: bundle.assessmentId, wagerAmount: fields.wagerAmount ?? null }),
      });
      const json = await res.json();
      if (json.ok) {
        setSavedLedgerId(json.ledgerId);
        toast({
          title: 'Ledger entry saved',
          description: 'Append-only record created. Corrections require a revision with a reason and integrity hash.',
        });
        onSaved();
      } else {
        toast({ title: 'Save blocked', description: json.detail ?? 'The entry was not saved.' });
      }
    } catch {
      toast({ title: 'Save failed', description: 'The ledger service is unavailable.' });
    } finally {
      setSaving(false);
    }
  }, [bundle, fields.wagerAmount, onSaved, toast]);

  const setField = <K extends keyof ExtractionFields>(key: K, value: ExtractionFields[K]) => {
    setFields((prev) => ({ ...prev, [key]: value }));
    setBundle(null);
    setSavedLedgerId(null);
  };

  const fieldConf = (key: string): number | undefined => extraction?.fieldConfidence?.[key];
  const lowConf = (key: string): boolean => {
    const c = fieldConf(key);
    return c === undefined || c < CONF_THRESHOLD;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Record a proposed price</h2>
        <p className="mt-1 text-[13px] text-zinc-500 leading-relaxed max-w-2xl">
          Upload a screenshot, paste slip text, or enter fields manually. Extraction always requires your explicit
          confirmation before any assessment runs. This is not a betting recommendation.
        </p>
      </div>

      <Tabs value={inputMode} onValueChange={(v) => setInputMode(v as typeof inputMode)}>
        <TabsList>
          <TabsTrigger value="screenshot">Screenshot</TabsTrigger>
          <TabsTrigger value="paste">Paste slip text</TabsTrigger>
          <TabsTrigger value="manual">Manual entry</TabsTrigger>
        </TabsList>

        <TabsContent value="screenshot" className="mt-3">
          <div className="pst-card rounded-md p-4">
            <Label className="text-[13px]">Slip screenshot</Label>
            <p className="text-[12px] text-zinc-500 mt-1">
              PNG or JPG, up to 8 MB. Screenshots are stored only if you opt in below; deletion is available from the
              entry. Vision extraction reads fields only — it never computes probabilities or assessments.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="block text-[13px] text-zinc-400 file:mr-3 file:rounded-sm file:border file:border-white/[0.12] file:bg-white/[0.08] file:px-3 file:py-1.5 file:text-[13px] file:text-zinc-200 hover:file:bg-white/[0.14]"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadFile(f);
                }}
              />
              {uploading && <span className="text-[12px] text-zinc-400">Extracting fields…</span>}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Checkbox id="retain" checked={retain} onCheckedChange={(v) => setRetain(v === true)} />
              <Label htmlFor="retain" className="text-[12.5px] font-normal text-zinc-400">
                Retain the screenshot with the ledger record (optional; deletable at any time)
              </Label>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="paste" className="mt-3">
          <div className="pst-card rounded-md p-4">
            <Label className="text-[13px]">Slip text</Label>
            <p className="text-[12px] text-zinc-500 mt-1">Paste the slip text exactly as shown by the sportsbook.</p>
            <Textarea
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              rows={4}
              className="mt-2 pst-num text-[13px]"
              aria-label="Slip text to parse"
            />
            <Button variant="outline" size="sm" className="mt-2" onClick={submitPaste} disabled={uploading}>
              {uploading ? 'Parsing…' : 'Parse slip text'}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="manual" className="mt-3">
          <div className="pst-card rounded-md p-4">
            <Note>Manual entry goes straight to the confirmation screen. The record is marked manual_entry in the ledger.</Note>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => {
                setExtraction({
                  slipUploadId: null,
                  provider: 'manual-entry',
                  confidence: 1,
                  fieldConfidence: {},
                  needsManualConfirmation: false,
                });
              }}
            >
              Open manual entry form
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {/* Confirmation screen */}
      {extraction && (
        <section aria-label="Confirm the extracted selections" className="pst-card rounded-md p-4">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <h3 className="text-sm font-semibold text-zinc-100">Confirm the extracted selections</h3>
            {extraction.provider !== 'manual-entry' && (
              <span className={cn('pst-num text-[12px]', extraction.confidence >= CONF_THRESHOLD ? 'text-emerald-300' : 'text-amber-300/80')}>
                extractor {extraction.provider} · confidence {(extraction.confidence * 100).toFixed(0)}% (threshold{' '}
                {(CONF_THRESHOLD * 100).toFixed(0)}%)
                {extraction.needsManualConfirmation ? ' · manual confirmation required' : ''}
              </span>
            )}
          </div>
          <p className="mt-1 text-[12px] text-zinc-500">
            Every field is editable. Nothing is analyzed until you confirm. Low-confidence fields are highlighted for
            manual review.
          </p>

          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
            <FieldInput label="Player" conf={fieldConf('playerName')} low={lowConf('playerName')} value={fields.playerName ?? ''} onChange={(v) => setField('playerName', v)} />
            <FieldSelect
              label="Sport"
              conf={fieldConf('sport')}
              low={lowConf('sport')}
              value={fields.sport ?? 'NFL'}
              onChange={(v) => {
                setField('sport', v);
                setField('league', v);
              }}
              options={['NFL', 'NBA', 'UFC']}
            />
            <FieldSelect
              label="Market"
              conf={fieldConf('market')}
              low={lowConf('market')}
              value={fields.market ?? ''}
              onChange={(v) => {
                setField('market', v);
                setField('marketLabel', marketLabel(v));
              }}
              options={[
                'player_reception_yds',
                'player_passing_yds',
                'player_rushing_yds',
                'player_points',
                'player_rebounds',
                'player_assists',
                'fighter_prize_money',
              ]}
              render={(v) => marketLabel(v)}
            />
            <FieldSelect
              label="Selection"
              conf={fieldConf('selection')}
              low={lowConf('selection')}
              value={fields.selection ?? 'over'}
              onChange={(v) => setField('selection', v as 'over' | 'under')}
              options={['over', 'under']}
              render={(v) => (v === 'over' ? 'Over' : 'Under')}
            />
            <FieldInput label="Line" conf={fieldConf('line')} low={lowConf('line')} value={fields.line ?? ''} type="number" step="0.5" onChange={(v) => setField('line', v === '' ? null : Number(v))} />
            <FieldInput label="Entered price (American)" conf={fieldConf('americanOdds')} low={lowConf('americanOdds')} value={fields.americanOdds ?? ''} type="number" onChange={(v) => setField('americanOdds', v === '' ? null : Number(v))} />
            <FieldInput label="Counterpart price (other side)" value={counterpartOdds} type="number" onChange={setCounterpartOdds} hint="Used for two-way de-vig at entry" />
            <FieldInput label="Book" value={book} onChange={setBook} hint="Record only; never submitted anywhere" />
            <FieldInput label="Event" conf={fieldConf('eventLabel')} low={lowConf('eventLabel')} value={fields.eventLabel ?? ''} onChange={(v) => setField('eventLabel', v)} className="col-span-2" />
            <FieldInput
              label="Wager amount (optional, your record only)"
              value={fields.wagerAmount ?? ''}
              type="number"
              onChange={(v) => setField('wagerAmount', v === '' ? null : Number(v))}
              hint="Never used in assessments or advice"
            />
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="space-y-3">
              <div>
                <SectionLabel>Assessment mode</SectionLabel>
                <Select value={mode} onValueChange={(v) => setMode(v as 'market' | 'model')}>
                  <SelectTrigger className="mt-1 h-9 text-[13px]" aria-label="Assessment mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="market" className="text-[13px]">Market comparison (default)</SelectItem>
                    <SelectItem value="model" className="text-[13px]">Model surface (fails closed without calibrated coverage)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11.5px] text-zinc-400 mt-1">
                  Market mode compares prices. Model mode requires calibrated coverage: without it the categorical is NO
                  MODEL COVERAGE.
                </p>
              </div>
              <div>
                <SectionLabel>Pipeline scenario (reference build)</SectionLabel>
                <Select value={scenario} onValueChange={setScenario}>
                  <SelectTrigger className="mt-1 h-9 text-[13px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCENARIOS.map((s) => (
                      <SelectItem key={s.value} value={s.value} className="text-[13px]">
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11.5px] text-zinc-400 mt-1">
                  Injects fail-closed conditions to demonstrate explicit unavailable states.
                </p>
              </div>
            </div>
            <div className="flex flex-col justify-end">
              <div className="flex items-start gap-2">
                <Checkbox id="confirm-fields" checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} aria-required />
                <Label htmlFor="confirm-fields" className="text-[12.5px] font-normal leading-snug text-zinc-300">
                  I confirm these fields match the slip I am recording.
                </Label>
              </div>
              <Button className="mt-2" disabled={!confirmed || assessing} onClick={runAssessment}>
                {assessing ? 'Computing price assessment…' : 'Confirm and run price assessment'}
              </Button>
            </div>
          </div>
        </section>
      )}

      {/* Assessment result */}
      {bundle && (
        <section aria-label="Price assessment result" className="space-y-4">
          <RatingCard
            slip={{
              playerName: bundle.slip.playerName,
              market: bundle.slip.market,
              selection: bundle.slip.selection,
              line: bundle.slip.line,
              enteredAmericanOdds: bundle.slip.enteredAmericanOdds,
              book: bundle.slip.book,
              capturedAtUtc: bundle.slip.capturedAtUtc,
              eventLabel: bundle.slip.eventLabel,
              sport: bundle.slip.sport,
            }}
            hurdle={bundle.hurdle}
            model={bundle.model}
            provenance={bundle.provenance}
            comparison={bundle.comparison}
            computedAtUtc={bundle.createdAtUtc}
          />

          <div className="pst-card rounded-md p-4">
            <EvidenceDna
              provenance={bundle.provenance}
              model={bundle.model}
              comparison={bundle.comparison}
              slip={bundle.slip}
              record={null}
            />
          </div>

          {!savedLedgerId ? (
            <div className="flex items-center gap-3">
              <Button variant="secondary" onClick={saveToLedger} disabled={saving}>
                {saving ? 'Saving…' : 'Save immutable ledger entry'}
              </Button>
              <Note>Saving creates an append-only record with a snapshot hash; it can be corrected only via revision.</Note>
            </div>
          ) : (
            <div className="pst-card rounded-md p-4 flex items-center justify-between flex-wrap gap-2">
              <div>
                <div className="text-[13px] font-medium text-zinc-200">Recorded for review</div>
                <Note>Ledger entry {savedLedgerId} is append-only. See the Ledger tab for its Evidence DNA and grading.</Note>
              </div>
              <Button variant="outline" size="sm" onClick={() => onSaved()}>
                View in ledger
              </Button>
            </div>
          )}
        </section>
      )}

      {!extraction && !bundle && (
        <div className="pst-card rounded-md p-8 text-center border-dashed">
          <p className="text-[13px] text-zinc-500">
            No assessment yet. Confirm an extraction or enter a slip to run the Hurdle Router.
          </p>
        </div>
      )}
    </div>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  type = 'text',
  step,
  conf,
  low,
  hint,
  className,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  step?: string;
  conf?: number;
  low?: boolean;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-baseline justify-between">
        <Label className="text-[12px] text-zinc-400">{label}</Label>
        {conf !== undefined && (
          <span className={cn('pst-num text-[10.5px]', low ? 'text-amber-300/80' : 'text-emerald-300')}>
            {(conf * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <Input
        type={type}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={cn('mt-1 h-9 pst-num text-[13px]', low && 'border-amber-500/40 bg-amber-50/40')}
      />
      {hint && <p className="text-[11px] text-zinc-400 mt-0.5">{hint}</p>}
    </div>
  );
}

function FieldSelect({
  label,
  value,
  onChange,
  options,
  render,
  conf,
  low,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  render?: (v: string) => string;
  conf?: number;
  low?: boolean;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <Label className="text-[12px] text-zinc-400">{label}</Label>
        {conf !== undefined && (
          <span className={cn('pst-num text-[10.5px]', low ? 'text-amber-300/80' : 'text-emerald-300')}>
            {(conf * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label} className={cn('mt-1 h-9 text-[13px]', low && 'border-amber-500/40 bg-amber-50/40')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o} value={o} className="text-[13px]">
              {render ? render(o) : o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
