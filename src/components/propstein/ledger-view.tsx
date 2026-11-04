'use client';

/**
 * PropStein — Ledger view (module 3 UI).
 *
 * Append-only record list with filters; entry detail shows the immutable
 * core, Evidence DNA, revision history, closing reference quality, settlement
 * grade with CLV or UNEVALUABLE reason codes, and hash-chain integrity.
 */

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import { AssessmentChip } from './shared';
import { Note, QualityChip, SectionLabel, fmtAmerican, fmtEt, fmtPct, fmtPp, marketLabel, selectionLabel } from './shared';
import { EvidenceDna as EvidenceDnaPanel } from './evidence-dna';
import type { ProvenanceRecord, ComparisonQuote, ModelAssessment } from '@/lib/domain/types';

interface LedgerRow {
  ledgerId: string;
  sport: string;
  playerName: string;
  market: string;
  selection: string;
  line: number;
  enteredAmericanOdds: number;
  priceAssessment: string;
  capturedAtUtc: string;
  createdAtUtc: string;
  settlementStatus: string;
  settlementResult: string | null;
  closingQuality: string;
  duplicate: boolean;
  correlated: boolean;
}

interface EntryDetail {
  entry: Record<string, unknown>;
  provenance: { provenance: ProvenanceRecord; comparison?: ComparisonQuote | null; scenario?: string };
  revisions: { revisionNo: number; reasonCode: string; reasonText: string; changedFields: string[]; priorHash: string; newHash: string; createdAtUtc: string }[];
  closingReference: {
    provider: string | null;
    capturedAtUtc: string | null;
    overAmericanOdds: number | null;
    underAmericanOdds: number | null;
    americanOdds: number | null;
    impliedProbability: number | null;
    fairProbability: number | null;
    quality: string;
    secondSource: { provider: string; impliedProbability: number } | null;
    independenceVerified: boolean;
    integrityHash: string | null;
  } | null;
  settlement: { status: string; result: string | null; reasonCode: string | null; actualValue: number | null; source: string | null; settledAtUtc: string | null };
  grade: { clvPp: number | null; evaluable: boolean; reasonCode: string | null; beatClose: boolean | null } | null;
  integrity: { ok: boolean; problems: string[] };
}

