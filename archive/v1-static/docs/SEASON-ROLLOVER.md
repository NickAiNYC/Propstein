# Season Rollover Runbook (2026 → 2027)

> Written 2026-11-02 after a full code audit for 2027 readiness. Purpose:
> rolling to the 2027 NFL season (and every season after) must be a **data
> and config exercise, not a code change**. This file is the checklist that
> makes that true — and the record of what was already fixed so it is.

## Design rule

Season/year values live in **data files and registry entries**, never in
code branches. Any code that must touch a season pattern is
season-**agnostic** (regexes capture the year, resolvers glob the files).

## Already season-agnostic (verified 2026-11-02 — no action needed)

| Surface | Why it rolls over cleanly |
|---|---|
| Freeze pipelines (`scripts/freeze_sunday_early.py`, `scripts/resolve_freeze_target.py`) | Glob `viewer/games_*_w*.json`, parse season/week from filenames; zero hardcoded weeks |
| `freeze_tnf.yml` / `freeze_sunday_early.yml` / `freeze_ufc.yml` workflows | Season/week come from the resolvers or dispatch inputs; schedules are weekday-cron, not date-pinned |
| Weekly model CLI (`src/week1.py`) | `--season` / `--week` arguments |
| Autopilot schedule resolution | Loads `data/games.csv` (nflverse); season/week derived from kickoffs |
| Python dependency lock (`requirements.lock`) | No season coupling |
| Viewer build-hash week bump (`scripts/autopilot.py`) | **Fixed 2026-11-02**: `BUILD_HASH_RE` was pinned to `2026` literally — on a 2027 page the week bump would silently no-op. Now the year is captured and preserved; selftest pins both a 2026 and a 2027 case |

## The rollover checklist (first week of the 2027 season)

Ordered; each item names the file(s) and the verification.

1. **Pull the 2027 schedule.** `python scripts/autopilot.py --plan` (or the
   daily_update workflow) refreshes `data/games.csv` from nflverse; the new
   season's rows appear automatically. Verify: `selftest` passes and the
   resolver reports `season=2027`.
2. **Run the first 2027 slate.**
   `python src/week1.py --season 2027 --week 1` — generates
   `viewer/slate_2027_w1.json`, `viewer/current_picks_2027_w1.json`,
   `viewer/games_2027_w1.json`, `viewer/injuries_2027_w1.json`,
   `viewer/snapshots_2027_w1.json` (same schema as the 2026 files; autopilot
   selftest pins the schema).
3. **Register the slate in the NFL adapter** (`viewer/js/sports/nfl.js`):
   add the `2027_wN` entry to `slates` (season, week, shortLabel, state,
   file names) and flip the previous season's entries to
   `historical: true` **only after their settlement/audit is complete** —
   2026 files are the evidence record and are never deleted (see
   docs/TECH-DEBT.md "Evidence record over marketing").
4. **NBA / UFC adapters** (`viewer/js/sports/nba.js`, `ufc.js`): add the new
   date-keyed slate entries as nights/events go live. NBA entries carry a
   one-time epoch activation gate (`Date.now() > <ms>`) per slate — copy the
   pattern from the Oct 2026 entries.
5. **Build-hash + cache triple.** The week segment rolls automatically
   (season-preserving bump). The `?v=` asset busters and the SW
   `CACHE_NAME` bump only when viewer assets themselves change — follow the
   cache-bump convention in docs/TECH-DEBT.md (coherent triple, same PR).
6. **Regenerate public pages.** `scripts/build_public_pages.py` for the
   player-market pages / performance pages covering the new season's data.
7. **Verify end-to-end.** All of:
   - `npm run check:production` (node gate + parity goldens)
   - `PYTHONPATH=. pytest test/ tests/` (incl. dependency-lock tests)
   - `python scripts/autopilot.py --selftest`
   - Freeze resolver dry-run: `python scripts/resolve_freeze_target.py`
     prints the 2027 season/week (with `EVENT_NAME=workflow_dispatch` and
     empty inputs it resolves the next kickoff).
   - Viewer slate switcher shows the 2027 entries; feed health honest.

## Known non-goals / acceptance limits

- Historical 2026 fixtures (w1/w7/w8) stay in the repo as audit artifacts —
  size is bounded and they pin the parity goldens.
- `viewer/js/sports/nfl.js` `sampleNote` fallback string `row.season ||
  '2026'` is display-only and exercised only for legacy rows; leave it
  until a 2027 row without `season` actually renders wrong.
- The research corpora under `research/*/data/` are gitignored
  (regenerable via each project's `00_download_data.py`) — a new season
  adds new parquet files locally, never to the repo.
