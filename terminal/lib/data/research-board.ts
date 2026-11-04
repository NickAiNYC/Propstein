// Read-only research board. Figures come from the ledger and from
// snapshots/snapshots_*.jsonl. A missing source is the string "unavailable".

import fs from "node:fs";
import path from "node:path";

export const UNAVAILABLE = "unavailable";
export const CONFIRMATORY_N = 600;
export const AMENDMENT_ID = "AMEND-001";
export const RESEARCH_LABEL = "Research divergence, not a recommendation.";

export const GATE_COUNT_SQL = `
SELECT count(*)::int AS n
FROM population_committed_forecasts
WHERE amendment_id = 'AMEND-001'
`;

export const EVALUABLE_COUNT_SQL = `
SELECT count(DISTINCT s.id)::int AS n
FROM population_committed_forecasts s
JOIN closing_references c ON c.signal_id = s.id AND c.match_status = 'MATCHED'
WHERE s.amendment_id = 'AMEND-001'
  AND s.decision_at < s.event_start_at
  AND c.reason_code IS NULL
  AND c.settlement_rules IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM withdrawals w WHERE w.signal_id = s.id
  )
  AND NOT EXISTS (
    SELECT 1 FROM settlements st
    WHERE st.signal_id = s.id
      AND st.result IN ('push', 'void', 'dnp', 'cancelled')
  )
`;

export const SIGNAL_SQL = `
SELECT event_id, event_start_at, provider_event_id, amendment_id,
       game_id, player_id, market, model_version, captured_at, payload_canonical
FROM population_committed_forecasts
WHERE amendment_id = 'AMEND-001'
ORDER BY event_start_at, event_id, player_id, market
`;

export type TimestampState = "missing" | "naive" | "future" | "ok";

export type QuoteDisplay = {
  book: string;
  line: string;
  capturedAt: string;
  verification: string;
  staleness: string;
};

export type PlayerCard = {
  eventId: string;
  playerName: string;
  market: string;
  fairLine: string;
  projectedVolume: string;
  modelVersion: string;
  quotes: QuoteDisplay[];
  snapshotClock: string;
};

export type DivergenceItem = {
  playerName: string;
  market: string;
  book: string;
  divergence: string;
};

export type GameChip = {
  eventId: string;
  kickoff: string;
};

export type ResearchBoard = {
  gateLabel: string;
  evaluableCount: number;
  evaluableLabel: string;
  committedCount: number;
  committedLabel: string;
  modelVersion: string;
  weekLabel: string;
  games: GameChip[];
  cards: PlayerCard[];
  divergence: DivergenceItem[];
  researchLabel: string;
};

export type LedgerSignal = {
  eventId: string;
  eventStartAt: string | null;
  providerEventId: string | null;
  amendmentId: string | null;
  gameId: string | null;
  playerId: string | null;
  market: string | null;
  modelVersion: string | null;
  capturedAt: string | null;
  payload: Record<string, unknown>;
};

export type SnapshotRow = {
  snapshot_id?: unknown;
  content_hash?: unknown;
  created_at?: unknown;
  slate?: unknown;
  game_id?: unknown;
  player_id?: unknown;
  player_name?: unknown;
  market?: unknown;
  model?: { version?: unknown } | null;
  projection?: {
    fair_line?: unknown;
    proj_volume?: unknown;
    distribution_params?: Record<string, unknown> | null;
    p_over?: unknown;
    p_under?: unknown;
  } | null;
  quote?: { line?: unknown; observed_at?: unknown; status?: unknown } | null;
};

const RECEPTION_MARKETS = new Set(["receptions", "player_receptions"]);
const YARDS_MARKETS = new Set([
  "receiving_yards",
  "player_reception_yds",
  "player_reception_yards",
]);

export function formatGateCount(count: number | null): string {
  if (count === null || !Number.isInteger(count) || count < 0) return UNAVAILABLE;
  return `${count} / ${CONFIRMATORY_N}`;
}

export function classifyTimestamp(
  value: unknown,
  now: Date,
  options?: { rejectFuture?: boolean },
): { state: TimestampState; iso?: string } {
  if (typeof value !== "string" || value.trim() === "") return { state: "missing" };
  const text = value.trim();
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(text)) return { state: "naive" };
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return { state: "missing" };
  if (options?.rejectFuture !== false && parsed.getTime() > now.getTime()) {
    return { state: "future", iso: parsed.toISOString() };
  }
  return { state: "ok", iso: parsed.toISOString() };
}

function finiteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function textOrUnavailable(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") return UNAVAILABLE;
  return value.trim();
}

function formatNumber(value: unknown): string {
  const number = finiteNumber(value);
  if (number === null) return UNAVAILABLE;
  return String(number);
}