export function LedgerView({ refreshKey }: { refreshKey: number }) {
  const { toast } = useToast();
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [sportFilter, setSportFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [correction, setCorrection] = useState({ reasonCode: '', reasonText: '', field: 'playerName', value: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (sportFilter !== 'all') params.set('sport', sportFilter);
      if (statusFilter !== 'all') params.set('status', statusFilter);
      const res = await fetch(`/api/ledger?${params.toString()}`);
      const json = await res.json();
      if (json.ok) setRows(json.entries);
    } finally {
      setLoading(false);
    }
  }, [sportFilter, statusFilter]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const openDetail = useCallback(async (id: string) => {
    setDetailId(id);
    const res = await fetch(`/api/ledger/${id}`);
    const json = await res.json();
    if (json.ok) setDetail(json);
    else setDetail(null);
  }, []);

  const act = useCallback(
    async (path: string, body?: Record<string, unknown>) => {
      if (!detailId) return;
      setBusy(true);
      try {
        const res = await fetch(`/api/ledger/${detailId}/${path}`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body ?? {}),
        });
        const json = await res.json();
        toast({
          title: json.ok ? (path === 'close' ? 'Closing reference captured' : path === 'settle' ? 'Entry settled and graded' : 'Revision appended') : 'Action blocked',
          description: json.ok ? json.note ?? json.revision?.reasonCode : json.detail ?? json.code,
        });
        await openDetail(detailId);
        load();
      } finally {
        setBusy(false);
      }
    },
    [detailId, openDetail, load, toast],
  );

  const e = detail?.entry as Record<string, any> | undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900">Immutable ledger</h2>
          <p className="mt-0.5 text-[12.5px] text-zinc-500 max-w-2xl">
            Append-only records. Corrections create a new revision with a reason and integrity hash; the original is
            never overwritten. Pushes, voids, cancellations, and DNPs are retained with reason codes and excluded from
            CLV — never counted as losses or zeros.
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={sportFilter} onValueChange={setSportFilter}>
            <SelectTrigger className="h-8 w-28 text-[12.5px]" aria-label="Filter by sport">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {['all', 'NFL', 'NBA', 'UFC'].map((s) => (
                <SelectItem key={s} value={s}>{s === 'all' ? 'All sports' : s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-32 text-[12.5px]" aria-label="Filter by settlement status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {['all', 'pending', 'settled', 'push', 'void', 'canceled', 'dnp'].map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="pst-card rounded-md overflow-hidden">
        <div className="max-h-[28rem] overflow-y-auto">
          <table className="w-full text-[12.5px]">
            <thead className="sticky top-0 bg-zinc-50/95 backdrop-blur-sm border-b border-zinc-200">
              <tr className="text-left pst-label">
                <th className="px-3 py-2 font-medium">Record</th>
                <th className="px-3 py-2 font-medium">Price assessment</th>
                <th className="px-3 py-2 font-medium">Settlement</th>
                <th className="px-3 py-2 font-medium">Close quality</th>
                <th className="px-3 py-2 font-medium">Captured (ET)</th>
                <th className="px-3 py-2 font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-zinc-400">Loading ledger…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-zinc-500">No ledger entries match. Record a proposed price to start your append-only record.</td></tr>
              )}
              {!loading &&
                rows.map((r) => (
                  <tr
                    key={r.ledgerId}
                    className="border-b border-zinc-100 last:border-b-0 hover:bg-zinc-50/70 cursor-pointer"
                    onClick={() => openDetail(r.ledgerId)}
                    tabIndex={0}
                    onKeyDown={(ev) => {
                      if (ev.key === 'Enter') openDetail(r.ledgerId);
                    }}
                    aria-label={`Open ledger entry ${r.ledgerId}`}
                  >
                    <td className="px-3 py-2">
                      <div className="font-medium text-zinc-800">{r.playerName}</div>
                      <div className="text-zinc-500 text-[11.5px]">
                        {r.sport} · {marketLabel(r.market)} {selectionLabel(r.selection)} {r.line} @ {fmtAmerican(r.enteredAmericanOdds)}
                      </div>
                      <div className="pst-num text-zinc-400 text-[10.5px]">{r.ledgerId}</div>
                    </td>
                    <td className="px-3 py-2"><AssessmentChip assessment={r.priceAssessment} size="sm" /></td>
                    <td className="px-3 py-2">
                      <QualityChip quality={r.settlementStatus} />
                      {r.settlementResult && <span className="ml-1.5 text-zinc-500 text-[11.5px]">{r.settlementResult}</span>}
                    </td>
                    <td className="px-3 py-2"><QualityChip quality={r.closingQuality} /></td>
                    <td className="px-3 py-2 pst-num text-zinc-500 text-[11.5px]">{fmtEt(r.capturedAtUtc)}</td>
                    <td className="px-3 py-2 text-[11.5px] text-zinc-500">
                      {r.duplicate && <span className="text-amber-700">duplicate </span>}
                      {r.correlated && <span className="text-amber-700">correlated</span>}
                      {!r.duplicate && !r.correlated && <span className="text-zinc-300">—</span>}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Entry detail dialog */}
      <Dialog open={detailId !== null} onOpenChange={(o) => { if (!o) { setDetailId(null); setDetail(null); } }}>
        <DialogContent aria-describedby={undefined} className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {detail && e ? (
            <>
              <DialogHeader>
                <DialogTitle className="text-[15px] leading-tight">
                  {String(e.playerName)} — {marketLabel(String(e.market))} {selectionLabel(String(e.selection))} {String(e.line)}
                </DialogTitle>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <AssessmentChip assessment={String(e.priceAssessment)} />
                  <QualityChip quality={detail.settlement.status} />
                  {detail.closingReference && <QualityChip quality={detail.closingReference.quality} />}
                  <span
                    className={
                      detail.integrity.ok
                        ? 'text-[11px] text-teal-800 pst-num'
                        : 'text-[11px] text-amber-700 pst-num'
                    }
                  >
                    {detail.integrity.ok
                      ? 'integrity: hash chain verified'
                      : `integrity check failed: ${detail.integrity.problems.join('; ')}`}
                  </span>
                </div>
              </DialogHeader>

              <div className="space-y-5">
                {/* Core record */}
                <section>
                  <SectionLabel>Immutable core</SectionLabel>
                  <div className="grid grid-cols-2 gap-x-6 text-[12.5px] mt-1">
                    <div className="space-y-1 pst-num text-zinc-700">
                      <div>entered {fmtAmerican(Number(e.enteredAmericanOdds))} · break-even {fmtPct(Number(e.breakEvenProbability))}</div>
                      <div>book {String(e.book)} · captured {fmtEt(String(e.capturedAtUtc))}</div>
                      <div>model {String(e.modelVersion ?? 'none')} ({String(e.modelCoverage)})</div>
                    </div>
                    <div className="space-y-1 pst-num text-zinc-700">
                      <div>entry hash <span className="text-zinc-400">{String(e.entryHash).slice(0, 16)}…</span></div>
                      <div>snapshot hash <span className="text-zinc-400">{String(e.snapshotHash).slice(0, 16)}…</span></div>
                      <div>game cluster {String(e.gameClusterId)}</div>
                    </div>
                  </div>
                  {(e.duplicateOfLedgerId || e.correlationGroup) && (
                    <div className="mt-2 space-y-1">
                      {e.duplicateOfLedgerId && <Note tone="warn">Duplicate of {String(e.duplicateOfLedgerId)} — retained, excluded from confirmatory counts.</Note>}
                      {e.correlationGroup && <Note tone="warn">Correlated entry ({String(e.correlationGroup)}) — retained, flagged; cluster dependence is preserved in statistics.</Note>}
                    </div>
                  )}
                </section>

                {/* Closing reference */}
                <section>
                  <SectionLabel>Closing reference</SectionLabel>
                  {detail.closingReference && detail.closingReference.provider ? (
                    <div className="mt-1 text-[12.5px] pst-num text-zinc-700 space-y-1">
                      <div>
                        {fmtAmerican(detail.closingReference.americanOdds)} · fair {fmtPct(detail.closingReference.fairProbability)} ·
                        captured {fmtEt(detail.closingReference.capturedAtUtc)}
                      </div>
                      <div className="text-zinc-500">
                        provider {detail.closingReference.provider} · independence {detail.closingReference.independenceVerified ? 'verified (feed disjoint from model inputs)' : 'NOT VERIFIED'}
                        {detail.closingReference.secondSource && (
                          <> · second source {detail.closingReference.secondSource.provider} at {fmtPct(detail.closingReference.secondSource.impliedProbability)}</>
                        )}
                      </div>
                      <div className="text-zinc-400">integrity hash {detail.closingReference.integrityHash?.slice(0, 16)}…</div>
                    </div>
                  ) : (
                    <Note tone="warn">Closing reference unavailable. The entry cannot be graded until an independent, fresh close exists.</Note>
                  )}
                </section>

                {/* Settlement + grade */}
                <section>
                  <SectionLabel>Settlement and grade</SectionLabel>
                  <div className="mt-1 text-[12.5px] text-zinc-700 space-y-1">
                    <div>
                      status <span className="pst-num">{detail.settlement.status}</span>
                      {detail.settlement.result && <span className="pst-num"> · result {detail.settlement.result}</span>}
                      {detail.settlement.reasonCode && <span className="pst-num"> · reason {detail.settlement.reasonCode}</span>}
                      {detail.settlement.actualValue !== null && detail.settlement.actualValue !== undefined && (
                        <span className="pst-num"> · actual {detail.settlement.actualValue}</span>
                      )}
                    </div>
                    {detail.grade && (
                      <div className="pst-num">
                        {detail.grade.evaluable ? (
                          <>price CLV {fmtPp(detail.grade.clvPp)} · {detail.grade.beatClose ? 'beat close' : 'did not beat close'}</>
                        ) : (
                          <span className="text-amber-700">UNEVALUABLE — reason code {detail.grade.reasonCode}. Never counted as a loss or a zero.</span>
                        )}
                      </div>
                    )}
                  </div>
                </section>

                {/* Revisions */}
                <section>
                  <SectionLabel>Revision history ({detail.revisions.length})</SectionLabel>
                  <div className="mt-1 space-y-1.5 max-h-40 overflow-y-auto">
                    {detail.revisions.map((r) => (
                      <div key={r.revisionNo} className="text-[12px] border-l-2 border-zinc-200 pl-2.5">
                        <div className="pst-num text-zinc-600">
                          #{r.revisionNo} · {r.reasonCode} · {fmtEt(r.createdAtUtc)}
                        </div>
                        <div className="text-zinc-500">{r.reasonText}</div>
                        {r.changedFields.length > 0 && (
                          <div className="text-zinc-400 text-[11px]">changed: {r.changedFields.join(', ')}</div>
                        )}
                        <div className="pst-num text-zinc-300 text-[10px]">
                          {r.priorHash.slice(0, 10)}… → {r.newHash.slice(0, 10)}…
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                {/* Evidence DNA */}
                <section>
                  <EvidenceDnaPanel
                    provenance={detail.provenance.provenance}
                    model={{
                      coverage: String(e.modelCoverage) === 'calibrated' ? 'calibrated' : String(e.modelCoverage) === 'uncalibrated' ? 'uncalibrated' : 'none',
                      modelName: String(e.modelVersion ?? 'none') === 'none' ? null : `${String(e.sport)} model`,
                      modelVersion: e.modelVersion ?? null,
                      probability: e.modelProbability ?? null,
                      uncertainty: e.modelUncertaintyLower !== null && e.modelUncertaintyUpper !== null ? { lower: Number(e.modelUncertaintyLower), upper: Number(e.modelUncertaintyUpper) } : null,
                      calibrationStatus: String(e.modelCoverage) === 'calibrated' ? 'calibrated' : 'none',
                      limitations: [],
                      dataFreshnessUtc: null,
                      corpusGames: null,
                    }}
                    comparison={detail.provenance.comparison ?? null}
                    slip={{ enteredAmericanOdds: Number(e.enteredAmericanOdds), selection: String(e.selection), line: Number(e.line), book: String(e.book), capturedAtUtc: String(e.capturedAtUtc), sport: String(e.sport) }}
                    record={{
                      ledgerId: String(e.ledgerId),
                      createdAtUtc: String(e.createdAtUtc),
                      revisionCount: detail.revisions.length,
                      settlementStatus: detail.settlement.status,
                      clvAvailable: Boolean(detail.grade?.evaluable),
                      closingQuality: detail.closingReference?.quality ?? null,
                    }}
                  />
                </section>

                {/* Actions */}
                <section className="border-t border-zinc-200 pt-3 space-y-3">
                  {!detail.closingReference && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => act('close')}>
                        Capture closing reference
                      </Button>
                      <Select onValueChange={(v) => act('close', { scenario: v })}>
                        <SelectTrigger className="h-8 w-56 text-[12px]" aria-label="Capture close with demo scenario">
                          <SelectValue placeholder="Capture with quality scenario" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="stale_close" className="text-[12px]">Capture as STALE close (unevaluable demo)</SelectItem>
                          <SelectItem value="conflicting_close" className="text-[12px]">Capture as CONFLICTING sources (unevaluable demo)</SelectItem>
                          <SelectItem value="missing_close" className="text-[12px]">Capture as MISSING close (unevaluable demo)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  {detail.settlement.status === 'pending' && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => act('settle')}>
                        Settle and grade
                      </Button>
                      <Select onValueChange={(v) => act('settle', { scenario: v })}>
                        <SelectTrigger className="h-8 w-60 text-[12px]" aria-label="Settle with demo scenario">
                          <SelectValue placeholder="Settle with exclusion scenario" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="push" className="text-[12px]">Settle as PUSH (excluded, reason code)</SelectItem>
                          <SelectItem value="void" className="text-[12px]">Settle as VOID (excluded, reason code)</SelectItem>
                          <SelectItem value="canceled" className="text-[12px]">Settle as CANCELED (excluded, reason code)</SelectItem>
                          <SelectItem value="dnp" className="text-[12px]">Settle as DNP (excluded, reason code)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-[12px] text-zinc-600">Request correction (creates a revision)</Label>
                      <Input
                        placeholder="Reason code (e.g. PLAYER_NAME_TYPO)"
                        value={correction.reasonCode}
                        onChange={(ev) => setCorrection((c) => ({ ...c, reasonCode: ev.target.value }))}
                        className="h-8 text-[12.5px] pst-num"
                      />
                      <Textarea
                        placeholder="Reason for correction (required, retained in the revision)"
                        value={correction.reasonText}
                        onChange={(ev) => setCorrection((c) => ({ ...c, reasonText: ev.target.value }))}
                        rows={2}
                        className="text-[12.5px]"
                      />
                      <div className="flex gap-2">
                        <Input
                          placeholder="playerName"
                          value={correction.field}
                          onChange={(ev) => setCorrection((c) => ({ ...c, field: ev.target.value }))}
                          className="h-8 text-[12.5px] pst-num"
                          aria-label="Field to correct"
                        />
                        <Input
                          placeholder="corrected reading"
                          value={correction.value}
                          onChange={(ev) => setCorrection((c) => ({ ...c, value: ev.target.value }))}
                          className="h-8 text-[12.5px]"
                          aria-label="Corrected field reading"
                        />
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busy || !correction.reasonCode || !correction.reasonText || !correction.value}
                        onClick={() =>
                          act('correction', {
                            reasonCode: correction.reasonCode,
                            reasonText: correction.reasonText,
                            changedFields: { [correction.field]: correction.value },
                          })
                        }
                      >
                        Append revision
                      </Button>
                    </div>
                    <Note>
                      The original record is never modified. Each revision carries a reason, actor, timestamp, prior
                      hash, and new hash; the chain is re-verified on every open.
                    </Note>
                  </div>
                </section>
              </div>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle className="sr-only">Ledger entry detail</DialogTitle>
              </DialogHeader>
              <div className="py-10 text-center text-[13px] text-zinc-400">Loading entry…</div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
