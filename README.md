# Propstein 2.0 — Live Sports Prop Terminal

One repo. One app. Zero paid APIs.

Next.js (App Router, TS) + Tailwind terminal UI over Prisma (Supabase/Neon
Postgres in production, SQLite for preview), fed by a GitHub Actions cron
running the Python ingest workers against **free, key-less public data**:

| source | what | cost |
| --- | --- | --- |
| `site.api.espn.com` public JSON | NBA/NFL/NHL scoreboards, box scores, player identities | $0, no auth |
| `nba_api` (stats.nba.com) | active-player registry | $0, no auth |
| v1 snapshot live-odds feed (`worker/data/`) | Polymarket prop quotes + model fair lines | $0 |

## Free / Pro tiers (single-app gating)

| | Free | Pro |
| --- | --- | --- |
| Live scores (NBA/NFL/NHL) | ✅ full | ✅ full |
| Player directory + season stats | ✅ | ✅ |
| Rolling box-score form (L3) | ❌ blurred | ✅ |
| Props per slate | first 3 teaser rows | full join-flattened feed |
| Line freshness | 15-min delay | live |
| Direction (side + Watch/Pass lean) | ✅ | ✅ |
| Exact model numbers (prob, fair odds, EV, Kelly) | ❌ blurred | ✅ |
| Book comparison (best book ★) | ❌ | ✅ |
| Copy-for-slips + CSV export | ❌ | ✅ |

Enforcement is server-side in `/api/props` and `/api/players`: the free
response **omits** `probWin`, `fairOdds`, `ev`, `kelly`, `fairLine` and
`formSummary` fields entirely (the UI blur is cosmetic on top of stripped
payloads, not the gate itself).

Production wiring: Supabase Auth session → `user.isPro` (written by the
Stripe billing webhook). Preview wiring: the `propstein_tier` cookie
flipped by the sidebar toggle — default `free`, exactly what an anonymous
visitor sees.

## Player identity (the v2 fix)

The v1 build collided two ID namespaces under one prefix (LeBron existed
twice: `espn-nba-2544` registry vs `espn-nba-1966` ESPN). v2 keeps them
separate and merges by `nameKey` with ESPN canonical:

```
espn-nba-{espnAthleteId}   canonical — team/position/form/stats from box scores
nba-{nbaStatsId}           registry-only — name until ESPN box data arrives
nfl-{nameKey}              v1 snapshot NFL players
```

When an ESPN row meets an existing registry row with the same
`(league, name_key)`, the registry row is retired and its `nbaStatsId`
carried onto the ESPN record — one human, one row, richest identity wins.
Guard: `@@unique([league, nameKey])`.

## Repo layout

```
prisma/schema.prisma            SQLite preview schema
prisma/schema.postgres.prisma   canonical Postgres schema (Supabase/Neon)
worker/ingest_games.py          ESPN scoreboards -> Game
worker/ingest_players.py        registry + ESPN summaries -> Player (merge)
worker/ingest_props.py          snapshot quotes -> Prop (+ EV/Kelly)
worker/upsert.py                chunked atomic upsert core (psycopg3)
worker/ev.py                    odds/EV/Kelly math (mirrors src/lib/ev.ts)
worker/selftest.py              offline sanity suite (11 tests)
worker/data/                    v1 snapshot fixtures (live odds, picks)
.github/workflows/ingest.yml    cron: games+players 15m, props hourly
src/app/api/*                   games / players / props (tier-gated) / tier
src/components/terminal/*       sidebar, ticker, panels, paywall UI
scripts/seed.ts                 real-data seed for local preview
research/                       preserved v1 quant research (untouched)
```

## Local preview

```bash
bun install
bun run db:push                # SQLite schema
bun scripts/seed.ts            # real ESPN + snapshot data (~1 min)
bun run dev                    # http://localhost:3000
python worker/selftest.py      # offline math + fail-closed checks
```

Flip Free ⇄ Pro with the sidebar toggle and watch `/api/props` strip vs
serve the model columns.

## Deploy (Vercel + Supabase)

1. **Supabase**: create project → copy the pooled connection string.
2. **Database**: `npx prisma db push --schema prisma/schema.postgres.prisma`
   against the Supabase URL (tables + indexes + unique guards).
3. **GitHub Actions secret**: `DATABASE_URL` = same pooled URL — the cron
   then fills Game/Player/Prop every 15 minutes.
4. **Vercel**: import this repo (root = repo root, framework Next.js),
   set `DATABASE_URL` env var, deploy. API routes read through Prisma with
   `s-maxage=60, stale-while-revalidate=300` CDN caching.
   The `postinstall` hook (scripts/postinstall.mjs) auto-picks the Postgres
   schema when `DATABASE_URL` is a `postgres://` URL — no other build
   settings to change.
5. **Auth (optional at first)**: add Supabase env vars; swap the demo
   `/api/tier` toggle for `getTier()` reading the Supabase session claim.

## Honesty notes

- Prop rows carry `verified` + raw provenance in `rawPayload`; synthetic
  demo fixtures in the snapshot are **skipped**, never ingested.
- The model (Gaussian tail around the fair line, market-aware sigma) is an
  estimate. EV/Kelly are model outputs, not betting advice.
- Season stats start as "tracked-games averages" and converge as the cron
  accumulates box scores.

*v1 static site is preserved on branch `v1-static-archive` and tag `v1.0.0`.*
