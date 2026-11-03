# B1 — Line-History Capture: Schema Spec & Decision Frame

**Status:** PROPOSED — owner decision required (provider + budget + book scope)
**Author:** session work, 2026-10-27
**Depends on:** nothing (forward-only; starts whenever approved)
**Feeds:** CLV ledger, public-page line-movement charts, steam alerts, best-line board

---

## 1. Why this is the moat

Everything else in PropWire is reproducible: the UI, the projection math,
the page structure. The one asset that **cannot be cloned later** is a
timestamped, cross-book history of prop lines — because markets only move
forward. Every week this is not capturing is a week of history that will
never exist. This spec exists so the B1 decision can be made in one sitting
and capture can start the same day.

Design constraints inherited from the existing invariants:

- **Observation time is sacred.** Every row stores *when* the line was seen,
  from *which* source, with a verification flag — same honesty rules as the
  pre-kickoff snapshots (`viewer/` snapshot JSON) already enforce.
- **Never present stale as current.** Consumers (terminal, public pages)
  must render a captured_at timestamp with every line series.
- **Forward-only.** No synthetic backfill. Gaps are gaps and stay visible.

## 2. The owner decision (B1 blockers)

| Decision | Options | Recommendation |
|---|---|---|
| Provider | (a) The Odds API — aggregated, cheapest, ~limited books; (b) OpticOdds / similar prop-focused feeds — broader props coverage, mid cost; (c) direct sportsbook APIs/feeds — best data, hardest TOS/engineering | **(b) if budget allows, else (a)**; store raw payload + provider row so swaps are cheap |
| Budget | $0 manual / ~$30–100 mo API / enterprise | start mid-tier; the data accrues in value monthly |
| Book scope | start 3–5: Pinnacle (closing benchmark), DraftKings, FanDuel, Caesars, BetMGM | Pinnacle non-negotiable (closing-line reference) |
| Market scope | receiving yards + receptions first, then rushing/passing yards, then game-level | matches existing public-page structure 1:1 |
| Closing-line definition | last Pinnacle pre-kickoff vs consensus median | **Pinnacle last pre-kickoff** (industry-standard CLV benchmark); store consensus too |
| Storage | SQLite file in repo-adjacent storage → Postgres when >1GB or concurrent writers | start SQLite (zero-ops), schema is Postgres-portable below |

## 3. Schema (v1 — SQLite DDL, Postgres-portable)

```sql
CREATE TABLE events (
  event_id     TEXT PRIMARY KEY,      -- namespaced: '<provider>:<native_id>'
  league       TEXT NOT NULL DEFAULT 'nfl',
  season       INTEGER NOT NULL,
  week         INTEGER NOT NULL,
  home_team    TEXT NOT NULL,
  away_team    TEXT NOT NULL,
  kickoff_utc  TEXT NOT NULL,         -- ISO-8601; drives pre-kickoff windows
  status       TEXT NOT NULL DEFAULT 'scheduled'  -- scheduled|live|final
);

CREATE TABLE players (
  player_id    TEXT PRIMARY KEY,      -- internal stable id (reuse the id in
                                      -- snapshots_2026_w7.json; never renumber)
  full_name    TEXT NOT NULL,
  team         TEXT,
  position     TEXT,
  aliases      TEXT                   -- JSON array of provider name variants
);

CREATE TABLE books (
  book_id      TEXT PRIMARY KEY,      -- 'pinnacle','draftkings','fanduel',...
  display_name TEXT NOT NULL,
  active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE lines (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id      TEXT NOT NULL REFERENCES books(book_id),
  event_id     TEXT NOT NULL REFERENCES events(event_id),
  player_id    TEXT REFERENCES players(player_id),  -- NULL = game-level market
  market       TEXT NOT NULL,         -- 'receiving_yards','receptions',...
  line         REAL NOT NULL,         -- 78.5
  over_price   INTEGER,               -- American odds, -110
  under_price  INTEGER,
  captured_at  TEXT NOT NULL,         -- UTC observation time (source of truth)
  source       TEXT NOT NULL,         -- 'api'|'screen'|'manual'
  verified     INTEGER NOT NULL DEFAULT 0,
  raw_hash     TEXT                   -- sha256 of provider payload (audit)
);

CREATE UNIQUE INDEX ux_lines_dedupe
  ON lines(book_id, event_id, IFNULL(player_id,''), market, line,
           over_price, under_price, captured_at);
CREATE INDEX idx_lines_series ON lines(event_id, player_id, market,
                                       captured_at);
CREATE INDEX idx_lines_steam  ON lines(event_id, market, line, captured_at);
```

Notes:

