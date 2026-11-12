# nba_model — PropWire's independent NBA player-points model

v1 scope: **game points**, fully interpretable, published only through
fail-closed gates with SHA-256 receipts on PropWire's existing trust
primitives (`src/crypto_utils.py`, canonical JSON).

This package shares **zero code** with the NFL receiving stack
(`src/model.py`) and imports **no external model**. See `DECISIONS.md`
for the data-source decision and the four GitHub repositories we
evaluated (methodology only — never predictions or serialized models).

## Architecture

```
data/providers.py    BalldontlieProvider (licensed, fail-closed, paginated)
                     FixtureProvider (committed research fixtures)
                     SyntheticSeasonProvider (deterministic offline season)
data/dataset.py      tidy player-game frame + team-game pace/margin
features/form.py     rolling 5/10/20 form — shift(1) no-leakage guard
features/minutes.py  expected minutes: recent-5 blend + garbage trim
features/context.py  team pace & opponent defence (train-window only) + B2B rest
features/injuries.py availability feed: Out/Questionable/teammate-out boosts
model/projector.py   mean & variance assembly + full `explain` dict
model/distribution.py discretized Gaussian tails, push mass, DNP mixing
eval/devig.py        multiplicative + power de-vig, per-exact-line consensus
eval/walkforward.py  date-based expanding-window harness (leakage-guarded)
eval/calibration.py  Brier, log-loss, reliability bins, Cox slope (logistic)
publish/gates.py     freshness / calibration / independent-quote gates
publish/board.py     top-8 selection + canonical SHA-256 receipt chain
cli.py               prepare / walkforward / publish
```

## The interpretable v1 projection

```
mean_pts = ppm_hat × minutes_hat × rest_mult × pace_mult × opp_mult
           × form_mult × availability_mult
sd_pts   = sqrt((sd_ppm × minutes_hat)² + (ppm_hat × sd_minutes)²)
           × var_inflation                    [floored at 4.0 pts]
```

Every multiplier is fitted on the training window only and every
projection row carries `explain` — a published number can be re-derived
by hand from its receipt.

## Quickstart (fully offline)

```bash
python3 src/nba_model/cli.py prepare     --provider synthetic --start 2026-10-19 --days 45
python3 src/nba_model/cli.py walkforward --provider synthetic --start 2026-11-01 --end 2026-12-01 --days 45
python3 src/nba_model/cli.py publish     --provider synthetic --days 45 --as-of 2026-12-02T22:50:00Z
```

Exit codes: `0` ok · `2` missing API key · `3` tier lacks box scores ·
`4` rate limit · `5` network/no-data · `6` bad args · `10` publish
REFUSED by gates (a refusal artifact is still written, with reasons).

## Pregame research path (FREE — stats.nba.com, D7 owner call)

```bash
python3 src/nba_model/cli.py prepare --provider nbacom --start 2026-10-20 --end 2026-11-03
python3 scripts/build_nba_pregame_research.py \
  --dataset-dir src/nba_model/out \
  --games viewer/nba_games_2026-11-04.json \
  --odds viewer/nba_odds_2026-11-04.json \
  --out src/nba_model/out --date 2026-11-04
```

The pregame bridge resolves FanDuel player names against official NBA player IDs
and teams in today's scheduled games. It rejects ambiguous identities and
synthetic inputs, uses only completed box scores before the slate, and writes
`nba_research_<date>.json` plus `nba_board_<date>_REFUSED.json`. Research
probabilities are explicitly **uncalibrated**; no edge ranking or recommendation
is emitted. The bridge currently has no injury feed and only one book, and
there is no scored historical quote sample. Its board must remain REFUSED.

