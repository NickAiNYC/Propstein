'use client';

/**
 * PropStein — daily predictions board.
 *
 * Interactive data-dense surface over the stored daily run artifact:
 *   - instant client-side search (Cmd+K command bar)
 *   - sport and assessment-state pills
 *   - threshold sliders (minimum |model − market| gap, minimum model P)
 *   - multi-column sorting
 *   - Bento card grid / compact table views
 *   - inline sparklines, uncertainty band bars, day-over-day delta badges
 *   - drill-down drawer on row/card click
 *
 * Fail closed: without a readable artifact the board renders an explicit
 * unavailable state and never shows assumed numbers. Semantic accents map
 * to delta direction and coverage state only — never to a pick.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { CommandDialog, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '@/components/ui/command';
import { Slider } from '@/components/ui/slider';
import { AssessmentChip, fmtAmerican, fmtEt, fmtPct, fmtPp, SectionLabel } from '@/components/propstein/shared';
import { Sparkline } from '@/components/propstein/sparkline';
import { DeltaBadge, DrillDrawer } from '@/components/propstein/drill-drawer';
import type { TelemetryState } from '@/components/propstein/telemetry-header';
import { LayoutGrid, Rows3, Search, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

// ---------------------------------------------------------------------------
// Artifact types (mirror pipeline/schemas.py, camelCase as serialized)
// ---------------------------------------------------------------------------

export interface BoardPrediction {
  prediction_id: string;
  board_key: string;
  sport: string;
  league: string;
  event_id: string;
  event_label: string;
  game_cluster_id: string;
  commences_at_utc: string;
  player_id: string;
  player_name: string;
  market: string;
  market_label: string;
  selection: string;
  line: number;
  quote: {
    provider: string;
    book: string;
    over_american_odds: number;
    under_american_odds: number;
    captured_at_utc: string;
    licensed: boolean;
  };
  market_implied_probability: number;
  market_fair_probability: number;
  model: {
    model_name: string | null;
    model_version: string | null;
    coverage: string;
    probability: number | null;
    uncertainty: { lower: number; upper: number } | null;
    calibration_status: string;
    limitations: string[];
    corpus_games: number | null;
    data_freshness_utc: string | null;
    features: { name: string; label: string; value: number; weight: number; contribution_pp: number }[];
  };
  model_minus_market_pp: number | null;
  delta_pp_vs_prev: number | null;
  run_date: string;
  is_new_today: boolean;
  series: { run_date: string; p: number | null }[];
  provenance: { key: string; label: string; source_id: string; observed_at_utc: string | null; value: string | null }[];
  provenance_complete: boolean;
  unverified_reason: string | null;
  history: { n_settled: number; n_excluded: number; brier: number | null; hit_rate: number | null };
  freshness: { captured_at_utc: string; age_seconds: number | null; threshold_seconds: number; state: string };
  price_assessment: string;
  reason_code: string;
  assessment_detail: string;
}

interface BoardArtifact {
  run_date: string;
  run_id: string;
  generated_at_utc: string;
  pipeline_version: string;
  source: string;
  odds_provider: string;
  seed: number;
  integrity_hash: string;
  n_records_analyzed: number;
  models: { model_name: string; model_version: string; sport: string; market: string; coverage: string }[];
  metrics: {
    n_predictions: number;
    n_events: number;
    brier: number | null;
    hit_rate: number | null;
    median_band_pp: number | null;
    delta: { n_compared: number; n_new: number; n_dropped: number; mean_abs_delta_pp: number | null };
    coverage_mix: { calibrated: number; uncalibrated: number; none: number };
  };
  predictions: BoardPrediction[];
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

type SportFilter = 'ALL' | 'NFL' | 'NBA' | 'UFC';
type StateFilter = 'ALL' | 'ABOVE' | 'AT' | 'BELOW' | 'STALE' | 'UNVERIFIED' | 'NOCOVERAGE';
type ViewMode = 'bento' | 'table';

const STATE_PILLS: { id: StateFilter; label: string; dot: string }[] = [
  { id: 'ALL', label: 'All states', dot: '#8B90A0' },
  { id: 'ABOVE', label: 'Above hurdle', dot: '#10B981' },
  { id: 'AT', label: 'At hurdle', dot: '#8B90A0' },
  { id: 'BELOW', label: 'Below hurdle', dot: '#EF4444' },
  { id: 'STALE', label: 'Stale quote', dot: '#F59E0B' },
  { id: 'UNVERIFIED', label: 'Unverified', dot: '#F59E0B' },
  { id: 'NOCOVERAGE', label: 'No model', dot: '#F59E0B' },
];

function stateOf(p: BoardPrediction): StateFilter {
  switch (p.price_assessment) {
    case 'PRICE ABOVE MARKET HURDLE':
      return 'ABOVE';
    case 'PRICE AT MARKET HURDLE':
      return 'AT';
    case 'PRICE BELOW MARKET HURDLE':
      return 'BELOW';
    case 'STALE QUOTE':
      return 'STALE';
    case 'UNVERIFIED CONTEXT':
      return 'UNVERIFIED';
    case 'NO MODEL COVERAGE':
    case 'MODEL UNAVAILABLE':
      return 'NOCOVERAGE';
    default:
      return 'ALL';
  }
}

type SortKey = 'player' | 'market' | 'line' | 'modelP' | 'gap' | 'delta' | 'band';

const SORT_COLUMNS: { key: SortKey; label: string; className?: string }[] = [
  { key: 'player', label: 'Player' },
  { key: 'market', label: 'Market', className: 'hidden md:table-cell' },
  { key: 'line', label: 'Line' },
  { key: 'modelP', label: 'Model P' },
  { key: 'gap', label: 'Model − market' },
  { key: 'delta', label: 'Δ vs prev run' },
  { key: 'band', label: '95% band', className: 'hidden lg:table-cell' },
];

// ---------------------------------------------------------------------------
// Board component
// ---------------------------------------------------------------------------

export function PipelineBoard({ telemetry }: { telemetry: TelemetryState }) {
  const [artifact, setArtifact] = useState<BoardArtifact | null>(null);
  const [boardError, setBoardError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [query, setQuery] = useState('');
  const [commandOpen, setCommandOpen] = useState(false);
  const [sport, setSport] = useState<SportFilter>('ALL');
  const [stateFilter, setStateFilter] = useState<StateFilter>('ALL');
  const [minGapPp, setMinGapPp] = useState(0);
  const [minModelP, setMinModelP] = useState(0);
  const [view, setView] = useState<ViewMode>('bento');
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'gap', dir: 'desc' });
  const [selected, setSelected] = useState<BoardPrediction | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // ---- data load (fail closed) --------------------------------------------
  useEffect(() => {
    let cancelled = false;
    fetch('/api/pipeline/predictions')
      .then(async (r) => {
        const json = await r.json();
        if (cancelled) return;
        if (json?.ok && json.predictions) {
          setArtifact(json.predictions as BoardArtifact);
        } else {
          setBoardError(json?.detail ?? 'The board artifact is not available.');
        }
      })
      .catch(() => {
        if (!cancelled) setBoardError('The board endpoint could not be reached.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ---- Cmd+K global shortcut ------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const openDrawer = useCallback((p: BoardPrediction) => {
    setSelected(p);
    setDrawerOpen(true);
  }, []);

  // ---- filtering -------------------------------------------------------------
  const filtered = useMemo(() => {
    if (!artifact) return [];
    const q = query.trim().toLowerCase();
    const rows = artifact.predictions.filter((p) => {
      if (sport !== 'ALL' && p.sport !== sport) return false;
      if (stateFilter !== 'ALL' && stateOf(p) !== stateFilter) return false;
      if (minGapPp > 0) {
        const gap = p.model_minus_market_pp;
        if (gap === null || Math.abs(gap) < minGapPp) return false;
      }
      if (minModelP > 0) {
        const prob = p.model.probability;
        if (prob === null || prob < minModelP) return false;
      }
      if (q) {
        const hay = `${p.player_name} ${p.event_label} ${p.market_label} ${p.league} ${p.model.model_version ?? ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const dir = sort.dir === 'asc' ? 1 : -1;
    const val = (p: BoardPrediction): number | string => {
      switch (sort.key) {
        case 'player':
          return p.player_name;
        case 'market':
          return p.market_label;
        case 'line':
          return p.line;
        case 'modelP':
          return p.model.probability ?? -1;
        case 'gap':
          return Math.abs(p.model_minus_market_pp ?? -1);
        case 'delta':
          return Math.abs(p.delta_pp_vs_prev ?? -1);
        case 'band':
          return p.model.uncertainty ? p.model.uncertainty.upper - p.model.uncertainty.lower : 9;
      }
    };
    return rows.sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (typeof va === 'string' && typeof vb === 'string') return va.localeCompare(vb) * dir;
      return ((va as number) - (vb as number)) * dir;
    });
  }, [artifact, query, sport, stateFilter, minGapPp, minModelP, sort]);

  const sportsPresent = useMemo(() => {
    if (!artifact) return [] as string[];
    return Array.from(new Set(artifact.predictions.map((p) => p.sport))).sort();
  }, [artifact]);

  const counts = useMemo(() => {
    if (!artifact) return { ALL: 0, ABOVE: 0, AT: 0, BELOW: 0, STALE: 0, UNVERIFIED: 0, NOCOVERAGE: 0 } as Record<StateFilter, number>;
    const c = { ALL: 0, ABOVE: 0, AT: 0, BELOW: 0, STALE: 0, UNVERIFIED: 0, NOCOVERAGE: 0 } as Record<StateFilter, number>;
    for (const p of artifact.predictions) c.ALL += 1;
    for (const p of artifact.predictions) c[stateOf(p)] += 1;
    return c;
  }, [artifact]);

  const toggleSort = (key: SortKey) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'player' || key === 'market' ? 'asc' : 'desc' }));
  };

  // ---- render -----------------------------------------------------------------
  return (
    <div className="space-y-4">
      {/* Run identity strip */}
      {artifact && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/[0.07] bg-[#12141C]/70 pst-sheen px-4 py-2.5">
          <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
            <span className="text-[13px] text-zinc-200">
              Daily Board <span className="pst-num text-zinc-400">{artifact.run_date}</span>
            </span>
            <span className="text-[11px] text-zinc-500 pst-num hidden sm:inline">
              {artifact.metrics.n_predictions} rows · {artifact.metrics.n_events} events · {artifact.n_records_analyzed.toLocaleString('en-US')} records analyzed
            </span>
            <span className="text-[11px] text-zinc-500 pst-num hidden md:inline">
              {artifact.models.map((m) => `${m.model_version}:${m.coverage}`).join(' · ')}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {telemetry.status === 'ok' && telemetry.data.lastRun && (
              <span className="text-[10.5px] text-zinc-600 pst-num hidden lg:inline">
                {telemetry.data.lastRun.movement.mean_abs_delta_pp !== null
                  ? `mean |Δ| ${telemetry.data.lastRun.movement.mean_abs_delta_pp.toFixed(2)} pp vs previous run`
                  : 'first run of the window'}
              </span>
            )}
            <span className="text-[10.5px] text-zinc-600 pst-num" title="Artifact integrity hash (SHA-256 over canonical content)">
              {artifact.integrity_hash.slice(0, 12)}…
            </span>
            <div className="flex rounded-md border border-white/[0.07] overflow-hidden" role="group" aria-label="Board view mode">
              <button
                onClick={() => setView('bento')}
                aria-pressed={view === 'bento'}
                className={cn('flex items-center gap-1.5 px-2.5 py-1 text-[11px] transition-colors', view === 'bento' ? 'bg-indigo-500/15 text-indigo-300' : 'text-zinc-500 hover:text-zinc-300')}
              >
                <LayoutGrid className="h-3.5 w-3.5" /> Bento
              </button>
              <button
                onClick={() => setView('table')}
                aria-pressed={view === 'table'}
                className={cn('flex items-center gap-1.5 px-2.5 py-1 text-[11px] transition-colors', view === 'table' ? 'bg-indigo-500/15 text-indigo-300' : 'text-zinc-500 hover:text-zinc-300')}
              >
                <Rows3 className="h-3.5 w-3.5" /> Table
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Control bar */}
      <div className="rounded-lg border border-white/[0.07] bg-[#12141C]/70 pst-sheen p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setCommandOpen(true)}
            className="flex items-center gap-2 rounded-md border border-white/[0.09] bg-[#0D0F16] px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 hover:border-white/20 transition-colors min-w-[220px]"
            aria-label="Open search command bar"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="flex-1 text-left">Search players, markets, events</span>
            <kbd className="pst-num text-[10px] text-zinc-600 border border-white/10 rounded px-1 py-0.5">⌘K</kbd>
          </button>

          {/* Sport pills */}
          <div className="flex flex-wrap gap-1" role="group" aria-label="Sport filter">
            {(['ALL', ...sportsPresent] as SportFilter[]).map((s) => (
              <button
                key={s}
                onClick={() => setSport(s)}
                aria-pressed={sport === s}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                  sport === s
                    ? 'border-indigo-500/50 bg-indigo-500/15 text-indigo-200'
                    : 'border-white/[0.08] text-zinc-500 hover:text-zinc-300 hover:border-white/20',
                )}
              >
                {s === 'ALL' ? 'All sports' : s}
              </button>
            ))}
          </div>

          <span className="flex-1" />

          {/* View-mode independent threshold sliders */}
          <div className="flex items-center gap-3 flex-wrap">
            <label className="flex items-center gap-2 text-[11px] text-zinc-500" title="Only show rows whose |model probability − market fair probability| is at least this large">
              <span className="whitespace-nowrap">min |model − market|</span>
              <Slider
                min={0}
                max={10}
                step={0.5}
                value={[minGapPp]}
                onValueChange={(v) => setMinGapPp(v[0])}
                className="w-24"
                aria-label="Minimum absolute model versus market gap in percentage points"
              />
              <span className="pst-num text-zinc-300 w-10">{minGapPp.toFixed(1)}pp</span>
            </label>
            <label className="flex items-center gap-2 text-[11px] text-zinc-500" title="Only show calibrated rows with model probability at least this high">
              <span className="whitespace-nowrap">min model P</span>
              <Slider
                min={0}
                max={90}
                step={5}
                value={[Math.round(minModelP * 100)]}
                onValueChange={(v) => setMinModelP(v[0] / 100)}
                className="w-24"
                aria-label="Minimum model probability"
              />
              <span className="pst-num text-zinc-300 w-10">{(minModelP * 100).toFixed(0)}%</span>
            </label>
          </div>
        </div>

        {/* Assessment state pills with counts */}
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Assessment state filter">
          {STATE_PILLS.map((pill) => (
            <button
              key={pill.id}
              onClick={() => setStateFilter(pill.id)}
              aria-pressed={stateFilter === pill.id}
              className={cn(
                'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                stateFilter === pill.id
                  ? 'border-white/25 bg-white/[0.07] text-zinc-100'
                  : 'border-white/[0.08] text-zinc-500 hover:text-zinc-300 hover:border-white/20',
              )}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: pill.dot }} aria-hidden="true" />
              {pill.label}
              <span className="pst-num text-zinc-600">{counts[pill.id]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <BoardSkeleton />
      ) : boardError || !artifact ? (
        <div className="rounded-lg border border-dashed border-rose-500/30 bg-rose-500/[0.04] p-8 text-center" role="alert">
          <p className="text-[13px] text-rose-300 font-medium tracking-wide">PIPELINE OUTPUT UNAVAILABLE</p>
          <p className="text-[12px] text-zinc-500 mt-1.5 max-w-md mx-auto leading-relaxed">
            {boardError ?? 'The daily model run artifact is not readable on this deployment.'} The board fails closed — it
            never renders assumed numbers.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-white/[0.07] bg-[#12141C]/50 p-8 text-center">
          <p className="text-[13px] text-zinc-400">No rows match the current filters.</p>
          <p className="text-[11.5px] text-zinc-600 mt-1">Adjust the pills, thresholds, or search above.</p>
        </div>
      ) : view === 'bento' ? (
        <BentoGrid rows={filtered} runDate={artifact.run_date} onSelect={openDrawer} />
      ) : (
        <BoardTable rows={filtered} sort={sort} onToggleSort={toggleSort} onSelect={openDrawer} />
      )}

      {/* Command bar */}
      <CommandDialog open={commandOpen} onOpenChange={setCommandOpen} title="Board search" description="Search players, markets, and events; jump to filter states.">
        <CommandInput placeholder="Search players, markets, events…" value={query} onValueChange={setQuery} />
        <CommandList className="pst-scroll">
          <CommandEmpty>No matching board rows.</CommandEmpty>
          {artifact && (
            <CommandGroup heading="Board rows">
              {filtered.slice(0, 8).map((p) => (
                <CommandItem
                  key={p.prediction_id}
                  value={`${p.player_name} ${p.event_label} ${p.market_label}`}
                  onSelect={() => {
                    setCommandOpen(false);
                    openDrawer(p);
                  }}
                >
                  <span className="text-zinc-200 text-[13px]">{p.player_name}</span>
                  <span className="text-zinc-500 text-[11.5px] truncate">
                    {p.market_label} O{p.line.toFixed(1)} · {p.event_label}
                  </span>
                  <span className="ml-auto pst-num text-[11px] text-zinc-500">
                    {p.model.probability !== null ? fmtPct(p.model.probability) : p.price_assessment}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          <CommandGroup heading="Filter states">
            {STATE_PILLS.map((pill) => (
              <CommandItem
                key={pill.id}
                value={`filter ${pill.label}`}
                onSelect={() => {
                  setStateFilter(pill.id);
                  setCommandOpen(false);
                }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: pill.dot }} aria-hidden="true" />
                <span className="text-[13px] text-zinc-200">Filter: {pill.label}</span>
                <span className="ml-auto pst-num text-[11px] text-zinc-500">{counts[pill.id]}</span>
              </CommandItem>
            ))}
          </CommandGroup>
          <CommandGroup heading="Views">
            <CommandItem value="view bento" onSelect={() => { setView('bento'); setCommandOpen(false); }}>
              <LayoutGrid className="h-3.5 w-3.5 text-zinc-500" />
              <span className="text-[13px] text-zinc-200">Bento grid view</span>
            </CommandItem>
            <CommandItem value="view table" onSelect={() => { setView('table'); setCommandOpen(false); }}>
              <Rows3 className="h-3.5 w-3.5 text-zinc-500" />
              <span className="text-[13px] text-zinc-200">Table view</span>
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      <DrillDrawer prediction={selected} open={drawerOpen} onOpenChange={setDrawerOpen} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bento grid
// ---------------------------------------------------------------------------

function BentoGrid({ rows, runDate, onSelect }: { rows: BoardPrediction[]; runDate: string; onSelect: (p: BoardPrediction) => void }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-px rounded-lg overflow-hidden border border-white/[0.07] bg-white/[0.05]" role="list">
      {rows.map((p) => {
        const gap = p.model_minus_market_pp;
        const hasNumbers = p.model.probability !== null;
        const tone =
          p.price_assessment === 'PRICE ABOVE MARKET HURDLE'
            ? 'emerald'
            : p.price_assessment === 'PRICE BELOW MARKET HURDLE'
              ? 'rose'
              : 'neutral';
        return (
          <button
            key={p.prediction_id}
            onClick={() => onSelect(p)}
            className="pst-rowfocus group text-left bg-[#0D0F16] hover:bg-[#12141C] transition-colors p-3.5 flex flex-col gap-2.5 relative overflow-hidden"
            role="listitem"
            aria-label={`${p.player_name}, ${p.market_label} Over ${p.line}, ${p.price_assessment}`}
          >
            {/* tone rail */}
            <span
              aria-hidden="true"
              className={cn(
                'absolute left-0 top-0 bottom-0 w-[2px]',
                tone === 'emerald' ? 'bg-emerald-500/70' : tone === 'rose' ? 'bg-rose-500/70' : 'bg-white/10',
              )}
            />
            <div className="flex items-start justify-between gap-2 pl-1.5">
              <div className="min-w-0">
                <div className="text-[13.5px] font-medium text-zinc-100 truncate">{p.player_name}</div>
                <div className="text-[11px] text-zinc-500 truncate">
                  {p.market_label} <span className="text-zinc-400">Over</span>{' '}
                  <span className="pst-num text-zinc-300">{p.line.toFixed(1)}</span>
                </div>
              </div>
              <span className="text-[10px] pst-num text-zinc-600 border border-white/[0.07] rounded px-1 py-0.5 shrink-0">{p.sport}</span>
            </div>

            {hasNumbers ? (
              <>
                <div className="flex items-end justify-between gap-2 pl-1.5">
                  <div>
                    <div className="pst-num text-[22px] leading-none text-zinc-100">{(p.model.probability! * 100).toFixed(1)}%</div>
                    <div className="text-[10px] text-zinc-600 mt-1 pst-num">
                      band {(p.model.uncertainty!.lower * 100).toFixed(1)}–{(p.model.uncertainty!.upper * 100).toFixed(1)}%
                      {p.model.model_version && <span className="ml-1.5">{p.model.model_version}</span>}
                    </div>
                  </div>
                  <Sparkline
                    points={[...p.series, { run_date: runDate, p: p.model.probability }]}
                    width={84}
                    height={30}
                    className="text-zinc-500"
                  />
                </div>
                {/* band bar + gap + delta */}
                <div className="pl-1.5 space-y-1.5">
                  <div className="relative h-1 rounded-full bg-white/[0.06]" aria-hidden="true">
                    <div
                      className="absolute top-0 bottom-0 rounded-full bg-indigo-500/60"
                      style={{ left: `${p.model.uncertainty!.lower * 100}%`, width: `${(p.model.uncertainty!.upper - p.model.uncertainty!.lower) * 100}%` }}
                    />
                    <div className="absolute top-[-2px] bottom-[-2px] w-[2px] bg-zinc-200/80" style={{ left: `${p.model.probability! * 100}%` }} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span
                      className={cn(
                        'pst-num text-[11px]',
                        gap !== null && gap > 0 ? 'text-emerald-300' : gap !== null && gap < 0 ? 'text-rose-300' : 'text-zinc-400',
                      )}
                      title="Model probability minus market fair probability (descriptive diagnostic)"
                    >
                      {fmtPp(gap, 1)}
                    </span>
                    {p.delta_pp_vs_prev !== null ? (
                      <DeltaBadge deltaPp={p.delta_pp_vs_prev} compact />
                    ) : p.is_new_today ? (
                      <span className="text-[10px] pst-num text-indigo-300/80 border border-indigo-500/30 rounded px-1 py-0.5">NEW</span>
                    ) : null}
                  </div>
                </div>
              </>
            ) : (
              <div className="pl-1.5 py-2 text-[11.5px] text-amber-300/80 leading-relaxed">
                {p.price_assessment === 'NO MODEL COVERAGE' || p.price_assessment === 'MODEL UNAVAILABLE'
                  ? 'No calibrated model numbers for this market.'
                  : p.price_assessment === 'STALE QUOTE'
                    ? 'Quote snapshot is beyond the freshness threshold.'
                    : 'Context inputs are not verified before the pricing cutoff.'}
              </div>
            )}

            <div className="pl-1.5 flex items-center justify-between gap-2 mt-auto pt-2 border-t border-white/[0.06]">
              <span className="text-[10.5px] text-zinc-600 truncate">{p.event_label}</span>
              <span className="pst-num text-[10.5px] text-zinc-600 shrink-0">{fmtAmerican(p.quote.over_american_odds)}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table view
// ---------------------------------------------------------------------------

function BoardTable({
  rows,
  sort,
  onToggleSort,
  onSelect,
}: {
  rows: BoardPrediction[];
  sort: { key: SortKey; dir: 'asc' | 'desc' };
  onToggleSort: (key: SortKey) => void;
  onSelect: (p: BoardPrediction) => void;
}) {
  return (
    <div className="rounded-lg border border-white/[0.07] overflow-hidden">
      <div className="overflow-x-auto pst-scroll">
        <table className="w-full text-[12.5px] border-collapse">
          <thead>
            <tr className="bg-[#12141C] text-left">
              {SORT_COLUMNS.map((col) => (
                <th key={col.key} scope="col" className={cn('py-2 px-3 font-medium', col.className)}>
                  <button
                    onClick={() => onToggleSort(col.key)}
                    className="flex items-center gap-1 text-zinc-400 hover:text-zinc-200 transition-colors"
                    aria-label={`Sort by ${col.label}`}
                  >
                    {col.label}
                    {sort.key === col.key ? (
                      sort.dir === 'asc' ? (
                        <ArrowUp className="h-3 w-3 text-indigo-400" />
                      ) : (
                        <ArrowDown className="h-3 w-3 text-indigo-400" />
                      )
                    ) : (
                      <ArrowUpDown className="h-3 w-3 opacity-30" />
                    )}
                  </button>
                </th>
              ))}
              <th scope="col" className="py-2 px-3 font-medium text-zinc-400 hidden xl:table-cell">Assessment</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const gap = p.model_minus_market_pp;
              return (
                <tr
                  key={p.prediction_id}
                  onClick={() => onSelect(p)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') onSelect(p);
                  }}
                  className="pst-rowfocus cursor-pointer border-t border-white/[0.05] bg-[#0D0F16] hover:bg-[#151823] transition-colors"
                >
                  <td className="py-2 px-3">
                    <div className="text-zinc-100">{p.player_name}</div>
                    <div className="text-[10.5px] text-zinc-600 truncate max-w-[24ch]">{p.event_label}</div>
                  </td>
                  <td className="py-2 px-3 text-zinc-400 hidden md:table-cell">
                    {p.market_label}
                    <span className="pst-num text-zinc-600 ml-1.5 text-[10.5px]">{p.sport}</span>
                  </td>
                  <td className="py-2 px-3 pst-num text-zinc-200 whitespace-nowrap">{p.line.toFixed(1)}</td>
                  <td className="py-2 px-3 whitespace-nowrap">
                    {p.model.probability !== null ? (
                      <div className="flex items-center gap-2">
                        <span className="pst-num text-zinc-100">{fmtPct(p.model.probability)}</span>
                        <div className="relative h-1 w-14 rounded-full bg-white/[0.06]" aria-hidden="true">
                          <div
                            className="absolute top-0 bottom-0 rounded-full bg-indigo-500/60"
                            style={{
                              left: `${p.model.uncertainty!.lower * 100}%`,
                              width: `${(p.model.uncertainty!.upper - p.model.uncertainty!.lower) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    ) : (
                      <span className="text-[11px] text-amber-300/70 pst-num">{p.model.model_version ?? '—'} withheld</span>
                    )}
                  </td>
                  <td
                    className={cn(
                      'py-2 px-3 pst-num whitespace-nowrap',
                      gap !== null && gap > 0 ? 'text-emerald-300' : gap !== null && gap < 0 ? 'text-rose-300' : 'text-zinc-500',
                    )}
                  >
                    {fmtPp(gap, 1)}
                  </td>
                  <td className="py-2 px-3 whitespace-nowrap">
                    {p.delta_pp_vs_prev !== null ? (
                      <DeltaBadge deltaPp={p.delta_pp_vs_prev} compact />
                    ) : p.is_new_today ? (
                      <span className="text-[10px] pst-num text-indigo-300/80 border border-indigo-500/30 rounded px-1 py-0.5">NEW</span>
                    ) : (
                      <span className="text-zinc-600 text-[11px]">—</span>
                    )}
                  </td>
                  <td className="py-2 px-3 hidden lg:table-cell">
                    <Sparkline points={[...p.series, { run_date: '', p: p.model.probability }]} width={72} height={22} />
                  </td>
                  <td className="py-2 px-3 hidden xl:table-cell">
                    <AssessmentChip assessment={p.price_assessment} size="sm" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function BoardSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-px rounded-lg overflow-hidden border border-white/[0.07] bg-white/[0.05]" aria-busy="true" aria-label="Loading board">
      {Array.from({ length: 12 }).map((_, i) => (
        <div key={i} className="bg-[#0D0F16] p-3.5 space-y-3 animate-pulse">
          <div className="h-3 w-2/3 rounded bg-white/[0.06]" />
          <div className="h-2 w-1/2 rounded bg-white/[0.04]" />
          <div className="h-6 w-1/3 rounded bg-white/[0.06]" />
          <div className="h-1 w-full rounded bg-white/[0.04]" />
          <div className="h-2 w-1/4 rounded bg-white/[0.04]" />
        </div>
      ))}
    </div>
  );
}