- `IFNULL(player_id,'')` keeps game-level rows dedupe-safe in SQLite.
- Prices are `INTEGER` American odds; never floats for money lines.
- `verified` mirrors the terminal's verification-state honesty rules; rows
  captured from screen/manual sources start unverified.
- Postgres port: `AUTOINCREMENT`→`BIGSERIAL`, `IFNULL`→`COALESCE`,
  `TEXT` timestamps→`timestamptz`. Nothing else changes.

## 4. Capture cadence (adaptive)

| Mode | Trigger | Interval |
|---|---|---|
| Baseline sweep | always | 15 min |
| Pre-kickoff sprint | T-3h → kickoff | 60 s |
| News sprint | injury/scratch trigger (existing `news_watcher.py`) | 60 s for 2h |
| Steam sprint | any book moves ≥ threshold (see §6) | 30 s for 30 min |

Capture job rules:

1. One sweep = one pass over all (book × active event × market) tuples.
2. Insert only on **change** (line or either price) vs that book's last row
   — identical re-quotes do not get rows (dedupe index backstops).
3. Never mutate or delete a captured row. Corrections = new row with
   `source='manual'` + note. (Forward-only, like git history.)
4. Every row's `captured_at` is the **observation time**, not fetch-completion
   time; if a provider batches, use its reported timestamp and set
   `verified=0` when uncertain.

Volume estimate at 5 books × 400 props × adaptive cadence: ~150–300k rows/week
during season — SQLite handles this for years; downsample >90-day-old rows to
a 5-min grid if it ever exceeds ~5GB (keep every row inside the last 90 days
at full resolution forever).

## 5. Access patterns (what this unlocks)

**CLV (existing ledger, upgraded):** closing line = last pre-kickoff Pinnacle
row per (event, player, market). User entry price vs that close = CLV. The
current CLV ledger uses per-week snapshot files; this makes it continuous
and per-timestamp instead of per-slate.

**Line-movement sparklines (public pages, SEO moat):** per player-market page,
a 7-day series `{t, line, over, under}` per book → tiny inline SVG chart.
Generated statically by `build_public_pages.py` reading the capture DB —
no runtime backend, CSP stays clean. Unique data per page = pages that rank
and get cited.

**Best-line board (terminal):** latest row per book per (player, market) →
max over_price / max under_price + which book. Rendered client-side from a
pre-generated JSON snapshot (same no-backend pattern).

**Steam detection (alerts):** moving window over `idx_lines_steam`: N books
(≥3) moving the same direction within T minutes (≤10) with magnitude ≥ M
(≥1 point or ≥15¢). Emits to the existing news/telemetry pipeline.

## 6. API contract (static-first)

The site is static; the "API" is pre-generated JSON committed alongside the
pages (regenerated per build), exactly like other viewer data:

```
GET /api/lines/<player_slug>/<market_slug>.json
{
  "player_id": "00-0032464",
  "market": "receiving_yards",
  "generated_at": "2026-10-27T14:00:00Z",
  "window_hours": 168,
  "series": {
    "pinnacle":  [ { "t": "...", "line": 78.5, "over": -110, "under": -110 } ],
    "draftkings":[ { "t": "...", "line": 79.5, "over": -115, "under": -105 } ]
  },
  "closing": { "book": "pinnacle", "line": 78.5, "over": -110, "under": -110,
               "captured_at": "...", "verified": 1 }
}
```

Consumer honesty rule: every chart/number rendered from this file must show
`generated_at`/`captured_at` — no undated numbers, same as everything else.

## 7. Rollout phases

- **P1 (day one):** schema + capture job for ONE book (Pinnacle via chosen
  provider) + market scope receiving_yards/receptions. Success = rows land
  reliably for a full week.
- **P2 (week two):** add 3–4 books; add news-triggered sprints; publish a
  private coverage dashboard (rows/day, gaps, book uptime).
- **P3 (weeks three–four):** static JSON API + sparklines on the 780
  player-market pages (regen via `build_public_pages.py`); best-line board
  upgrade in terminal.
- **P4 (month two):** steam alerts (Discord/Telegram webhook); CLV ledger
  switches to continuous closing lines; start charging only after the legal
  pack ships.

## 8. Open items for the owner

1. Provider + budget (§2) — the only true blocker.
2. Confirm Pinnacle-as-closing-benchmark convention.
3. Where the capture job runs (GitHub Actions cron is fine for 15-min
   baseline; sprint mode wants a long-running box or Vercel cron at 1-min).
4. Storage location for the SQLite file (repo LFS vs small VPS) — must NOT
   go into the public repo if provider TOS forbids redistribution.
5. Confirm market priorities beyond the first two.
