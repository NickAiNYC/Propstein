# PropStein — Platform Architecture

**Repo:** `NickAiNYC/PropsteinP` · **Site:** `propstein.com`
**Posture:** evidence-first price-understanding and record-keeping terminal. Not a betting
recommendation product. The product charter (10 non-negotiable rules) governs every layer;
the copy linter enforces it in CI and at runtime.

---

## 1. Modular structure

```
PropsteinP/
├── pipeline/                     # PHASE 3 — daily data & model engine (Python 3.12)
│   ├── __main__.py               #   CLI orchestrator: python -m pipeline run [--date YYYY-MM-DD]
│   ├── config.py                 #   seeds, thresholds, paths, provider selection (env-keyed)
│   ├── schemas.py                #   Pydantic contracts: raw feed → features → run artifact
│   ├── determinism.py            #   FNV-1a, mulberry32, gauss, normal CDF (TS parity)
│   ├── odds.py                   #   implied probability, devig, American odds conversions
│   ├── http.py                   #   rate-limited fetcher: retries, exponential backoff + jitter
│   ├── requirements.txt          #   runtime deps (pydantic, httpx)
│   ├── providers/
│   │   ├── base.py               #   provider interface + registry
│   │   ├── synthetic.py          #   deterministic simulated feed (default; no keys required)
│   │   └── licensed.py           #   HTTP adapter activated by PROPSTEIN_FEED_* env keys
│   ├── features.py               #   feature engineering (seeded, schema-validated)
│   ├── models.py                 #   versioned model registry + deterministic inference
│   ├── scoring.py                #   Brier score, calibration bins, hit rate, day-over-day delta
│   ├── runs.py                   #   snapshot store: data/runs/*.json, idempotent writes
│   ├── validate.py               #   sanity gate: empty / NaN / row-count / schema failures
│   ├── report.py                 #   GitHub Actions Job Summary generator
│   └── tests/                    #   pytest suite (determinism, backoff, schema, run, validate)
│
├── data/                         # run artifacts — written by pipeline, read-only for the web app
│   ├── runs/YYYY-MM-DD.json      #   immutable daily snapshot (hash-verified, idempotent)
│   ├── latest_predictions.json   #   today's board + series + metrics (zero-latency read)
│   └── runs_index.json           #   telemetry index: dates, hashes, counts, health, durations
│
├── src/                          # /web + /api — the propstein.com serving layer (Next.js 16)
│   ├── app/                      #   App Router: single visible route + API routes
│   │   ├── api/pipeline/         #     telemetry + predictions artifact readers (fail-closed)
│   │   ├── api/slips/            #     upload (extraction only) + confirm (assessment)
│   │   └── api/…                 #     the charter endpoints (ledger, gates, alerts, …)
│   │   ├── error.tsx             #     explicit degraded state (no blank screens)
│   │   └── loading.tsx           #     terminal skeleton
│   ├── components/propstein/     #   terminal shell, telemetry header, board, drill drawer,
│   │                             #   sparklines, slip/ledger/record/alerts/gates/docs
│   └── lib/domain/               #   charter core: hurdle router, ledger, gate, copy-lint…
│
├── .github/workflows/
│   └── daily_model_run.yml       # PHASE 4 — autonomous daily execution (cron 0 11 * * *)
│
├── prisma/schema.prisma          # system of record: ledger, revisions, gates, compliance…
└── docs/ARCHITECTURE.md          # this file
```

Separation of concerns:

| Layer | Owns | Never does |
| --- | --- | --- |
| `/pipeline` | ingestion, features, inference, self-scoring, artifact writes | serve users |
| `/data` | versioned run artifacts (source of truth for the board) | mutate after write (idempotent by hash) |
| `/src` (web+api) | rendering, charter endpoints, ledger persistence | recompute model numbers |
| `.github` | scheduling, validation gates, artifact commit, deploy trigger | bypass the sanity gate |

## 2. Data flow (end-to-end)

```
[providers] --fetch(backoff, rate-limit)--> [raw feed (Pydantic-validated)]
      → [features] → [models] → [run artifact]  ──write──>  data/runs/YYYY-MM-DD.json
                                                     └────>  data/latest_predictions.json
                                                     └────>  data/runs_index.json
[GitHub Actions cron 0 11 * * *]  runs pipeline → validates → commits data/ → deploy hook
[propstein.com /api/pipeline/*]   reads artifacts (server-side, fail-closed)
[terminal UI]                     telemetry header + predictions board + drill-down drawer
[user slips]                      upload → confirm → charter hurdle router → immutable ledger
```

Key invariants:

1. **Determinism** — every stochastic value derives from FNV-1a seeds over stable keys
   (`namespace|sport|event|player|market|…`). Re-running a date reproduces a byte-identical
   artifact (hash-verified). `PYTHONHASHSEED` is pinned in config.
2. **Idempotency** — `runs.py` writes an artifact only if absent or hash-identical; a content
   mismatch on an existing date fails loudly instead of silently overwriting history.
3. **Fail-closed surfaces** — a missing/stale/corrupt artifact renders an explicit
   `PIPELINE OUTPUT UNAVAILABLE` state in the UI, never a fabricated board.
4. **Charter language** — the copy linter scans every component literal and JSX text node;
   CI runs it on every change. Board semantics use descriptive deltas only.
5. **No LLM in the decision path** — models are fixed deterministic functions of features;
   LLM usage (OCR extraction) is data-entry assistance only.

## 3. Run artifact contract (v1)

`data/runs/YYYY-MM-DD.json` and `data/latest_predictions.json` share the prediction schema
(Pydantic `RunArtifact` in `pipeline/schemas.py`; mirrored by the TS reader in
`src/app/api/pipeline/`). Each prediction carries:

- identity: `board_key` (stable across days), per-day `prediction_id`, sport/league/event/
  player/market/selection/line
- market: two-way American odds, implied + devigged fair probability, freshness timestamp
- model: version, coverage (`calibrated|uncalibrated|none|unavailable`), probability,
  95% uncertainty interval, feature contributions, limitations, corpus size
- diagnostics: `model_minus_market_pp` (descriptive spread — never an actionable-signal
  claim), `delta_pp_vs_prev` (day-over-day model movement), 7-run `series` for sparklines
- self-scoring: settled-history Brier score, hit rate, calibration deciles

`runs_index.json` carries telemetry: last successful run, run dates, prediction counts,
active model versions, health (`healthy|degraded|down`), execution durations, data source
label (`synthetic` vs licensed provider ids), and integrity hashes.

## 4. Deployment

- **Sandbox/reference:** Next.js dev server on port 3000 (gateway: Caddyfile), SQLite via
  Prisma, synthetic providers (labelled as simulated data on every surface).
- **Production:** same repo; licensed providers activate via `PROPSTEIN_FEED_ODDS_URL`,
  `PROPSTEIN_FEED_ODDS_KEY`, `PROPSTEIN_FEED_STATS_URL`, `PROPSTEIN_FEED_STATS_KEY`;
  Postgres swaps in for SQLite (identical Prisma models). The daily workflow commits
  `data/` and triggers the host deploy hook (`VERCEL_DEPLOY_HOOK_URL` secret, optional).

## 5. Observability

- Pipeline: stage-level durations + structured stdout summary; failures exit non-zero and
  surface in the GitHub Actions Job Summary (`report.py`).
- Web: `/api/pipeline/telemetry` is the single health source for the Live Telemetry Header;
  charter API routes emit structured audit events (`AuditEvent` model).
- UI: error boundaries (`error.tsx`, `global-error.tsx`) render explicit degraded states.
