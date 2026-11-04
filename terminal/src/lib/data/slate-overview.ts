// lib/data/slate-overview.ts — deterministic data layer for the Slate Overview.
//
// CONTRACT:
//   - The Python model layer (src/) is the sole truth source. This layer READS
//     the versioned artifacts under viewer/ and maps them; it never recomputes
//     pricing, Kelly, or verification decisions.
//   - FAIL CLOSED: unreadable artifacts yield STALE sources and an empty
//     board — never invented numbers.
//   - Mocks (`?__mock=`) are gated to the test environment
//     (NODE_ENV=test or PLAYWRIGHT=1) and are inert everywhere else —
//     local dev and production always render real artifacts.
//   - Thresholds are config-driven, read from the repo's own committed
//     artifacts, never hardcoded opinions:
//       viewer/top_picks.json              -> gate_edge (edge gate), season/week
//       viewer/circuit_breaker_config.json -> odds_stale_max_age_seconds
//       news-watcher staleness copy        -> 5-minute context warning

import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import type {
  FeedSourceHealth,
  GateClause,
  QualifiedPlaySummary,
  SlateOverview,
  VerificationStatus,
} from "@/lib/types/slate";

// ---------------------------------------------------------------------------
// Artifact locations (terminal/ lives inside the repo; viewer/ is one level up)

function resolveViewerDir(): string {
  const candidates = [
    process.env.PROPSTEIN_VIEWER_DIR,
    path.join(process.cwd(), "viewer"),
    path.join(process.cwd(), "..", "viewer"),
  ].filter((p): p is string => Boolean(p));
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, "live_odds_feed.json"))) return dir;
  }
  return path.join(process.cwd(), "..", "viewer");
}
const VIEWER = resolveViewerDir();

function readJson<T>(file: string): T | null {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")) as T;
  } catch {
    return null;
  }
}

const ageSeconds = (iso: string | undefined): number =>
  iso
    ? (() => {
        const time = new Date(iso).getTime();
        return Number.isFinite(time) && time <= Date.now()
          ? Math.floor((Date.now() - time) / 1000)
          : Number.MAX_SAFE_INTEGER;
      })()
    : Number.MAX_SAFE_INTEGER;

const round1 = (n: number) => Math.round(n * 10) / 10;
const round3 = (n: number) => Math.round(n * 1000) / 1000;
const validFraction = (n: number | undefined): n is number =>
  typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1;

// ---------------------------------------------------------------------------
// Deterministic thresholds — read from the repo's own committed config.

interface SportBlock {
  thresholds?: { odds_stale_max_age_seconds?: number };
}
interface BreakerConfig {
  sports?: Record<string, SportBlock>;
}

const breaker = readJson<BreakerConfig>(path.join(VIEWER, "circuit_breaker_config.json"));
const NFL: SportBlock = breaker?.sports?.nfl ?? {};
/** Odds staleness threshold — committed breaker config (NFL: 21600s = 6h). */
const STALE_SECONDS = NFL.thresholds?.odds_stale_max_age_seconds ?? 21600;
/** News-watcher freshness — pinned by the breaker messaging copy ("stale >5m"). */
const NEWS_FRESH_SECONDS = 300;

interface PicksMeta {
  season?: number;
  week?: number;
  gate_edge?: number;
}
const picksMeta = readJson<PicksMeta>(path.join(VIEWER, "top_picks.json"));
/** Edge gate in percentage points (artifact carries it in probability units). */
const EDGE_GATE_PCT = (picksMeta?.gate_edge ?? 0.1) * 100;
const SLATE_ID = `NFL ${picksMeta?.season ?? ""} W${picksMeta?.week ?? ""}`.trim().replace(/\s+/g, " ");

// ---------------------------------------------------------------------------
// Feed artifact shapes (viewer/live_odds_feed.json)

interface FeedQuote {
  quote_id: string;
  book: string;
  player_id?: string;
  player_name: string;
  market: string;
  line: number;
  fair_line: number;
  over_odds: number;
  under_odds: number;
  observed_at: string;
  content_hash?: string;
  verified?: boolean;
  source?: string;
  evaluation?: {
    best_side?: string;
    prob_edge?: number;
    expected_return?: number;
    actionable_stake?: number;
    fair_prob?: number;
    kelly_fraction?: number;
    status?: string;
  };
}
interface OddsFeed {
  feed_status?: string;
  updated_at?: string;
  quotes?: FeedQuote[];
}
interface NewsWatcherState {
  last_polled_at?: string;
  is_alive?: boolean;
}

