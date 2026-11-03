# DECISIONS — nba_model v1

Recorded 2026-11-03. Every decision here is revisitable; the point is
that none of them is silent.

## D1. Data source — BallDontLie paid box-score tier (DECIDED)

**Decision:** balldontlie NBA API, ALL-STAR tier ($9.99/mo) or higher,
for box scores; free tier covers games metadata. Key: `BALLDONTLIE_API_KEY`.

Why:
1. It is already the project's user-approved Phase 0.5 data-source gate
   (documented in `scripts/fetch_nba.py`): the only documented,
   ToS-clean NBA source; scraping NBA.com/ESPN endpoints is forbidden
   by the project ToS rule.
2. `BALLDONTLIE_API_KEY` plumbing, rate limiting, provenance stamps and
   ET slate keying already exist in the repo and are reused.
3. Price is trivial vs. enterprise alternatives (Sportradar, Stats
   Perform) which are built for rights-holders, not research terminals.
4. The provider is abstracted (`data/providers.py::fetch_range`), so a
   second licensed provider (e.g. MySportsFeeds) can be added without
   touching model code.

What stays out of scope until verified on the paid tier: balldontlie's
injuries endpoint availability. Availability adjustments currently
consume the project's own feed (`nba_injuries_*.json` schema), which is
the proven path.

## D2. GitHub repositories — borrow methodology, never models (DECIDED)

| Repo | Verdict | What we took | What we refused |
|---|---|---|---|
| parlayparlor/nba-prop-prediction-model | MIT, one file, no tests, rolling averages | nothing — it is the baseline we must beat, and our naive baseline plays that role | the "model" itself |
| Soskid107/nba-prop-engine | strongest architecture, MIT, but lightly tested, scraping-reliant, ships serialized models | the *shape* of the pipeline (ingest → features → distribution → gate) | its model binaries (unsafe pickle pattern), its scrapers, its code |
| rnsapountzis/nba-player-props-ml-pipeline | best validation discipline, model excluded from repo | date-based walk-forward + leakage paranoia (we test both layers) | nothing else exists to take |
| Shrey6876/nba-quant-engine | feature ideas, unproven 64%/22% ROI, ~no tests | none of the claims — no independently verifiable evidence | the ROI numbers entirely |

Rule going forward: any external idea enters through a test in
`tests/nba_model/` or it does not enter.

## D3. Model family — interpretable assembly, not ML (DECIDED)

Minutes × points-per-minute × context multipliers, explicit variance
budget. Rationale: with ~30 games of per-player history the honest
signal is small; an interpretable model with a full `explain` dict can
be audited line-by-line on the receipt, which is this product's
differentiator. Calibrated ML can graduate individual components later
(e.g. minutes) behind the same gates.

## D4. Calibration gate vs. market gate (DECIDED)

- **Gated:** n ≥ 300 predictions, Cox slope ∈ [0.80, 1.25], Brier ≤
  naive baseline. These are properties the model can own.
- **Reported only:** Brier vs. de-vigged market. A model that loses to
  the market should be *visible*, not silenced — hiding it is how
  terminals start lying again (see the v176 74.2% beat-rate incident).

## D5. Thresholds and their rationale (TUNING, review after 500 predictions)

- `EDGE_HURDLE = 0.08` — NFL receiving uses 0.10; NBA points carry more
  per-play variance. Revisit with real data.
- `ODDS_MAX_AGE_SECONDS = 600` — pre-game quotes; aligns with the v177
  feed-status banner's 15–30 min stale band, tight end for publishing.
- `BOXSCORE_MAX_AGE_HOURS = 30` — data through yesterday ET plus late
  tip-offs and ingest latency.
- `MIN_INDEPENDENT_BOOKS = 2` — books are the independence unit; one
  licensed feed serving many books is fine, two book keys quoting the
  same line is the floor for a real price.
- `SD_FLOOR_PTS = 4.0` — NBA points never have a tighter predictive sd
  than this; floors stop shrinkage from fabricating confidence.

## D6. Scope — points only in v1 (DECIDED)

Rebounds and assists reuse the same projector skeleton (minutes-driven
with their own per-minute rates); they are intentionally absent until
points calibration demonstrates the loop works end-to-end.

## D7. Free data path — official stats.nba.com feeds (DECIDED, owner call 2026-11-03)

**Decision:** the production default provider is `nbacom` — the official
stats.nba.com league feeds (`leaguegamefinder` for games + per-day team
rows, `boxscoretraditionalv2` for player box scores), keyless and free,
implementing the exact normalized row schema and fail-closed contract as
the balldontlie provider (`data/nbacom.py`).

Implementation stance: endpoint/parameter contracts and browser-grade
headers mirror **swar/nba_api** (MIT, ~3.9k stars) — the maintained
reference for this surface, whose header fixes land in point releases
(v1.11.4 / #633). We speak the same endpoint language through our own
injectable transport instead of importing the library's request layer:
the provider stays hermetically testable, adds zero runtime
dependencies, and swapping in the library itself later is a one-function
change (`_default_transport`).

Why: owner directive — run Propstein on Vercel at $0. balldontlie's box
scores sit behind "Full data access" (GOAT $39.99/mo per their pricing
page fetched 2026-11-03; the $299.99/mo All-Access tier is the
multi-sport/webhooks bundle) — the D1 note that ALL-STAR ($9.99) covered
`/v1/stats` no longer matches their current tier copy.

Honest trade-offs, accepted by the owner call:
1. Unofficial access to league endpoints: no SLA; the edge can block
   datacenter IPs (GitHub Actions runners included) at any time.
   Mitigation: fail-closed everywhere — a blocked run is RED and visible,
   never silently empty.
2. Header/endpoint drift: when NBA.com changes, mirror the upstream
   swar/nba_api fix in `NBA_COM_HEADERS`/params.
3. Politeness discipline: 1.2 s spacing between successful calls, one
   60 s 429 backoff, then fail closed.

What does NOT change:
- `bdl` remains wired as the licensed alternative (D1).
- ESPN / other stat-site scraping stays forbidden.
- Odds still flow through the project's existing odds feed — stats.nba.com
  has no odds, so the independent-quote gate stays honest.
- Availability stays on the project's `nba_injuries_*.json` schema.
- The api-evangelist public API surface/OpenAPI maps (balldontlie,
  thesportsdb) were reviewed as response-shape references and deliberately
  not adopted: Propstein's canonical schema is the provider-agnostic
  normalized row in `data/providers.py`; external wrappers must come to
  it, not the reverse.

Topology note (free hosting): the daily ingestion worker is
`.github/workflows/nba_model_daily.yml` (GitHub Actions cron → pipeline
→ artifacts committed to `viewer/feeds/nba_model/` → Vercel serves them
statically). Git is the cache layer; a Postgres cache (Supabase/Neon)
is an optional future upgrade for queryable history, not a v1
dependency.
