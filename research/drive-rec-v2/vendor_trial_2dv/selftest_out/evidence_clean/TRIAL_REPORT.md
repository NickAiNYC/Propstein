# Decision 2D-V Trial Verification Report — DECISION_2DV_TRIAL_v1

- **Data label:** `SYNTHETIC-HARNESS-TEST`  — SYNTHETIC HARNESS TEST, not vendor evidence
- **Sample:** 8 games (4 x 2025, 4 x 2026 w1-7)
- **Overall verdict:** **BLOCKED_PENDING_MANUAL** — V8 written permission outstanding — full acquisition BLOCKED until attached

## 1. Verified sample

| game | season | week | books (max) | players priced (max) |
| --- | --- | --- | --- | --- |
| SYN25_G01 | 2025 | 6 | 3 | 8 |
| SYN25_G02 | 2025 | 9 | 3 | 8 |
| SYN25_G03 | 2025 | 14 | 3 | 8 |
| SYN25_G04 | 2025 | 19 | 3 | 8 |
| SYN26_G05 | 2026 | 1 | 3 | 8 |
| SYN26_G06 | 2026 | 3 | 3 | 8 |
| SYN26_G07 | 2026 | 5 | 3 | 8 |
| SYN26_G08 | 2026 | 7 | 3 | 8 |

## 2. Coverage and missingness

- ledger rows (game x time x book): **72** (0 absent-book slots recorded explicitly)
- pulled/absent player-lines: **24** → `selftest_out/evidence_clean/pulled_lines.csv`
- discovery misses: 0

## 3. Actual API consumption

- metered requests: **26**; measured total **240** credits vs cap 600
- by request kind: baseline_sports=0, historical_event_odds=240
- quote pulls: modeled **240**; actual-vs-modeled mismatches: 0
- consumption-unestablished rows: 0; header inconsistencies: 0

## 4. Check verdicts V1-V10

| check | title | status |
| --- | --- | --- |
| V1 | Historical availability | **PASS** |
| V2 | Timestamp integrity | **PASS** |
| V3 | Market identification | **PASS** |
| V4 | Sportsbook identity | **PASS** |
| V5 | Price integrity | **PASS** |
| V6 | Missingness | **PASS** |
| V7 | Settlement | **PASS** |
| V8 | Commercial rights | **PENDING_MANUAL** |
| V9 | Cost | **PASS** |
| V10 | Reproducibility | **PASS** |

### V1 — Historical availability [PASS]

8 sampled games; receiving-yards props observed for seasons [2025, 2026]

### V2 — Timestamp integrity [PASS]

24 responses; snapshot lag min/median/max = 45/45/45s (positive = snapshot BEFORE decision ts)

### V3 — Market identification [PASS]

24 responses checked for player/team/game/line/over-under identification + event-ID map provenance (8 map entries)

### V4 — Sportsbook identity [PASS]

bookmaker key/title stability across observation times; 24 book-game slots

### V5 — Price integrity [PASS]

1104 outcome prices validated; 552 two-sided markets; vig mean 4.73pp (min 4.71, max 4.76)

### V6 — Missingness [PASS]

72 game x time x book ledger rows (missingness_ledger.csv); 24 pulled/absent player-line entries (pulled_lines.csv); 0 discovery misses

### V7 — Settlement [PASS]

64 player-games settled from independent stats (over 32 / under 24 / push 8); 0 stats players unpriced (informational)

### V8 — Commercial rights [PENDING_MANUAL]

written permission for storage, analysis, and display NOT YET ATTACHED

### V9 — Cost [PASS]

26 metered requests; measured 240 credits total (baseline_sports=0, historical_event_odds=240); budget cap 600; 0 quote actual-vs-modeled mismatches

### V10 — Reproducibility [PASS]

53 manifest entries verified by SHA-256; 52 raw responses with redacted-URL metadata

## 5. Settlement reconciliation

- outcomes: over 32 / under 24 / push 8
- row-level reconciliation: `selftest_out/evidence_clean/settlement_reconciliation.csv`

## 6. Canonical-schema preview (decision_2d integration)

- rows: 552; schema validation: PASS (on synthetic=False copy); synthetic-refusal path: REFUSED (fail-closed intact)

## 7. Recommendation

**BLOCKED (pending V8)** — automated checks pass, but written commercial permission must be attached before any full acquisition. Attach the vendor's written permission to ATTACHMENT_V8_COMMERCIAL_RIGHTS.md and re-run the verifier.

## 8. Provenance

- raw manifest: `selftest_out/raw_clean/manifest.json` (sha256 df050e59eb49c118…)
- sample manifest: precommitted selection, schedule metadata only
- event-ID map: `selftest_out/raw_clean/event_id_map.json` (discovery source + timestamp per entry; verified by V3)
- evidence JSONs: `selftest_out/evidence_clean` (deterministic; no wall-clock content)
- **SYNTHETIC HARNESS TEST**: zero vendor requests, zero credits consumed; this report validates CODE, not the vendor.

