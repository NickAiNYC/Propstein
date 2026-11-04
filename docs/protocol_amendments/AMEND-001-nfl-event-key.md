# AMEND-001 — NFL ledger event key

Status: **protocol amendment.** Effective **2026-11-01T00:00:00Z**. Prospective only.

This amendment does not edit `docs/EDGE_GATE.md`. The confirmatory size stays N = 600 per sport, the descriptive checkpoint stays N = 300, and the clustering procedure stays the game-clustered bootstrap with seed `20261024`. Cross-sport pooling stays forbidden. Nothing here changes a registered parameter in that document.

## What changes

For NFL records admitted under this amendment:

| Ledger column | Source |
|---|---|
| `event_id` | The nflverse `game_id` captured on the prospective journal row. This is the game-clustering key. |
| `event_start_at` | The `kickoff_at` captured on that same row. |
| `provider_event_id` | The odds-provider event id **only when that field is present on the source row**. The column is nullable. It is never the clustering key and is never copied into `event_id`. |
| `amendment_id` | `AMEND-001` |

`game_id` on the journal row is the nflverse game id already used to cluster games. The mapping copies that captured value into `event_id`. It does not look up a game, a kickoff, or a provider id from any other file.

## Scope

The mapping applies only to prospective journal rows (`schema = propstein.prospective_board.v1`) whose decision timestamp `captured_at` is timezone-aware and **on or after** 2026-11-01T00:00:00Z.

The following stay outside this amendment. They are not imported by it, and their missing fields are not filled:

- Rows whose `captured_at` is before 2026-11-01T00:00:00Z
- Historical paper trading and backtests
- The Week 7 trigger cohort: `viewer/clv_report_2026_w7.json` (37 ledger rows)
- Freeze snapshot logs that are not prospective journal rows (`snapshots/snapshots_*.jsonl`)

Source files are not rewritten. A row that lacks `game_id` or `kickoff_at`, whose `captured_at` or `kickoff_at` is naive or unusable, whose decision timestamp is at or after kickoff, or whose source hash is missing or does not match, is not admitted. Those in-scope failures are recorded in `historical_evidence_gaps` with `event_id` and `event_start_at` left null. No field is inferred to complete them.

The generic importer does not apply this mapping. Absence of a literal `event_id` on a historical file remains a gap unless this amendment's importer admits the row.

## Registry

`AMEND-001` is registered in `protocol_amendments` and catalogued in `rule_registry` (family `protocol`). The slip-audit pre-registration is unchanged. This amendment does not enable a slip rule and does not open a commercial flag.

## Forward only

A later change to this key is a new amendment. It does not revise rows already admitted under AMEND-001.
