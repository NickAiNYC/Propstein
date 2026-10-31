#!/usr/bin/env python3
"""autopilot.py — PropWire daily data autopilot (NFL week rollover + feed refresh).

WHAT THIS SOLVES
  The board used to go stale by hand: someone had to notice "it is week 8",
  run the model, generate the slate files, wire the new week into the viewer
  and commit. This script does all of it, idempotently, so a scheduled job
  (GitHub Actions cron -> commit -> Vercel auto-deploy) keeps the board on
  the current NFL week and fresh data without human intervention.

PIPELINE (run mode, in order)
  1. Refresh nflverse feeds in data/ (free, ToS-clean; same sources as
     src/fetch_data.py): games.csv + current-season stats/rosters/injuries
     parquets. Historical parquets are only downloaded when missing.
  2. Resolve the ACTIVE NFL week from the real schedule: the week owning the
     next kickoff at-or-after (now - 4h). The 4h grace keeps the board on the
     in-progress week through Monday night, then rolls to the next week.
  3. Run src/week1.py --season S --week W (retrains on all data through W-1,
     regenerates fair lines/projections). With ODDS_API_KEY set in the env,
     add --odds so scored picks are generated too; without it the run stays
     in the documented honest fallback (fair lines only).
  4. Generate the viewer files for the week, matching the committed w7
     schemas exactly: games_/slate_/injuries_/snapshots_/current_picks_wN.
  5. Regenerate viewer/feeds/slate-index.json — the manifest the viewer
     boots from to discover new weeks/nights WITHOUT code edits (NFL weeks
     + NBA date slates; NBA entries appear automatically once
     BALLDONTLIE_API_KEY is configured and scripts/fetch_nba.py runs).
  6. Refresh viewer/feeds/player_photos.json — the ESPN headshot map for
     every player on the current slates (incremental: only names still
     unresolved hit the search API; every URL is verified before it ships;
     fail-open, a cosmetic layer must never abort the data pipeline).
  7. Bump the build-hash WEEK segment in the terminal pages
     (2026-w7-v15 -> 2026-w8-v15). UI version counters (asset busters, SW
     cache name) are NOT touched by automation — those are manual releases.

FAIL-CLOSED RULES
  * No network and no cached feeds -> exit non-zero, write nothing.
  * week1.py failure -> abort; the workflow surfaces the failure visibly.
  * Missing provider keys never fabricate data: odds stay in their current
    verified/manual state; NBA slates only come from real balldontlie files.
  * Every generated file is provenance-stamped (_fixture flags, generated_at).

USAGE
  python3 scripts/autopilot.py --plan            # print what would happen
  python3 scripts/autopilot.py --run             # execute the pipeline
  python3 scripts/autopilot.py --run --skip-model  # manifest/build-hash only
  python3 scripts/autopilot.py --selftest        # offline pure-function checks

EXIT CODES: 0 ok (including idempotent no-op) · 1 pipeline error ·
            2 environment error (missing data, bad state) · 6 selftest failure

Env overrides: PROPWIRE_NOW (ISO timestamp, mirrors FREEZE_NOW) for
deterministic tests; PROPWIRE_SKIP_FETCH=1 to use cached feeds only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
VIEWER = ROOT / "viewer"
DATA = ROOT / "data"
FEEDS = VIEWER / "feeds"

ET = ZoneInfo("America/New_York")
NFLVERSE_BASE = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"

BUILD_HASH_RE = re.compile(r"2026-w(\d+)-v(\d+)")
GAMES_FILE_RE = re.compile(r"games_(\d{4})_w(\d+)\.json$")
NBA_GAMES_FILE_RE = re.compile(r"nba_games_(\d{4}-\d{2}-\d{2})\.json$")

LIVE_GRACE_HOURS = 4.0  # a kickoff this recent may still be in progress


# ---------------------------------------------------------------------------
# Schedule resolution
# ---------------------------------------------------------------------------

def load_schedule(now: datetime) -> "tuple[int, list[dict]]":
    """Load data/games.csv and return (season, active-week games).

    The active week owns the next kickoff at-or-after now - grace. Keeps the
    board on the live week through Monday night, rolls Tuesday morning.
    """
    import csv

    path = DATA / "games.csv"
    if not path.exists():
        raise SystemExit("data/games.csv missing - run with network or fetch feeds first")
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                row["season_i"] = int(row["season"])
                row["week_i"] = int(row["week"])
                row["kickoff"] = datetime.strptime(
                    f"{row['gameday']} {row['gametime']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=ET)
            except (ValueError, KeyError, TypeError):
                continue
            rows.append(row)
    if not rows:
        raise SystemExit("data/games.csv parsed to zero games")

    cutoff = now - timedelta(hours=LIVE_GRACE_HOURS)
    upcoming = [r for r in rows if r["kickoff"] >= cutoff]
    if not upcoming:
        raise SystemExit("no upcoming games in schedule - season over or stale feeds")
    # keep only rows of the same season as the next kickoff
    anchor = min(upcoming, key=lambda r: r["kickoff"])
    season = anchor["season_i"]
    week = anchor["week_i"]
    games = sorted(
        (r for r in rows if r["season_i"] == season and r["week_i"] == week),
        key=lambda r: (r["kickoff"], r["game_id"]),
    )
    return season, games


def week_span_label(games: list[dict]) -> str:
    """'Oct 29-Nov 2' style ET span for the slate state label."""
    days = sorted({g["kickoff"].date() for g in games})
    first, last = days[0], days[-1]

    def fmt(d) -> str:
        return f"{d.strftime('%b')} {d.day}"

    if first == last:
        return fmt(first)
    if first.month == last.month:
        return f"{first.strftime('%b')} {first.day}-{last.day}"
    return f"{fmt(first)}-{fmt(last)}"


# ---------------------------------------------------------------------------
# Feed refresh (nflverse — the documented ToS-clean source, see fetch_data.py)
# ---------------------------------------------------------------------------

def download(url: str, dest: Path) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
        return True
    except Exception as exc:  # network down, 404, disk — fail soft per file
        print(f"  [warn] fetch failed {dest.name}: {exc}", file=sys.stderr)
        if Path(str(tmp)).exists():
            try:
                Path(str(tmp)).unlink()
            except OSError:
                pass
        return False


def refresh_feeds(season: int) -> None:
    """Always refresh current-season feeds + games.csv; history only if absent."""
    if os.environ.get("PROPWIRE_SKIP_FETCH") == "1":
        print("[autopilot] PROPWIRE_SKIP_FETCH=1 - using cached feeds only")
        return
    jobs: list[tuple[str, Path]] = [(NFLVERSE_BASE, DATA / "games.csv")]
    jobs.append((f"{RELEASES}/stats_player/stats_player_week_{season}.parquet",
                 DATA / f"stats_{season}.parquet"))
    jobs.append((f"{RELEASES}/weekly_rosters/roster_weekly_{season}.parquet",
                 DATA / f"roster_{season}.parquet"))
    jobs.append((f"{RELEASES}/injuries/injuries_{season}.parquet",
                 DATA / f"injuries_{season}.parquet"))
    for prior in (season - 1, season - 2):
        for kind, remote, local in (
            ("stats", f"stats_player/stats_player_week_{prior}.parquet", f"stats_{prior}.parquet"),
            ("roster", f"weekly_rosters/roster_weekly_{prior}.parquet", f"roster_{prior}.parquet"),
        ):
            if not (DATA / local).exists():
                jobs.append((f"{RELEASES}/{remote}", DATA / local))
    # training history back to 2016 (stats only) when absent
    for year in range(2016, season - 2):
        dest = DATA / f"stats_{year}.parquet"
        if not dest.exists():
            jobs.append((f"{RELEASES}/stats_player/stats_player_week_{year}.parquet", dest))
    ok = 0
    for url, dest in jobs:
        ok += 1 if download(url, dest) else 0
    print(f"[autopilot] feeds refreshed: {ok}/{len(jobs)} ok")
    if not (DATA / "games.csv").exists():
        raise SystemExit("games.csv unavailable and no cached copy - aborting (fail closed)")


# ---------------------------------------------------------------------------
# Viewer file generation (schemas match the committed 2026_w7 files exactly)
# ---------------------------------------------------------------------------

def games_viewer_rows(games: list[dict]) -> list[dict]:
    return [
        {
            "game_id": g["game_id"],
            "gameday": g["gameday"],
            "gametime": g["gametime"],
            "away_team": g["away_team"],
            "home_team": g["home_team"],
            "spread_line": _num_or_none(g.get("spread_line")),
            "total_line": _num_or_none(g.get("total_line")),
            "roof": g.get("roof") or None,
            "wind": _num_or_none(g.get("wind")),
        }
        for g in games
    ]


def _num_or_none(value):
    try:
        return float(value) if value not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def write_games(season: int, week: int, games: list[dict]) -> Path:
    dest = VIEWER / f"games_{season}_w{week}.json"
    dest.write_text(json.dumps(games_viewer_rows(games), indent=2) + "\n", encoding="utf-8")
    return dest


def write_injuries(season: int, week: int, games: list[dict]) -> Path:
    """Generate the injuries viewer file straight from the nflverse parquet.

    Provenance-honest: only rows the feed actually contains; when the week's
    report has not been published yet the file ships an explicit empty list
    (the daily run fills it the moment nflverse publishes).
    """
    dest = VIEWER / f"injuries_{season}_w{week}.json"
    injuries: list[dict] = []
    source = "none"
    parquet = DATA / f"injuries_{season}.parquet"
    kickoff_by_team: dict[str, dict] = {}
    for g in games:
        kickoff_by_team[g["home_team"]] = g
        kickoff_by_team[g["away_team"]] = g
    try:
        import pandas as pd

        frame = pd.read_parquet(parquet)
        rows = frame[(frame.season == season) & (frame.week == week)]
        source = f"nflverse injuries_{season}.parquet"
        def _s(v) -> str:
            # parquet nulls arrive as float NaN; treat any non-str as empty
            return v.strip() if isinstance(v, str) else ""

        for r in rows.itertuples(index=False):
            gid = getattr(r, "gsis_id", None)
            team = getattr(r, "team", None)
            game = kickoff_by_team.get(team, {})
            report = _s(getattr(r, "report_status", ""))
            injuries.append({
                "player_id": gid,
                "player_name": getattr(r, "full_name", None),
                "team": team,
                "opponent": (game.get("home_team") if game.get("away_team") == team
                             else game.get("away_team")) or None,
                "game_id": game.get("game_id"),
                "position": getattr(r, "position", None),
                "injury_type": _s(getattr(r, "report_primary_injury", "")) or "Injury",
                "report_status": report.upper() or "PRACTICE ONLY",
                "practice_status": _s(getattr(r, "practice_status", "")) or "Practice status unavailable",
            })
    except Exception as exc:
        print(f"  [warn] injuries parquet unavailable ({exc}) - writing empty report", file=sys.stderr)
        source = "unavailable"
    now = datetime.now(timezone.utc)
    payload = {
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slate_week": week,
        "season": season,
        "total_active_injuries": sum(i["report_status"] != "PRACTICE ONLY" for i in injuries),
        "total_practice_entries": sum(i["report_status"] == "PRACTICE ONLY" for i in injuries),
        "source": source,
        "impacted_beneficiaries": {},
        "injuries": injuries,
    }
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def write_snapshots_stub(season: int, week: int) -> Path:
    """Empty snapshot shelf the freeze workflow (freeze_tnf.yml) fills pre-kickoff."""
    dest = VIEWER / f"snapshots_{season}_w{week}.json"
    if not dest.exists():
        dest.write_text("[]\n", encoding="utf-8")
    return dest


def run_model(season: int, week: int) -> bool:
    """Run src/week1.py for the week. Returns True on success."""
    cmd = [sys.executable, "week1.py", "--season", str(season), "--week", str(week)]
    if os.environ.get("ODDS_API_KEY"):
        cmd.append("--odds")
    print(f"[autopilot] model run: {' '.join(cmd)} (cwd=src)")
    result = subprocess.run(cmd, cwd=SRC, capture_output=True, text=True, timeout=1800)
    tail = (result.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print(f"  [week1] {line}")
    if result.returncode != 0:
        print((result.stderr or result.stdout or "")[-2000:], file=sys.stderr)
        return False
    return sync_week_files(season, week)


def sync_week_files(season: int, week: int) -> bool:
    """Mirror week1.py outputs into viewer/ and write week-stamped copies.

    week1.py writes relative to cwd (src/) — it cannot sync to viewer/ itself
    (src/viewer does not exist). Also enriches the viewer picks payload with
    top_projections — the legacy rich format the Top-Plays view consumes
    (same shape as picks[], plus unposted_lines). Root keeps the raw output.
    """
    for name in ("slate_projections.json", "slate_projections.csv",
                 "current_picks.json", "top_picks.json"):
        src_file = SRC / name
        if src_file.exists():
            (VIEWER / name).write_bytes(src_file.read_bytes())
            (ROOT / name).write_bytes(src_file.read_bytes())
    slate_src = VIEWER / "slate_projections.json"
    picks_src = VIEWER / "current_picks.json"
    if not slate_src.exists() or not picks_src.exists():
        print("[autopilot] week1.py outputs missing after run", file=sys.stderr)
        return False
    try:
        payload = json.loads(picks_src.read_text(encoding="utf-8"))
        if isinstance(payload.get("picks"), list) and "top_projections" not in payload:
            enriched = [dict(p, unposted_lines=0) for p in payload["picks"]]
            payload["top_projections"] = enriched
            picks_src.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"  [warn] picks enrichment skipped: {exc}", file=sys.stderr)
    (VIEWER / f"slate_{season}_w{week}.json").write_bytes(slate_src.read_bytes())
    (VIEWER / f"current_picks_{season}_w{week}.json").write_bytes(picks_src.read_bytes())
    return True


def fetch_nba_days(now: datetime) -> None:
    """Optional: balldontlie NBA nights for today + tomorrow (needs API key).

    Free-tier friendly (schedules only; box scores are a paid tier). Best
    effort: failures warn and continue — the manifest scan simply registers
    whatever nba_*_{date}.json files exist. Without a key this is a no-op and
    the board keeps its honest fixture-only NBA state.
    """
    if not os.environ.get("BALLDONTLIE_API_KEY"):
        print("[autopilot] NBA: no BALLDONTLIE_API_KEY - fixture slates stay as-is")
        return
    script = ROOT / "scripts" / "fetch_nba.py"
    for offset in (0, 1):
        day = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
        result = subprocess.run(
            [sys.executable, str(script), "--date", day],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
        )
        status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
        print(f"[autopilot] NBA {day}: {status}")
        if result.returncode not in (0, 2, 3, 4):
            print((result.stderr or "")[-500:], file=sys.stderr)


def fetch_nba_odds_days(now: datetime) -> None:
    """Optional: The Odds API NBA schedule + points props for today + next 2 ET days.

    Uses a DEDICATED NBA_ODDS_API_KEY (free plan, 500 credits/mo) so it never
    drains the NFL ODDS_API_KEY pool. ~1 credit per game; the script refuses to
    spend past --max-credits. Best effort: failures warn and continue.
    """
    if not os.environ.get("NBA_ODDS_API_KEY"):
        print("[autopilot] NBA odds: no NBA_ODDS_API_KEY - skipped")
        return
    days = ",".join((now + timedelta(days=o)).strftime("%Y-%m-%d") for o in (0, 1, 2))
    env = {**os.environ, "ODDS_API_KEY": os.environ["NBA_ODDS_API_KEY"]}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_nba_odds.py"), "--dates", days],
        cwd=ROOT, capture_output=True, text=True, timeout=300, env=env,
    )
    print(f"[autopilot] NBA odds {days}: {'ok' if result.returncode == 0 else f'exit {result.returncode}'}")
    if result.returncode not in (0, 2, 4):
        print((result.stderr or "")[-500:], file=sys.stderr)


# ---------------------------------------------------------------------------
# Slate-index manifest — how the viewer discovers new weeks without code edits
# ---------------------------------------------------------------------------

def scan_nfl_slates(now: datetime) -> dict:
    slates = {}
    for path in sorted(VIEWER.glob("games_*_w*.json")):
        match = GAMES_FILE_RE.fullmatch(path.name)
        if not match:
            continue
        season, week = int(match.group(1)), int(match.group(2))
        slate_file = VIEWER / f"slate_{season}_w{week}.json"
        if not slate_file.exists():
            continue  # incomplete week - never register a half-built slate
        games = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(games, list) or not games:
            continue
        days = sorted(g["gameday"] for g in games if isinstance(g, dict) and g.get("gameday"))
        first, last = days[0], days[-1]
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=ET)
            is_past = last_dt + timedelta(days=1) < now
        except ValueError:
            is_past = False
        key = f"{season}_w{week}"
        span = week_span_label([
            {"kickoff": datetime.strptime(g["gameday"], "%Y-%m-%d").replace(tzinfo=ET)}
            for g in games
        ])
        slates[key] = {
            "season": season,
            "week": week,
            "shortLabel": f"W{week} {'Audit' if is_past else 'Live'}",
            "state": f"{'Historical audit' if is_past else 'Upcoming slate'} · {span}",
            "slate": f"slate_{season}_w{week}.json",
            "games": f"games_{season}_w{week}.json",
            "picks": f"current_picks_{season}_w{week}.json",
            "livePicks": (f"live_picks_{season}_w{week}.json"
                          if not is_past and (VIEWER / f"live_picks_{season}_w{week}.json").exists()
                          else None),
            "injuries": None if is_past else f"injuries_{season}_w{week}.json",
            "odds": None if is_past else "live_odds_feed.json",
            "snapshots": f"snapshots_{season}_w{week}.json",
            "historical": is_past,
        }
    return slates


def scan_nba_slates(now: datetime) -> dict:
    slates = {}
    for path in sorted(VIEWER.glob("nba_games_*.json")):
        match = NBA_GAMES_FILE_RE.fullmatch(path.name)
        if not match:
            continue
        date = match.group(1)
        slate_file = VIEWER / f"nba_slate_{date}.json"
        if not slate_file.exists():
            continue
        try:
            day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=ET)
        except ValueError:
            continue
        is_past = day < now.replace(hour=0, minute=0, second=0, microsecond=0)
        pretty = day.strftime("%b %-d") if hasattr(day, "strftime") else date
        try:
            pretty = f"{day.strftime('%b')} {day.day}"
        except Exception:
            pretty = date
        slates[date] = {
            "season": day.year,
            "date": date,
            "shortLabel": f"{pretty} {'Audit' if is_past else 'Slate'}",
            "state": f"{'Historical audit' if is_past else 'Slate'} · {date}",
            "slate": f"nba_slate_{date}.json",
            "games": f"nba_games_{date}.json",
            "picks": None,
            "injuries": f"nba_injuries_{date}.json",
            "odds": f"nba_odds_{date}.json",
            "snapshots": None,
            "historical": is_past,
            "timezone": "America/New_York",
            "marketOnly": json.loads(slate_file.read_text(encoding="utf-8")) == [],
        }
    return slates


def default_for(slates: dict) -> str | None:
    """Boot default: newest non-historical slate (keys sort chronologically)."""
    live = [k for k, v in slates.items() if not v.get("historical")]
    return live[-1] if live else None


def scan_ufc_cards(now: datetime) -> dict:
    """viewer/ufc_card_<date>.json -> manifest entries (written by fetch_ufc_odds.py)."""
    today = now.astimezone(ET).strftime("%Y-%m-%d")
    cards: dict = {}
    for path in sorted(VIEWER.glob("ufc_card_*.json")):
        date = path.stem.replace("ufc_card_", "")
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        cards[date] = {
            "date": date,
            "event_name": card.get("event_name"),
            "fights": len(card.get("fights") or []),
            "card": path.name,
            "status": f"ufc_status_{date}.json",
            "snapshots": f"ufc_snapshots_{date}.json",
            "historical": date < today,
        }
    return cards


def ufc_default(cards: dict):
    live = [k for k, v in cards.items() if not v["historical"]]
    return live[0] if live else (list(cards)[-1] if cards else None)


def fetch_ufc(now: datetime) -> None:
    """UFC card + model refresh (odds only inside 48h of the card; 2 credits/pull)."""
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_ufc_odds.py")],
                           capture_output=True, text=True, timeout=600)
        for line in (r.stdout or "").strip().splitlines():
            print(f"  {line}")
        if r.returncode != 0:
            print(f"  [warn] UFC pipeline exited {r.returncode}: {(r.stderr or '')[-500:]}", file=sys.stderr)
    except Exception as exc:
        print(f"  [warn] UFC pipeline skipped: {exc}", file=sys.stderr)


def write_manifest(now: datetime) -> Path:
    nfl = scan_nfl_slates(now)
    nba = scan_nba_slates(now)
    ufc = scan_ufc_cards(now)
    manifest = {
        "schema_version": "slate-index.v1",
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "scripts/autopilot.py",
        "sports": {
            "nfl": {"default_slate": default_for(nfl), "slates": nfl},
            "nba": {"default_slate": default_for(nba), "slates": nba},
            "ufc": {"default_card": ufc_default(ufc), "cards": ufc},
        },
    }
    FEEDS.mkdir(parents=True, exist_ok=True)
    dest = FEEDS / "slate-index.json"
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Build-hash week segment (data-freshness label only; UI versions stay manual)
# ---------------------------------------------------------------------------

def bump_build_hash_week(week: int) -> list[str]:
    changed = []
    pages = [VIEWER / "index.html", VIEWER / "audit.html", VIEWER / "verify.html",
             VIEWER / "ledger.html", VIEWER / "ledger" / "index.html"]
    for page in pages:
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        new = BUILD_HASH_RE.sub(lambda m: f"2026-w{week}-v{m.group(2)}", text)
        if new != text:
            page.write_text(new, encoding="utf-8")
            changed.append(str(page.relative_to(ROOT)))
    return changed


# ---------------------------------------------------------------------------
# Selftest (offline, pure functions)
# ---------------------------------------------------------------------------

def selftest() -> int:
    from datetime import datetime as dt

    failures = []
    mk_game = lambda day, time, gid: {
        "game_id": gid, "season_i": 2026, "week_i": (8 if day >= "2026-10-29" else 7),
        "gameday": day, "gametime": time,
        "kickoff": dt.strptime(f"{day} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=ET),
    }
    # Tuesday between weeks: Monday night done, Thursday not started -> w8
    tue = dt(2026, 10, 27, 12, 0, tzinfo=ET)
    season, games = None, None
    csv_rows = [
        mk_game("2026-10-22", "20:15", "2026_07_A"),
        mk_game("2026-10-26", "20:15", "2026_07_B"),
        mk_game("2026-10-29", "20:15", "2026_08_A"),
        mk_game("2026-11-01", "13:00", "2026_08_B"),
    ]
    cutoff = tue - timedelta(hours=LIVE_GRACE_HOURS)
    upcoming = [r for r in csv_rows if r["kickoff"] >= cutoff]
    if min(upcoming, key=lambda r: r["kickoff"])["week_i"] != 8:
        failures.append("tuesday rollover should resolve week 8")
    # Monday night in progress: kickoff 2h ago -> same week
    mon = dt(2026, 10, 26, 22, 15, tzinfo=ET)
    cutoff = mon - timedelta(hours=LIVE_GRACE_HOURS)
    upcoming = [r for r in csv_rows if r["kickoff"] >= cutoff]
    if min(upcoming, key=lambda r: r["kickoff"])["week_i"] != 7:
        failures.append("monday night should stay on week 7")
    # span labels
    games_w8 = [
        {"kickoff": dt(2026, 10, 29, 20, 15, tzinfo=ET)},
        {"kickoff": dt(2026, 11, 2, 20, 15, tzinfo=ET)},
    ]
    if week_span_label(games_w8) != "Oct 29-Nov 2":
        failures.append(f"span label wrong: {week_span_label(games_w8)}")
    games_w7 = [
        {"kickoff": dt(2026, 10, 22, 20, 15, tzinfo=ET)},
        {"kickoff": dt(2026, 10, 26, 20, 15, tzinfo=ET)},
    ]
    if week_span_label(games_w7) != "Oct 22-26":
        failures.append(f"span label wrong: {week_span_label(games_w7)}")
    # default_for picks the newest live slate and never a historical one
    slates = {"2026_w1": {"historical": True}, "2026_w7": {"historical": True},
              "2026_w8": {"historical": False}}
    if default_for(slates) != "2026_w8":
        failures.append("default_for should pick newest live slate")
    if default_for({"2026_w7": {"historical": True}}) is not None:
        failures.append("default_for should be None when only historical slates exist")
    # build-hash bump regex
    sample = "build 2026-w7-v15"
    if BUILD_HASH_RE.sub(lambda m: f"2026-w8-v{m.group(2)}", sample) != "build 2026-w8-v15":
        failures.append("build-hash bump regex broken")
    # v155: player-photo builder pure logic (offline)
    try:
        try:
            import build_player_photos as _bpp
        except ImportError:  # running as a module (python -m scripts.autopilot)
            from scripts import build_player_photos as _bpp
        if _bpp.normalize_name("A.J. Brown Jr.") != "aj brown":
            failures.append("photo normalize_name broken")
        if _bpp.normalize_name("De'Vonta Smith") != _bpp.normalize_name("DeVonta Smith"):
            failures.append("photo apostrophe normalize broken")
        _hits = [{"displayName": "Puka Nakua", "sport": "football"},
                 {"displayName": "Puka Nacua", "sport": "football"}]
        _best = _bpp.pick_best(_hits, "puka nacua", "nfl")
        if not _best or _best.get("displayName") != "Puka Nacua":
            failures.append("photo pick_best broken")
    except Exception as exc:
        failures.append(f"photo module import failed: {exc}")
    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 6
    print("autopilot selftest: ALL PASS")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="PropWire daily data autopilot")
    ap.add_argument("--plan", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--run", action="store_true", help="execute the pipeline")
    ap.add_argument("--skip-model", action="store_true",
                    help="skip week1.py (manifest/build-hash refresh only)")
    ap.add_argument("--selftest", action="store_true", help="offline checks, exit 6 on failure")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not (args.plan or args.run):
        ap.print_help()
        return 2

    now_env = os.environ.get("PROPWIRE_NOW", "").strip()
    now = datetime.fromisoformat(now_env).astimezone(ET) if now_env else datetime.now(ET)
    print(f"[autopilot] now (ET): {now.isoformat(timespec='seconds')}")

    if args.run and not (DATA / "games.csv").exists():
        DATA.mkdir(parents=True, exist_ok=True)
        print("[autopilot] data/games.csv missing - fetching schedule from nflverse")
        urllib.request.urlretrieve(NFLVERSE_BASE, DATA / "games.csv")
    season, games = load_schedule(now)
    week = games[0]["week_i"]
    span = week_span_label(games)
    print(f"[autopilot] active NFL slate: {season} week {week} ({span}, {len(games)} games)")

    existing = (VIEWER / f"games_{season}_w{week}.json").exists()
    print(f"[autopilot] week files {'present' if existing else 'MISSING'} "
          f"(model run: {'skipped' if args.skip_model else 'will run'})")

    if args.plan:
        print(f"[plan] refresh feeds for season {season}")
        print(f"[plan] run src/week1.py --season {season} --week {week}"
              f"{' --odds' if os.environ.get('ODDS_API_KEY') else ' (no ODDS_API_KEY: fair lines only)'}")
        print(f"[plan] write viewer/games_{season}_w{week}.json")
        print(f"[plan] write viewer/slate_{season}_w{week}.json (from slate_projections)")
        print(f"[plan] write viewer/current_picks_{season}_w{week}.json")
        print(f"[plan] write viewer/injuries_{season}_w{week}.json (nflverse report)")
        print(f"[plan] ensure viewer/snapshots_{season}_w{week}.json")
        print(f"[plan] regenerate viewer/feeds/slate-index.json")
        print(f"[plan] refresh viewer/feeds/player_photos.json (incremental, ESPN)")
        print(f"[plan] bump build-hash week segment -> 2026-w{week}-v*")
        return 0

    refresh_feeds(season)
    if not args.skip_model:
        if not run_model(season, week):
            print("[autopilot] model run failed - aborting (fail closed)", file=sys.stderr)
            return 1
    elif not (SRC / "slate_projections.json").exists():
        print("[autopilot] --skip-model but no cached week1.py output in src/ "
              "- run once without --skip-model first (fail closed)", file=sys.stderr)
        return 1
    else:
        if not sync_week_files(season, week):
            return 1
    games_path = write_games(season, week, games)
    injuries_path = write_injuries(season, week, games)
    write_snapshots_stub(season, week)
    fetch_nba_days(now)
    fetch_nba_odds_days(now)
    fetch_ufc(now)
    # v176: refresh real Polymarket player-prop quotes (public API, no key,
    # fail-closed — network failure leaves the feed untouched). DraftKings /
    # FanDuel still flow through the ODDS_API_KEY gate above.
    try:
        _pm = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_polymarket_props.py")],
            capture_output=True, text=True, timeout=45, cwd=str(ROOT))
        for line in (_pm.stdout or "").strip().splitlines():
            print(f"  [polymarket] {line}")
        if _pm.returncode != 0:
            print(f"  [warn] polymarket fetch exited {_pm.returncode}", file=sys.stderr)
    except Exception as exc:
        print(f"  [warn] polymarket fetch skipped: {exc}", file=sys.stderr)
    # v155: refresh the player headshot map (incremental, fail-open).
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.build_player_photos import refresh as _refresh_photos
        _ps = _refresh_photos()
        print(f"[autopilot] player photos: {_ps['new']} new, {_ps['kept']} kept, "
              f"{_ps['unresolved']} unresolved -> viewer/feeds/player_photos.json")
    except Exception as exc:
        print(f"  [warn] player photo refresh skipped: {exc}", file=sys.stderr)
    slate_ok = (VIEWER / f"slate_{season}_w{week}.json").exists()
    if not slate_ok and args.skip_model:
        print(f"[autopilot] slate_{season}_w{week}.json missing and model skipped "
              f"- manifest will omit this week", file=sys.stderr)
    manifest_path = write_manifest(now)
    # Generate pre-kickoff zero-fluff board for email & terminal subscribers
    try:
        from scripts.pre_kickoff_board import generate_board
        board_data = generate_board(f'{season}_w{week}')
        (VIEWER / 'todays_board.html').write_text(board_data['html'], encoding='utf-8')
        (VIEWER / 'todays_board.txt').write_text(board_data['text'], encoding='utf-8')
        print(f'[autopilot] wrote viewer/todays_board.html and .txt ({board_data["item_count"]} items)')
    except Exception as exc:
        print(f'  [warn] pre-kickoff board generation skipped: {exc}', file=sys.stderr)

    bumped = bump_build_hash_week(week)

    print(f"[autopilot] wrote: {games_path.name}, {injuries_path.name}, "
          f"{manifest_path.relative_to(ROOT)}")
    if bumped:
        print(f"[autopilot] build-hash week -> w{week} in: {', '.join(bumped)}")
    print("[autopilot] done - commit changed files to trigger deploy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
