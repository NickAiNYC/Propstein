# Feature cutoff gate

## What is blocked

New NFL receiving-model fits, backtests, and weekly projections call `src.features.attach_game_context()`. That function now raises `UnverifiedGameContextError` unless every pricing row has a timezone-aware `pricing_cutoff_timestamp` and the joined game has timezone-aware `spread_observed_at`, `total_observed_at`, and `weather_observed_at` values no later than that cutoff. The nflverse `games.csv` feed used by this repo has none of those observation fields, so new runs stop before spread, total, roof, temperature, or wind can enter a model feature.

The existing frozen artifacts are unchanged. They remain historical research outputs, not proof of a pregame-available feature set or a current betting edge. Do not bypass this guard with fabricated timestamps or a blanket development flag.

## Why the guard is necessary

`games.csv` records final game context, including closing market lines and weather, without the time each value became known. A historical row can therefore use information captured after its supposed pricing time. The old position fallback also computed medians across the full panel; it now uses strictly earlier weeks. Neither change refits or relabels a frozen model.

## Data needed to unblock a run

For every game row used by training and pricing, provide the source values and independent capture timestamps for spread, total, and weather. For every player pricing row, provide the intended pricing cutoff. The three source timestamps must precede or equal that row's cutoff, with explicit timezone offsets. A missing game, missing timestamp, naive timestamp, malformed timestamp, or value observed after cutoff fails the run.

Before restoring scheduled model generation, verify source ownership and licensing, validate the timestamped contract at ingestion, add a prospective capture test, and fit a new model version under a written migration plan. Do not overwrite the frozen model artifacts. The daily autopilot now skips the model and subscriber picks board when provenance is missing, labels any cached active slate as research-only and locked, and continues schedule, injury, and independent feed refreshes. For a new week with no slate file, it publishes an empty slate so the real schedule can still appear. It never copies an old projection into that week.

## Verification

Run the focused gate tests from the repository root:

```bash
PYTHONPATH=. python -m pytest tests/test_feature_cutoff.py -q
```

The same file is part of the blocking `foundation-freeze` CI job. A direct `src/week1.py` model run raises `UnverifiedGameContextError` against the current nflverse game feed. `scripts/autopilot.py` detects the missing capture fields before that run, publishes a paused board, and keeps the independent updates moving.
