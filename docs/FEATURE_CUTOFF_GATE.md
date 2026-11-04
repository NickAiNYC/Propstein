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

The same file is part of the blocking `foundation-freeze` CI job. A direct `src/week1.py` model run raises `UnverifiedGameContextError` against the current nflverse game feed. `scripts/autopilot.py` detects missing or empty capture values on the active week's unstarted games before that run, publishes a paused board, and keeps the independent updates moving. `scripts/check_game_context_provenance.py` exits non-zero with `PROVENANCE_ALERT` when that same window is not ready. That check is a blocking CI job and the last step of the daily autopilot workflow.

## ESPN capture rules

`scripts/ingest_espn_game_context.py` is the only writer of these timestamps. It does not backfill 2026 weeks 1–8.

* Spread and total timestamps are the scoreboard fetch. ESPN's home spread is negative when home is favored; nflverse `spread_line` is the negation of that number (positive when home is favored). The mapping is pinned to the saved week 9 scoreboard.
* Weather has its own timestamp. Outdoor and open-roof games stamp `weather_observed_at` only when the summary `gameInfo` includes both temperature and wind (ESPN's wind figure is the `gust` field). Dome and closed roofs stamp the scoreboard time with wind 0 and a blank temperature: the observation is the enclosed roof, not the outdoor forecast and not a default 72°F. SoFi stays `dome` (nflverse fixed roof). Lucas Oil, AT&T, NRG, Mercedes-Benz Stadium, State Farm, and Santiago Bernabéu are retractable (`closed` when ESPN says indoor, otherwise `open`).
* Kickoff in `games.csv` stays Eastern `HH:MM`, matching nflverse. Only ESPN state `pre` with a kickoff still ahead of the fetch is captured.
* A rerun keeps the latest capture that is still at or before kickoff. A later line, including one taken after kickoff, does not replace it. Journal ids that are not already on the nflverse schedule are not inserted. That is why the old `2026_09_LAR_WAS` rows stay in the journal and are not applied: nflverse's id for that game is `2026_09_LA_WAS`.
* HTTP errors, unreadable JSON, an unparsed pregame event, or a payload that is not the full scheduled week write neither the journal nor `games.csv`.

## Where the audit trail lives

`data/games.csv` stays gitignored. It is the nflverse download, and a refresh would wipe provenance columns. The durable copies are the committed append-only journal `data/game_context_captures.jsonl` and the raw JSON payloads in `data/raw_espn_captures/` (scoreboard bodies, plus summary `gameInfo` slices for outdoor weather). `.gitignore` keeps those two paths and ignores other `*.jsonl` logs. Autopilot reapplies the journal after every nflverse refresh. These files are not inputs to the frozen model hashes. Old journal lines are kept; consumers must use the pre-cutoff selector, because early rows stamped weather with null temperature and wind and inverted at least one home favorite.

The daily report is `data/game_context_provenance_report.json`: games ingested in the latest batch, missing timestamps, captures older than 36 hours, and failed fetches. Stale-but-valid lines stay usable. Missing required context at pricing time fails the check.
