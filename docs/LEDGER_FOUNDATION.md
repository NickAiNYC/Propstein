# Ledger foundation

Postgres is the source of truth for research passports, structural slip audits, and the prospective signal ledger. The per-passport SHA-256 chain is tamper-evident, not tamper-proof: a superuser can disable triggers. The `propstein_app` role has no `UPDATE`, `DELETE`, or `TRUNCATE` on ledger tables, and triggers reject those statements for every role.

`DATABASE_URL` is the app role. `LEDGER_ADMIN_URL` is the migration role. Neither password is stored in the repository.

## Schema

| Table | Role |
|---|---|
| `users` | Pseudonymous id only |
| `evidence_passports` | One chain root per research reference, slip, or signal |
| `research_references` | User cohort. Model fields are server-resolved |
| `prospective_signals` | `prospective_full_board` or `historical_backtest` only |
| `historical_evidence_gaps` | Rows that lack `event_id` or provenance. Both event columns are forced null |
| `intended_quotes` | Quote committed with a forecast. One per signal |
| `placements` | Achieved line and price, and only with a `ticket_ref` |
| `closing_references` | `MATCHED` or `UNMATCHED` plus a reason code and `source_id` |
| `settlements` | Grades a signal. Empty until a later grader writes a new row |
| `withdrawals` | New row. Does not rewrite the signal |
| `slip_audits`, `slip_legs`, `audit_findings` | Structural audit. Every leg requires `event_id` and `event_start_at` |
| `rule_registry`, `rule_registrations` | Catalog plus the hashed pre-registration. `enabled` is not a column |
| `ledger_events` | Append-only `prev_hash` / `integrity_hash` chain |
| `attestations` | `PENDING`, `CONFIRMED`, or `FAILED`. Created empty |
| `gate_flag_events` | `model_validation` and `paid_tier_clv` only. No combined flag |

`event_id` and `event_start_at` are `NOT NULL` on signals, research references, slip legs, quotes, placements, closes, settlements, and withdrawals. Updates are rejected, so those fields cannot be backfilled.

Population views, counted separately and only for `prospective_full_board`:

- `committed_forecasts`
- `graded_forecasts`
- `placements`
- `closing_price_matches` and `closing_price_matches_committed` (the same committed-record count)
- `closing_price_matches_placements`
- `missing_closing_quotes`
- `withdrawals`

User research, user slips, `historical_backtest`, and gap rows are absent from these views.

## Prices

Three records stay separate. A placement is not inferred from an intended quote or from a board observation.

Reported unit is probability percentage points (`(probability difference) * 100`) for the exact selected outcome. Both prices are the multiplicative de-vig from `src.model.devig_two_way`.

- `intended_clv = close_devig_prob - intended_entry_implied_prob`
- `placement_clv = close_devig_prob - achieved_entry_implied_prob`
- `execution_slippage = achieved_implied - intended_implied` (positive means a worse price)
- `model_vs_close = model_prob - close_devig_prob` (diagnostic only; the key is never a CLV label)

`placement_clv` is null when there is no placement. A close matches only when event, market, selection, line, and settlement rules all agree. A different line is `LINE_CHANGED` and the odds are not compared. `docs/EDGE_GATE.md` is unchanged, including its own CLV sign and the N=600 confirmatory rule. N=300 remains that document's descriptive checkpoint. The two gate flags are independent and there is no `QUALIFIED` flag. Both are closed on the current published holdout and the absence of a confirmatory pass file.

## Research references

`POST /api/v1/research-references` writes a passport and a research reference in one transaction, or it writes nothing.

Model version, coverage, probability, uncertainty, and `input_snapshot_hash` are taken from `snapshots/snapshots_*.jsonl`. The client cannot submit them. The stored version string is the snapshot's own `model.version` (`negbin-gamma-v3.2` on the current journals). Probability at the requested line is computed from that snapshot's stored distribution parameters with `src.freeze_slate.compute_rec_probs` / `compute_yards_probs`. Frozen snapshots do not contain an uncertainty interval, so the interval is stored and returned as null.

If no hash-valid snapshot exists at or before `observed_at`, the response is `409` with `reason=NO_SERVER_SNAPSHOT` and `saved=false`. Nothing is inserted. Coverage on a saved row is `uncalibrated` because the published week-1 Brier skill is negative (`viewer/holdout_eval_2026_w1.json`). The response omits `model_probability` while coverage is uncalibrated.

`observed_at` must be timezone-aware and not in the future. `event_id` and `event_start_at` are required on the request. `game_id` and `kickoff_at` are not copied into those columns. Context uses `scripts/autopilot.game_context_has_capture_times` and `src.features.assert_context_known_at_cutoff`. A failure marks `UNVERIFIED_CONTEXT` and still saves the reference when a snapshot exists.

`POST /api/v1/slip-audits` evaluates confirmed legs only. Unconfirmed legs are rejected and not stored. Overlap findings are same player, same team, same `event_id`, and duplicate selections. There is no shared-assumption finding. The active registration must match the SHA-256 of `src/ledger/preregistration/slip_audit_structural_v1.json`. `registered_at` is the database clock at insert. A later registration is a new row; older audits keep their original id.

## Historical records that lack required evidence

These files were not rewritten. Import stores a gap row with `event_id` and `event_start_at` null and leaves the original payload untouched. `kickoff_at`, `trigger_time`, and `close_time` are not promoted into the event columns.

| Source | Records | Missing |
|---|---:|---|
| `snapshots/full_board_2026_w8_early_1300.jsonl` | 472 | `event_id`, `event_start_at` on every row. `game_id` and `kickoff_at` are on the frozen row |
| `snapshots/snapshots_2026_w1.jsonl` | 862 | `event_id`, `event_start_at` |
| `snapshots/snapshots_2026_w7.jsonl` | 1118 | `event_id`, `event_start_at` |
| `snapshots/snapshots_2026_w8.jsonl` | 472 | `event_id`, `event_start_at` |
| `viewer/clv_report_2026_w7.json` ledger | 37 | `event_id`, `event_start_at` |
| `viewer/clv_audit_report.json` records | 8 | `event_id`, `event_start_at` |
| `public/clv_audit_report.json` records | 8 | `event_id`, `event_start_at` |
| `viewer/ufc_ledger.json` cards | 1 | `event_start_at`. `event_id` is present. `decisions` is empty |

`src/ledger/export.py` writes a JSONL mirror of ledger events. Merkle roots and OpenTimestamps anchoring are not implemented (`anchoring: not_implemented`).