interface FeedManifest { sha256?: string; source_feed?: string }

function verifiedFeedBytes(): { feed: OddsFeed; manifest: FeedManifest } | null {
  try {
    const raw = fs.readFileSync(path.join(VIEWER, "live_odds_feed.json"));
    const manifest = readJson<FeedManifest>(path.join(VIEWER, "live_odds_feed.manifest.json"));
    if (!manifest?.sha256 || createHash("sha256").update(raw).digest("hex") !== manifest.sha256) return null;
    return { feed: JSON.parse(raw.toString("utf8")) as OddsFeed, manifest };
  } catch {
    return null;
  }
}

function isSynthetic(q: FeedQuote): boolean {
  return q.player_id?.startsWith("SYN-") === true ||
    /synthetic|fixture|demobook/i.test(`${q.book} ${q.source ?? ""}`);
}

// ---------------------------------------------------------------------------
// Real path — map the live artifacts. FAIL CLOSED when they are unreadable.

function realSlateOverview(): SlateOverview {
  const audited = verifiedFeedBytes();
  const feed = audited?.feed;
  const news = readJson<NewsWatcherState>(path.join(VIEWER, "news_watcher_state.json"));

  const quotes = (feed?.quotes ?? []).filter((q) => !isSynthetic(q));
  const newsAge = ageSeconds(news?.last_polled_at);

  const plays: QualifiedPlaySummary[] = quotes
    .map((q): QualifiedPlaySummary => {
      const edgePct = Number.isFinite(q.evaluation?.prob_edge)
        ? round1(q.evaluation!.prob_edge! * 100)
        : null;
      const quoteAge = ageSeconds(q.observed_at);
      // The feed's legacy `verified` boolean is insufficient: it does not
      // carry an independent matched receipt or the Python verification.v1
      // clause trail. Never promote it into a customer-facing VERIFIED claim.
      const status: VerificationStatus = quoteAge > STALE_SECONDS
        ? "STALE"
        : q.evaluation?.status === "CONFLICT"
          ? "CONFLICT"
          : "OBSERVED";
      return {
        play_id: q.quote_id,
        player_name: q.player_name,
        side: q.evaluation?.best_side?.toLowerCase() === "under" ? "under" : "over",
        line: q.line,
        market: q.market,
        book_id: q.book,
        source_id: q.source ?? q.book,
        edge_pct: edgePct,
        fair_prob: validFraction(q.evaluation?.fair_prob) ? q.evaluation!.fair_prob! : null,
        fair_line: q.fair_line,
        ev_per_unit: Number.isFinite(q.evaluation?.expected_return)
          ? round3(q.evaluation!.expected_return!)
          : null,
        kelly_fraction: validFraction(q.evaluation?.kelly_fraction) ? q.evaluation!.kelly_fraction! : null,
        verification_status: status,
        // No Python gate artifact is attached to this feed. A fabricated
        // threshold trail would misrepresent the decision as audited.
        gate_reasoning: [],
        quote_age_seconds: quoteAge === Number.MAX_SAFE_INTEGER ? null : quoteAge,
        fetched_at: q.observed_at,
      };
    })
    .sort((a, b) => {
      if (a.edge_pct === null) return b.edge_pct === null ? 0 : 1;
      if (b.edge_pct === null) return -1;
      return b.edge_pct - a.edge_pct;
    });

  const feedAge = ageSeconds(feed?.updated_at);
  const primaryStatus: VerificationStatus =
    !audited || quotes.length === 0 || feedAge > STALE_SECONDS
      ? "STALE"
      : "OBSERVED";

  const sources: FeedSourceHealth[] = [
    {
      source_id: audited?.manifest.source_feed ?? "odds-feed",
      book_id: null,
      status: primaryStatus,
      quote_count: quotes.length,
      last_success_at: feed?.updated_at ?? "1970-01-01T00:00:00.000Z",
      verification_configured: Boolean(audited) && quotes.every((q) => Boolean(q.content_hash)),
      tier: "primary",
    },
    {
      source_id: "sleeper-news-watcher",
      book_id: null,
      status: newsAge > NEWS_FRESH_SECONDS ? "STALE" : "OBSERVED",
      quote_count: 0,
      last_success_at: news?.last_polled_at ?? "1970-01-01T00:00:00.000Z",
      verification_configured: false,
      tier: "secondary",
    },
  ];

  const cutoffs = [feed?.updated_at, ...quotes.map((q) => q.observed_at)]
    .filter((x): x is string => Boolean(x))
    .sort();

  return {
    slate_id: SLATE_ID,
    generated_at: new Date().toISOString(),
    data_cutoff_timestamp: cutoffs[cutoffs.length - 1] ?? "",
    plays,
    sources,
    conflict: plays.some((p) => p.verification_status === "CONFLICT"),
  };
}

