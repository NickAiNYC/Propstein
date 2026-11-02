<img src="viewer/propstein-logo.svg" alt="PropStein logo" width="420" />

PropStein is a distributional prop model and operational terminal for NFL receiving markets. It prices outcomes with a compound negative-binomial / gamma framework, runs weekly slate logic, and logs closing-line value with a disciplined risk gate.

**Historical context gate:** New model fits and weekly projections are blocked while the nflverse game spread, total, and weather inputs lack observation timestamps. The existing frozen artifacts remain available for research, but they are not evidence that these context values were known at pricing time. The weekly model command below will fail closed until timestamped context and per-row pricing cutoffs are supplied. See [Feature cutoff gate](docs/FEATURE_CUTOFF_GATE.md).

Built for edge detection, not hype: the model is probabilistic, walk-forward validated, and intentionally conservative. No LLM sits in the decision path; the language model reasons after the numbers are fixed.

## Why PropStein

- Distribution-aware pricing for receptions and receiving yards
- Real-time weekly slate generation and live line comparison
- Risk-gated picks with EV and Kelly guidance
- CLV logging and audit workflow for model accountability
- Clean deployment on a high-performance edge stack

## 3. Weekly Operational Cadence

1. **Tuesday – Thursday (Ingest & Projection)**
   - Schedule and depth charts finalize.
   - Run the weekly pipeline via the UI **Run Slate** button or terminal:
     ```bash
     python src/week1.py --season 2026 --week 1
     ```
   - Model fits in ~2 seconds and refreshes `slate_projections.json`, `current_picks.json`, and `top_picks.json`.

2. **Friday – Sunday Morning (Line Comparison & Execution)**
   - Open the **Slate Browser** and enter your sportsbook line in the **Book Line Comparison** tool.
   - The app runs the compound distribution and flags qualifying plays:
     - 🟢 **Green**: Edge >= 10% in W1 / >= 3% normal; value play clearing the calibration gate with EV per unit and Kelly guidance.
     - 🟡 **Yellow**: Positive edge below the strict risk gate (lean/watch).
     - 🔴 **Red**: Negative edge / sharp book.
   - Click **Save Bet to CLV Tracking Log** in the Calculator to add active plays to `picks_log.jsonl`.
   - Click **Copy as Text for Slips** in the Top Picks Card for rapid slip entry.

3. **Sunday Night / Monday (Closing Line Value Audit)**
   - Once games lock or settle, open the **CLV Tracking Log** tab.
   - Select logged picks and input the closing devigged probability or closing odds.
   - The app computes `clv = model_prob - closing_prob` and updates the running 95% confidence interval.

---

## 4. Production Deployment

The viewer frontend and precomputed slate data are deployed globally via Vercel:

- **Live Production URL**: [propstein.vercel.app](https://propstein.vercel.app)
- **Vercel Project**: [`propstein`](https://vercel.com/nicks-projects-ec56abd4/propstein)
- **Deployment root**: repository root (`.`). The root [`vercel.json`](vercel.json) publishes `viewer/`.
- **Operational model**: static assets are versioned, service workers are fail-closed, and edge caching is tuned for speed and reliability.

To publish the latest slate build:

```bash
vercel --prod
```

The edge deployment builds and propagates in roughly 4 seconds.

---

## Architecture Snapshot

```text
src/features.py   leak-free inputs and leakage checks
src/slate.py      weekly slate build, roster/injury ingestion, Week 1 handling
src/week1.py      CLI runner for live weekly pipelines
src/model.py      compound distribution, de-vig, Kelly logic
src/baseline.py   form-only line setter
src/backtest.py   walk-forward calibration and simulation
src/parlay.py     correlation-aware SGP and alt-line pricing
src/odds.py       odds API client and no-vig consensus logic
src/agent.py      picks engine, hard gate logic, CLV logging
api/main.py       FastAPI service, billing, and entitlement layer
```

## Quick Start

```bash
pip install -r requirements.txt        # intent spec (floor ranges)
pip install -r requirements.lock       # reproducible set — what CI runs the suite against
```

`requirements.txt` declares intent; `requirements.lock` is the exact pinned
set CI installs and the full test suite is validated against (refresh protocol
in the lock header).

Then run the weekly model (season/week are arguments — rolling to 2027 is a
data exercise, see [docs/SEASON-ROLLOVER.md](docs/SEASON-ROLLOVER.md)):

```bash
python src/week1.py --season 2026 --week 1
```

---

## Disclaimer

Statistical estimates for research and entertainment. Not financial advice.
21+ where legal. If gambling is causing harm, call 1-800-GAMBLER.