`--provider nbacom` is the FREE, keyless default: official stats.nba.com
league feeds (`leaguegamefinder` + `boxscoretraditionalv2`) with endpoint
contracts and browser-grade headers mirroring **swar/nba_api** (MIT).
Politeness: 1.2 s spacing, one 60 s 429 backoff, then fail closed — a
blocked run is RED, never silently empty. The daily ingestion worker is
`.github/workflows/nba_model_daily.yml` (GitHub Actions cron → artifacts
committed to `viewer/feeds/nba_model/` → Vercel serves them statically:
no paid API, no database). **Residential-IP requirement (confirmed
2026-11-03):** NBA's official feeds block datacenter IPs — GitHub-hosted
runners included (the workflow probes and skips with a notice when
blocked). Run the pipeline from a residential line via
`scripts/nba_model_local_worker.py` (cron/launchd on your machine) or a
self-hosted runner; machines that cannot reach stats.nba.com fail
closed — RED, never silently empty. Evidence and details:
`src/nba_model/DECISIONS.md` D7.

### Licensed alternative (D1, still wired)

`BALLDONTLIE_API_KEY` + box-score tier ("Full data access" per
balldontlie's current pricing page — GOAT $39.99/mo; the earlier note
that ALL-STAR $9.99 covered `/v1/stats` no longer matches their tier
copy) — the Phase 0.5 user-approved gate documented in
`scripts/fetch_nba.py`. The provider is fail-closed: no key → nothing
fetched, nothing written; a tier error never produces partial model
input. Odds continue to flow through the
existing project feed (`nba_odds_*.json` schema — quotes with
`book / market / line / over_odds / under_odds / observed_at`);
availability through the existing `nba_injuries_*.json` schema —
stats.nba.com provides neither odds nor a clean injury feed, so both
gates stay honest through the project's own feeds.

Swapping in another licensed stats provider later means implementing
`fetch_range()` against the same normalized row schema — the feature,
model, eval and publish layers never learn which provider ran.

## Gates (all must pass before a board exists)

1. **Freshness** — box scores ≤ 30h old; quotes ≤ 10 min old.
2. **Calibration** — ≥ 300 scored walk-forward predictions; Cox
   reliability slope inside [0.80, 1.25]; model Brier no worse than the
   naive season-mean baseline. Beating the market is REPORTED on the
   receipt, never gated — visibility beats silence.
3. **Independent quotes** — per play: ≥ 2 distinct books on the exact
   market+line inside the freshness window. Books are the independence
   unit (one licensed feed may serve many books).

A failed gate produces a `_REFUSED` artifact with reasons and a history
entry — never an empty-but-ranked board.

## Artifacts (`src/nba_model/out/`, gitignored)

- `nba_player_games.csv|.parquet`, `nba_dataset_meta.json`, `nba_odds_feed.json`
- `nba_walkforward_summary.json`, `nba_walkforward_records.csv`
- `nba_board_<date>.json` (receipt: `sha256`, `prev_sha256`, `locked_at`)
- `nba_board_<date>_REFUSED.json`, `nba_board_history.jsonl` (append-only, hash-chained)

Board history is tamper-evident: each entry commits to the previous
receipt, the same discipline as the freeze system.

## Viewer consumption contract (v178 wiring, not in this change)

`nba_board_<date>.json` is a bare JSON object with
`schema: "propwire.nba_board.v1"`, `plays[]` (each with player, market,
line, side, model/market probabilities, edge, books, explain), plus the
gate and walk-forward summaries. The UNCALIBRATED badge rule carries
over verbatim: `walk_forward.uncalibrated: true` ⇒ research-only
display, no ranking.

## Known v1 limitations (honest list)

- Gaussian shape is an approximation; the calibration gate is what
  decides whether it may publish. First 45-day synthetic walk-forward:
  z_sd = 1.13 (under-dispersed → Cox slope ≈ 0.2–0.4 → REFUSED, as it
  should be). Next iteration: variance recalibration from walk-forward
  z-scores, then re-test.
- Model v1 loses to the de-vigged market on synthetic data
  (Brier +0.013). Reported, not hidden; the market comparison rides on
  every receipt.
- Single-market (points). Rebounds/assists plug into the same projector.
- Availability boosts are share-based; feed `redistribution_plan`
  refinement is a v1.1 item.

## Tests

`python3 -m pytest tests/nba_model -q` — 70 tests, offline, no network:
de-vig math, minutes/form units, distribution tails & push mass,
**two-layer no-leakage walk-forward contract** (future rows cannot move
today's predictions; a training-window canary proves the harness reacts),
calibration slope direction, every gate failure mode, and receipt
canonical-hash + chain integrity.
