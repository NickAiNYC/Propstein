# PropStein: Empirical NFL Prop Research Terminal

[![CI](https://github.com/NickAiNYC/Propstein/actions/workflows/python-tests.yml/badge.svg)](https://github.com/NickAiNYC/Propstein/actions)
[![Production Deploy](https://github.com/NickAiNYC/Propstein/actions/workflows/production-deploy.yml/badge.svg)](https://propstein.com)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

PropStein is an empirical quantitative prop research terminal and cryptographic CLV ledger for NFL receiving markets. It models outcomes with a compound Negative Binomial / Gamma distributional framework, logs closing line value against sharp consensus, and publishes its full calibration record—including negative holdout results.

**Live Terminal**: [propstein.com](https://propstein.com)  
**Track Record & Evidence**: [propstein.com/performance/](https://propstein.com/performance/)  
**Audit Protocol**: [docs/VERIFY.md](docs/VERIFY.md)

---

## 1. What PropStein Is (and Is Not)

- **Distributional Research, Not Tout Picks**: PropStein evaluates the full predictive distribution across every alternate line ($P(\text{over } X)$ for receptions and receiving yards). It never outputs "guaranteed picks", "locks", or recommended dollar bets.
- **Fail-Closed Market Pricing**: Ingested sportsbook odds require deterministic SHA-256 verification receipts. Unquoted or unverified lines fail closed and are excluded from qualification.
- **Market-Anchored Shrinkage**: When holdout empirical skill is unproven, the model anchors to the devigged market closing consensus as its prior and shrinks probability shifts toward $w \approx 0.25$ to prevent overconfident pricing.
- **No LLM in the Decision Path**: Numerical pricing and distribution integrals are calculated purely with deterministic mathematical models. Language models reason only after the numbers are frozen.

---

## 2. Published Track Record & Honest Posture

We publish our full calibration record as-is, without cherry-picking:

- **Full-Board Close Calibration (Week 7)**:
  - Total graded decisions: **$N = 37$**
  - **2 of 37 beat the close** (5.4%, 95% Wilson CI: [1.5%, 17.7%])
  - **34 of 37 tied the close** (91.9%, line unchanged in yard increments)
  - **1 of 37 closed worse** (2.7%, -1.0 yd drift)
  - Full quoted board evaluation: **$N = 320$** observations ($\hat{w} = 0.7597$, 95% CI $[0.4001, 1.1193]$)
- **Holdout Brier Skill Defect**:
  - In our Week 1 holdout evaluation, the model's Brier score ($0.2813$) trailed the naive baseline ($0.2500$), resulting in a **$-12.51\%$ Brier skill score**.
  - We treat this as an open defect under active recalibration, not marketing spin.
- **Commercial Gate Active**:
  - Because the decision 95% CI spans zero ($[-0.1013, +1.4497]$), paid subscriptions are frozen, quant tiers are waitlisted, and all marketing beat-close guarantees are withdrawn until $N \ge 300$ prospective decisions demonstrate statistically significant alpha.

---

## 3. Reproducible Audit (`make verify`)

Any operator or researcher can reproduce the cryptographic hashes and calibration benchmarks locally in seconds:

```bash
git clone https://github.com/NickAiNYC/Propstein.git
cd Propstein
make verify
```

The verification engine asserts four invariants:
1. **Ledger Root Hash**: Confirms that canonical hashing reproduces the published ledger root (`Root #178e29974bf8748c`).
2. **Prospective Timing**: Verifies that all 472 candidate snapshots in `full_board_2026_w8_early_1300.jsonl` were captured before kickoff.
3. **Leakage Gate**: Confirms that decision cutoffs are strictly enforced and zero future snapshots were included in holdout evaluations.
4. **Market-Model Blend**: Verifies the empirical blend regression parameters and checks that commercial gates fail closed.

See [docs/VERIFY.md](docs/VERIFY.md) for full audit specification.

---

## 4. Distribution Architecture

```text
src/
├── model.py            # Compound NegBin/Gamma distribution & market shrinkage blend
├── value_boundaries.py # Continuous & discrete vig boundaries, push calculations
├── prospective_board.py# Pre-kickoff candidate universe locking & timing audit
├── grade_clv.py        # Probability-space and line-delta CLV validation
├── line_history.py     # B1 continuous multi-book quote capture & schema
├── sgp_detector.py     # Same-Game Parlay correlation detection vs benchmark haircuts
├── features.py         # Leakage-free feature pipelines with strict cutoffs
└── slate.py            # Weekly roster, injury, and schedule context ingestion

viewer/
├── js/quant-math.js    # Standalone verified odds math & Lanczos regularized gamma
├── js/sports/          # Modular sport adapters (NFL calibrated, NBA uncalibrated)
├── performance/        # Published full-board track record & holdout calibration
└── index.html          # Operational research terminal (pre-rendered zero-skeleton paint)
```

---

## 5. Running Tests Locally

```bash
# Python suite (456 tests)
make test-py

# Node.js suite (289 tests)
make test-node

# Complete verification & test run
make test
```

---

## 6. Responsible Research & Disclaimer

PropStein is quantitative sports analytics research, not betting advice. No content on this site or in this repository constitutes an offer, solicitation, or recommendation to wager. 21+ where applicable. If you or someone you know has a gambling problem, call 1-800-GAMBLER.