function nb2Sd(mu: number, alpha: number): number | null {
  if (mu < 0 || alpha <= 0) return null;
  const variance = mu + alpha * mu * mu;
  if (!(variance > 0)) return null;
  return Math.sqrt(variance);
}

/** Closed form of the captured distribution. Missing parameters stay null. */
export function modelSd(market: string, params: Record<string, unknown> | null | undefined): number | null {
  if (!params) return null;
  const muRec = finiteNumber(params.mu_rec);
  const alpha = finiteNumber(params.alpha);
  if (muRec === null || alpha === null) return null;
  if (RECEPTION_MARKETS.has(market)) return nb2Sd(muRec, alpha);
  if (!YARDS_MARKETS.has(market)) return null;
  const muYpr = finiteNumber(params.mu_ypr);
  const k = finiteNumber(params.k);
  if (muYpr === null || k === null || muYpr <= 0 || k <= 0) return null;
  const varianceN = muRec + alpha * muRec * muRec;
  const variance = (muRec * muYpr * muYpr) / k + muYpr * muYpr * varianceN;
  if (!(variance > 0)) return null;
  return Math.sqrt(variance);
}

function formatSigma(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded.toFixed(2)}σ`;
}

function clockLabel(state: TimestampState, iso?: string): string {
  if (state === "naive") return "rejected_naive_timestamp";
  if (state === "future") return "rejected_future_timestamp";
  if (state === "ok" && iso) return iso;
  return UNAVAILABLE;
}

function stalenessLabel(state: TimestampState): string {
  if (state === "naive") return "rejected_naive_timestamp";
  if (state === "future") return "rejected_future_timestamp";
  if (state === "ok") return "captured";
  return UNAVAILABLE;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function snapshotKey(id: unknown, hash: unknown): string | null {
  if (typeof id !== "string" || typeof hash !== "string") return null;
  if (!id.trim() || !hash.trim()) return null;
  return `${id.trim()}\n${hash.trim()}`;
}

function emptyQuote(): QuoteDisplay {
  return {
    book: UNAVAILABLE,
    line: UNAVAILABLE,
    capturedAt: UNAVAILABLE,
    verification: UNAVAILABLE,
    staleness: UNAVAILABLE,
  };
}

function quotesFrom(payload: Record<string, unknown>, now: Date): QuoteDisplay[] {
  const observations = payload.observations;
  if (!Array.isArray(observations) || observations.length === 0) return [emptyQuote()];
  return observations.map((item) => {
    const row = asRecord(item);
    if (!row) return emptyQuote();
    const clock = classifyTimestamp(row.observed_at, now, { rejectFuture: true });
    return {
      book: textOrUnavailable(row.book),
      line: formatNumber(row.line),
      capturedAt: clockLabel(clock.state, clock.iso),
      verification: textOrUnavailable(row.receipt_status),
      staleness: stalenessLabel(clock.state),
    };
  });
}

export function assembleResearchBoard(input: {
  signals: LedgerSignal[];
  snapshots: SnapshotRow[];
  gateCount?: number | null;
  evaluableCount?: number | null;
  committedCount?: number | null;
  now: Date;
}): ResearchBoard {
  const index = new Map<string, SnapshotRow>();
  for (const row of input.snapshots) {
    const key = snapshotKey(row.snapshot_id, row.content_hash);
    if (key) index.set(key, row);
  }

  const cards: PlayerCard[] = [];
  const divergence: DivergenceItem[] = [];
  const slates = new Set<string>();
  const games = new Map<string, Set<string>>();

  for (const signal of input.signals) {
    if (signal.amendmentId !== AMENDMENT_ID) continue;
    const slate = signal.payload.slate;
    if (typeof slate === "string" && slate.trim()) slates.add(slate.trim());

    const kickoff = classifyTimestamp(signal.eventStartAt, input.now, { rejectFuture: false });
    const kickoffLabel = clockLabel(kickoff.state, kickoff.iso);
    const eventId = signal.eventId.trim();
    const seen = games.get(eventId) ?? new Set<string>();
    seen.add(kickoffLabel);
    games.set(eventId, seen);

    const join = snapshotKey(signal.payload.model_snapshot_id, signal.payload.model_snapshot_hash);
    const snapshot = join ? index.get(join) : undefined;
    const snapshotClock = snapshot
      ? classifyTimestamp(snapshot.created_at, input.now, { rejectFuture: true })
      : null;
    const snapshotOk = snapshotClock?.state === "ok";
    const projection = snapshotOk ? asRecord(snapshot?.projection) : null;
    const params = projection ? asRecord(projection.distribution_params) : null;
    const market = textOrUnavailable(signal.market);
    const fair = snapshotOk ? formatNumber(projection?.fair_line) : UNAVAILABLE;
    const volume = snapshotOk ? formatNumber(projection?.proj_volume) : UNAVAILABLE;
    const snapshotVersion = snapshotOk ? textOrUnavailable(asRecord(snapshot?.model)?.version) : UNAVAILABLE;
    const modelVersion = snapshotVersion !== UNAVAILABLE ? snapshotVersion : textOrUnavailable(signal.modelVersion);
    const playerFromPayload = textOrUnavailable(signal.payload.player_name);
    const playerName =
      playerFromPayload !== UNAVAILABLE
        ? playerFromPayload
        : snapshotOk
          ? textOrUnavailable(snapshot?.player_name)
          : UNAVAILABLE;
    const quoteRows = quotesFrom(signal.payload, input.now);
    cards.push({
      eventId,
      playerName,
      market,
      fairLine: fair,
      projectedVolume: volume,
      modelVersion,
      quotes: quoteRows,
      snapshotClock: snapshotClock ? clockLabel(snapshotClock.state, snapshotClock.iso) : UNAVAILABLE,
    });

    const sd = snapshotOk && market !== UNAVAILABLE ? modelSd(market, params) : null;
    const fairNumber = snapshotOk ? finiteNumber(projection?.fair_line) : null;
    for (const quote of quoteRows) {
      const lineNumber = quote.line === UNAVAILABLE ? null : Number(quote.line);
      const sigma =
        fairNumber !== null && lineNumber !== null && Number.isFinite(lineNumber) && sd !== null && sd > 0
          ? formatSigma((fairNumber - lineNumber) / sd)
          : UNAVAILABLE;
      divergence.push({
        playerName,
        market,
        book: quote.book,
        divergence: sigma,
      });
    }
  }

  const versions = [...new Set(cards.map((card) => card.modelVersion).filter((item) => item !== UNAVAILABLE))].sort();
  const gameChips: GameChip[] = [...games.entries()]
    .map(([eventId, kickoffs]) => ({
      eventId,
      kickoff: kickoffs.size === 1 ? [...kickoffs][0] : UNAVAILABLE,
    }))
    .sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.eventId.localeCompare(b.eventId));

  const evaluableCount =
    input.evaluableCount !== undefined
      ? input.evaluableCount
      : input.gateCount !== undefined
        ? input.gateCount
        : null;
  const committedCount =
    input.committedCount !== undefined
      ? input.committedCount
      : input.signals.length;

  return {
    gateLabel: formatGateCount(evaluableCount),
    evaluableCount: evaluableCount ?? 0,
    evaluableLabel: formatGateCount(evaluableCount),
    committedCount: committedCount ?? 0,
    committedLabel: committedCount !== null ? `${committedCount} committed forecasts` : UNAVAILABLE,
    modelVersion: versions.length ? versions.join(", ") : UNAVAILABLE,
    weekLabel: slates.size ? [...slates].sort().join(", ") : UNAVAILABLE,
    games: gameChips,
    cards,
    divergence,
    researchLabel: RESEARCH_LABEL,
  };
}

export function renderResearchBoardText(board: ResearchBoard): string {
  const lines = [
    "Model status",
    `Version ${board.modelVersion}`,
    `Evaluable signals ${board.evaluableLabel}`,
    `Committed forecasts ${board.committedCount}`,
    `Confirmatory count ${board.gateLabel}`,
    `Week slate ${board.weekLabel}`,
    ...board.games.map((game) => `${game.eventId} ${game.kickoff}`),
    ...board.cards.flatMap((card) => [
      card.playerName,
      card.market,
      `Fair line (median) ${card.fairLine}`,
      `Projected volume (mean) ${card.projectedVolume}`,
      `Version ${card.modelVersion}`,
      ...card.quotes.flatMap((quote) => [
        `Captured line ${quote.line}`,
        `Capture timestamp ${quote.capturedAt}`,
        `Verification ${quote.verification}`,
        `Staleness ${quote.staleness}`,
      ]),
      `Snapshot timestamp ${card.snapshotClock}`,
    ]),
    board.researchLabel,
    ...board.divergence.map((row) => `${row.playerName} ${row.market} ${row.book} ${row.divergence}`),
  ];
  return lines.join("\n");
}

function resolveSnapshotDir(explicit?: string): string {
  const candidates = [
    explicit,
    process.env.PROPSTEIN_SNAPSHOT_DIR,
    path.join(process.cwd(), "snapshots"),
    path.join(process.cwd(), "..", "snapshots"),
  ].filter((item): item is string => Boolean(item));
  for (const dir of candidates) {
    if (fs.existsSync(dir)) return dir;
  }
  return candidates[candidates.length - 1] ?? path.join(process.cwd(), "snapshots");
}

export function readSnapshotRows(directory?: string): SnapshotRow[] {
  const dir = resolveSnapshotDir(directory);
  if (!fs.existsSync(dir)) return [];
  const rows: SnapshotRow[] = [];
  for (const name of fs.readdirSync(dir).filter((item) => /^snapshots_.*\.jsonl$/.test(item)).sort()) {
    const text = fs.readFileSync(path.join(dir, name), "utf8");
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const parsed = JSON.parse(line) as unknown;
        const row = asRecord(parsed);
        if (row) rows.push(row as SnapshotRow);
      } catch {
        continue;
      }
    }
  }
  return rows;
}

function asIso(value: unknown): string | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value.toISOString();
  if (typeof value === "string" && value.trim()) return value;
  return null;
}

function mapSignal(row: Record<string, unknown>): LedgerSignal | null {
  if (typeof row.event_id !== "string" || !row.event_id.trim()) return null;
  let payload: Record<string, unknown> = {};
  if (typeof row.payload_canonical === "string") {
    try {
      const parsed = JSON.parse(row.payload_canonical) as unknown;
      payload = asRecord(parsed) ?? {};
    } catch {
      payload = {};
    }
  }
  return {
    eventId: row.event_id.trim(),
    eventStartAt: asIso(row.event_start_at),
    providerEventId: typeof row.provider_event_id === "string" ? row.provider_event_id : null,
    amendmentId: typeof row.amendment_id === "string" ? row.amendment_id : null,
    gameId: typeof row.game_id === "string" ? row.game_id : null,
    playerId: typeof row.player_id === "string" ? row.player_id : null,
    market: typeof row.market === "string" ? row.market : null,
    modelVersion: typeof row.model_version === "string" ? row.model_version : null,
    capturedAt: asIso(row.captured_at),
    payload,
  };
}

async function readLedger(databaseUrl: string | undefined): Promise<{
  signals: LedgerSignal[];
  gateCount: number;
  evaluableCount: number;
  committedCount: number;
} | null> {
  if (!databaseUrl) return null;
  const { Client } = await import("pg");
  const client = new Client({ connectionString: databaseUrl });
  try {
    await client.connect();
    const count = await client.query<{ n: number }>(GATE_COUNT_SQL);
    const raw = count.rows[0]?.n;
    const committedCount = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isInteger(committedCount) || committedCount < 0) return null;

    let evaluableCount = 0;
    try {
      const evalRes = await client.query<{ n: number }>(EVALUABLE_COUNT_SQL);
      const evalRaw = evalRes.rows[0]?.n;
      const parsedEval = typeof evalRaw === "number" ? evalRaw : Number(evalRaw);
      if (Number.isInteger(parsedEval) && parsedEval >= 0) {
        evaluableCount = parsedEval;
      }
    } catch {
      evaluableCount = 0;
    }

    const listed = await client.query<Record<string, unknown>>(SIGNAL_SQL);
    const signals = listed.rows.map((row) => mapSignal(row)).filter((row): row is LedgerSignal => row !== null);
    return { signals, gateCount: evaluableCount, evaluableCount, committedCount };
  } catch {
    return null;
  } finally {
    await client.end().catch(() => undefined);
  }
}

export async function loadResearchBoard(input?: {
  now?: Date;
  snapshotDir?: string;
  snapshots?: SnapshotRow[];
  databaseUrl?: string;
  ledger?: {
    signals: LedgerSignal[];
    gateCount?: number | null;
    evaluableCount?: number | null;
    committedCount?: number | null;
  };
}): Promise<ResearchBoard> {
  const now = input?.now ?? new Date();
  const snapshots = input?.snapshots ?? readSnapshotRows(input?.snapshotDir);
  let signals: LedgerSignal[] = [];
  let gateCount: number | null = null;
  let evaluableCount: number | null = null;
  let committedCount: number | null = null;
  if (input?.ledger) {
    signals = input.ledger.signals;
    gateCount = input.ledger.gateCount ?? null;
    evaluableCount = input.ledger.evaluableCount ?? input.ledger.gateCount ?? null;
    committedCount = input.ledger.committedCount ?? null;
  } else {
    const loaded = await readLedger(input?.databaseUrl ?? process.env.DATABASE_URL);
    if (loaded) {
      signals = loaded.signals;
      gateCount = loaded.gateCount;
      evaluableCount = loaded.evaluableCount;
      committedCount = loaded.committedCount;
    }
  }
  return assembleResearchBoard({ signals, snapshots, gateCount, evaluableCount, committedCount, now });
}