// ---------------------------------------------------------------------------
// Mock fixtures — TEST ENV ONLY (NODE_ENV=test or PLAYWRIGHT=1). Frozen,
// self-describing, and consistent with the real config thresholds.

const T0 = "2026-11-02T17:45:00Z";

function mockPlay(p: Partial<QualifiedPlaySummary>): QualifiedPlaySummary {
  return {
    play_id: "",
    player_name: "",
    side: "over",
    line: 0,
    market: "receiving_yards",
    book_id: "",
    source_id: "polymarket-clob",
    edge_pct: 0,
    fair_prob: 0.5,
    fair_line: 0,
    ev_per_unit: 0,
    kelly_fraction: 0,
    verification_status: "OBSERVED",
    gate_reasoning: [],
    quote_age_seconds: 45,
    fetched_at: T0,
    ...p,
  };
}

function mockSource(p: Partial<FeedSourceHealth>): FeedSourceHealth {
  return {
    source_id: "",
    book_id: null,
    status: "OBSERVED",
    quote_count: 0,
    last_success_at: T0,
    verification_configured: true,
    tier: "primary",
    ...p,
  };
}

function mockOverview(
  plays: QualifiedPlaySummary[],
  sources: FeedSourceHealth[],
  conflict = false
): SlateOverview {
  return {
    slate_id: "MOCK",
    generated_at: T0,
    data_cutoff_timestamp: T0,
    plays,
    sources,
    conflict,
  };
}

/** Clauses consistent with the committed config: Edge gate 10.0pp, EV>0, Kelly>0, News<=300s. */
function mkClauses(opts: {
  edge: number;
  ev: number;
  kelly: number;
  newsAge: number;
}): GateClause[] {
  return [
    { clause_id: "edge", label: "Edge", operator: ">=", actual: round1(opts.edge), threshold: round1(EDGE_GATE_PCT), passed: opts.edge >= EDGE_GATE_PCT, severity: "hard" },
    { clause_id: "ev", label: "EV/unit", operator: ">", actual: round3(opts.ev), threshold: 0, passed: opts.ev > 0, severity: "hard" },
    { clause_id: "kelly", label: "Kelly", operator: ">", actual: round3(opts.kelly), threshold: 0, passed: opts.kelly > 0, severity: "hard" },
    { clause_id: "news", label: "News freshness", operator: "<=", actual: opts.newsAge, threshold: NEWS_FRESH_SECONDS, passed: opts.newsAge <= NEWS_FRESH_SECONDS, severity: "soft" },
  ];
}

const PASSING = mkClauses({ edge: 12.0, ev: 0.21, kelly: 0.05, newsAge: 120 });

