# Decision 2D-V Trial Verification Report — DECISION_2DV_TRIAL_v1

- **Data label:** `SYNTHETIC-HARNESS-TEST`  — SYNTHETIC HARNESS TEST, not vendor evidence
- **Sample:** 8 games (4 x 2025, 4 x 2026 w1-7)
- **Overall verdict:** **FAIL** — critical failure(s) present — full acquisition BLOCKED

## 1. Verified sample

| game | season | week | books (max) | players priced (max) |
| --- | --- | --- | --- | --- |
| SYN25_G01 | 2025 | 6 | 3 | 8 |
| SYN25_G02 | 2025 | 9 | 3 | 8 |
| SYN25_G03 | 2025 | 14 | 3 | 8 |
| SYN25_G04 | 2025 | 19 | 3 | 8 |
| SYN26_G05 | 2026 | 1 | 3 | 9 |
| SYN26_G06 | 2026 | 3 | 3 | 8 |
| SYN26_G07 | 2026 | 5 | 3 | 8 |
| SYN26_G08 | 2026 | 7 | 3 | 8 |

## 2. Coverage and missingness

- ledger rows (game x time x book): **75** (5 absent-book slots recorded explicitly)
- pulled/absent player-lines: **49** → `selftest_out/evidence_faulted/pulled_lines.csv`
- discovery misses: 0

## 3. Actual API consumption

- metered requests: **26**; measured total **245** credits vs cap 600
- by request kind: baseline_sports=0, historical_event_odds=245
- quote pulls: modeled **240**; actual-vs-modeled mismatches: 1
- consumption-unestablished rows: 1; header inconsistencies: 0

## 4. Check verdicts V1-V10

| check | title | status |
| --- | --- | --- |
| V1 | Historical availability | **PASS** |
| V2 | Timestamp integrity | **FAIL** |
| V3 | Market identification | **FAIL** |
| V4 | Sportsbook identity | **FAIL** |
| V5 | Price integrity | **FAIL** |
| V6 | Missingness | **PASS** |
| V7 | Settlement | **FAIL** |
| V8 | Commercial rights | **PENDING_MANUAL** |
| V9 | Cost | **FAIL** |
| V10 | Reproducibility | **PASS** |

### V1 — Historical availability [PASS]

8 sampled games; receiving-yards props observed for seasons [2025, 2026]

### V2 — Timestamp integrity [FAIL]

24 responses; snapshot lag min/median/max = -90/45/45s (positive = snapshot BEFORE decision ts)

Violations / problems:

- SYN26_G07@T-60m: snapshot exceeds decision ts by 90s (snapshot 2026-10-11T16:01:30+00:00, decision 2026-10-11T16:00:00+00:00)

### V3 — Market identification [FAIL]

24 responses checked for player/team/game/line/over-under identification + event-ID map provenance (8 map entries)

Violations / problems:

- SYN25_G02: discovery_timestamp_utc missing or invalid (None) (owner requirement: record the discovery timestamp)
- SYN25_G01@T-180m:synbook_a player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]
- SYN25_G01@T-180m:synbook_a player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]
- SYN25_G01@T-180m:synbook_b player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]
- SYN25_G01@T-180m:synbook_b player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]
- SYN25_G01@T-180m:synbook_c player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]
- SYN25_G01@T-180m:synbook_c player 'SYN WR A03' line 9999.0 outside plausible range [5.0, 250.0]

### V4 — Sportsbook identity [FAIL]

bookmaker key/title stability across observation times; 25 book-game slots

Violations / problems:

- SYN25_G02: book title 'Synthetic Book B' maps to keys ['synbook_b', 'synbook_b2']

### V5 — Price integrity [FAIL]

1086 outcome prices validated; 543 two-sided markets; vig mean 4.73pp (min 4.71, max 4.76)

Violations / problems:

- SYN25_G03@T-180m:synbook_a:SYN WR C05 Over decimal 1.95 != american -110 -> 1.9091
- SYN25_G03@T-180m:synbook_b:SYN WR C05 Over decimal 1.95 != american -110 -> 1.9091
- SYN25_G03@T-180m:synbook_c:SYN WR C05 Over decimal 1.95 != american -110 -> 1.9091

### V6 — Missingness [PASS]

75 game x time x book ledger rows (missingness_ledger.csv); 49 pulled/absent player-line entries (pulled_lines.csv); 0 discovery misses

### V7 — Settlement [FAIL]

64 player-games settled from independent stats (over 32 / under 24 / push 8); 0 stats players unpriced (informational)

Violations / problems:

- SYN25_G03: SYN WR C05 vendor settlement 'over' contradicts independent stats (under; line 50.5, yards 35.0)
- SYN26_G05: priced player 'SYN WR Z99' not found in independent stats (identification failure)

### V8 — Commercial rights [PENDING_MANUAL]

written permission for storage, analysis, and display NOT YET ATTACHED

### V9 — Cost [FAIL]

26 metered requests; measured 245 credits total (baseline_sports=0, historical_event_odds=245); budget cap 600; 1 quote actual-vs-modeled mismatches

Violations / problems:

- 1 response(s) with consumption UNESTABLISHED (usage headers missing/unreliable)
- 1 ledger row(s) with null actual_credits outside tolerated open/baseline rows
- 1 quote request(s) where actual credits != modeled (vendor headers disagree with documented rule)
- run aborted on a consumption failure: historical_event_odds/SYN26_G08@T-15m: x-requests-used missing on non-retryable response (status 200) — consumption cannot be established
- credit mismatch: {'game_id': 'SYN25_G04', 'offset': 'T-15m', 'modeled': 10, 'actual': 25}

### V10 — Reproducibility [PASS]

53 manifest entries verified by SHA-256; 52 raw responses with redacted-URL metadata

## 5. Settlement reconciliation

- outcomes: over 32 / under 24 / push 8
- row-level reconciliation: `selftest_out/evidence_faulted/settlement_reconciliation.csv`

## 6. Canonical-schema preview (decision_2d integration)

- rows: 543; schema validation: PASS (on synthetic=False copy); synthetic-refusal path: REFUSED (fail-closed intact)

## 7. Recommendation

**FAIL** — critical failures above block the full acquisition until resolved (Decision 2D acceptance rule: any critical failure is disqualifying).

## 8. Provenance

- raw manifest: `selftest_out/raw_faulted/manifest.json` (sha256 e0288ce4e781e5d2…)
- sample manifest: precommitted selection, schedule metadata only
- event-ID map: `selftest_out/raw_faulted/event_id_map.json` (discovery source + timestamp per entry; verified by V3)
- evidence JSONs: `selftest_out/evidence_faulted` (deterministic; no wall-clock content)
- **SYNTHETIC HARNESS TEST**: zero vendor requests, zero credits consumed; this report validates CODE, not the vendor.