const MOCKS: Record<string, SlateOverview> = {
  // Sharp books disagree beyond the drift hurdle: banner + BLOCKED_DATA card.
  conflict: mockOverview(
    [
      mockPlay({
        play_id: "mock-conflict-1",
        player_name: "Mock Player A",
        line: 34.5,
        fair_line: 43.5,
        book_id: "Synthetic Book A",
        edge_pct: 12.0,
        fair_prob: 0.612,
        ev_per_unit: 0.155,
        kelly_fraction: 0.03,
        verification_status: "CONFLICT",
        gate_reasoning: PASSING,
      }),
    ],
    [
      mockSource({ source_id: "polymarket-clob", status: "CONFLICT", quote_count: 24 }),
      mockSource({ source_id: "sleeper-news-watcher", tier: "secondary", verification_configured: false }),
    ],
    true
  ),

  // One verified book, one observed: distinct badges, distinct aria-labels.
  mixed_verification: mockOverview(
    [
      mockPlay({
        play_id: "mock-mixed-verified",
        player_name: "Mock Player V",
        book_id: "FanDuel",
        edge_pct: 11.2,
        fair_prob: 0.59,
        fair_line: 43.5,
        ev_per_unit: 0.19,
        kelly_fraction: 0.041,
        verification_status: "VERIFIED",
        gate_reasoning: PASSING,
      }),
      mockPlay({
        play_id: "mock-mixed-observed",
        player_name: "Mock Player O",
        book_id: "DraftKings",
        edge_pct: 12.0,
        fair_prob: 0.60,
        fair_line: 44.0,
        ev_per_unit: 0.21,
        kelly_fraction: 0.05,
        verification_status: "OBSERVED",
        gate_reasoning: PASSING,
      }),
    ],
    [
      mockSource({ source_id: "fanduel", book_id: "FanDuel", status: "VERIFIED", quote_count: 88 }),
      mockSource({ source_id: "draftkings", book_id: "DraftKings", status: "OBSERVED", quote_count: 64 }),
      mockSource({ source_id: "sleeper-news-watcher", tier: "secondary", verification_configured: false }),
    ]
  ),

  // +12% edge but unverified: BLOCKED, never QUALIFIED. Fail closed.
  edge_positive_observed: mockOverview(
    [
      mockPlay({
        play_id: "mock-obs-edge",
        player_name: "Mock Player E",
        book_id: "DraftKings",
        edge_pct: 12.0,
        fair_prob: 0.60,
        fair_line: 44.0,
        ev_per_unit: 0.21,
        kelly_fraction: 0.05,
        verification_status: "OBSERVED",
        gate_reasoning: PASSING,
      }),
    ],
    [
      mockSource({ source_id: "polymarket-clob", status: "OBSERVED", quote_count: 24 }),
      mockSource({ source_id: "sleeper-news-watcher", tier: "secondary", verification_configured: false }),
    ]
  ),

  // The model said no: hard edge clause fails, clause named in the subtitle.
  hard_gate_fail: mockOverview(
    [
      mockPlay({
        play_id: "mock-hard-gate",
        player_name: "Mock Player H",
        book_id: "FanDuel",
        edge_pct: 0.9,
        fair_prob: 0.512,
        fair_line: 41.0,
        ev_per_unit: 0.012,
        kelly_fraction: 0.004,
        verification_status: "VERIFIED",
        gate_reasoning: mkClauses({ edge: 0.9, ev: 0.012, kelly: 0.004, newsAge: 90 }),
      }),
    ],
    [
      mockSource({ source_id: "fanduel", book_id: "FanDuel", status: "VERIFIED", quote_count: 88 }),
      mockSource({ source_id: "sleeper-news-watcher", tier: "secondary", verification_configured: false }),
    ]
  ),

  // Soft clause fails only: WATCH, edge still visible, nothing blocked.
  soft_gate_fail: mockOverview(
    [
      mockPlay({
        play_id: "mock-soft-gate",
        player_name: "Mock Player S",
        book_id: "FanDuel",
        edge_pct: 12.0,
        fair_prob: 0.60,
        fair_line: 44.0,
        ev_per_unit: 0.21,
        kelly_fraction: 0.05,
        verification_status: "VERIFIED",
        gate_reasoning: mkClauses({ edge: 12.0, ev: 0.21, kelly: 0.05, newsAge: 3612 }),
      }),
    ],
    [
      mockSource({ source_id: "fanduel", book_id: "FanDuel", status: "VERIFIED", quote_count: 88 }),
      mockSource({ source_id: "sleeper-news-watcher", tier: "secondary", verification_configured: false }),
    ]
  ),
};

// ---------------------------------------------------------------------------

export async function getSlateOverview(mockKey?: string): Promise<SlateOverview> {
  const mockEnabled = process.env.NODE_ENV === "test" || process.env.PLAYWRIGHT === "1";
  if (mockKey && mockEnabled) {
    const mock = MOCKS[mockKey];
    if (mock) return mock;
  }
  // Unknown or disabled mock keys fall through to the real artifacts. FAIL CLOSED.
  return realSlateOverview();
}
