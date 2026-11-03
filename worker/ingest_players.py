"""Propstein 2.0 — player ingest with the v2 identity fix.

Two stages, two ID namespaces (no more collisions):

  stage 1  nba_api active registry      -> Player id `nba-{nbaStatsId}`
           (name only — no ESPN enhancement, source='nba_registry')
  stage 2  ESPN box-score summaries     -> Player id `espn-nba-{espnAthleteId}`
           (team/position/jersey/headshot + rolling form + season stats,
            source='espn')

Merge rule (THE fix): ESPN is canonical by nameKey. When stage 2 meets an
existing `nba-*` row with the same (league, name_key), the registry row is
retired — deleted, its nbaStatsId carried onto the ESPN record — so one
human = one row with the richest identity. Examples: LeBron James
espn-nba-1966 (registry 2544 retired), Giannis espn-nba-3032977.

    DATABASE_URL=... python worker/ingest_players.py [--games 12]

Exit codes: 0 ok, 2 no DATABASE_URL, 3 upstream, 5 db.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date, timedelta

from upsert import EXIT_OK, EXIT_UPSTREAM, EXIT_DB, connect, finish, jsonb, upsert_rows

UA = {"User-Agent": "propstein-ingest/2.0"}
NBA_PATH = "basketball/nba"


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def name_key(name: str) -> str:
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def recent_nba_event_ids(days: int = 2) -> list[str]:
    ids = []
    today = date.today()
    for back in range(days):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        data = fetch_json(
            f"https://site.api.espn.com/apis/site/v2/sports/{NBA_PATH}/scoreboard?dates={d}"
        )
        for ev in data.get("events") or []:
            if (ev.get("status", {}).get("type", {}).get("state")) == "post":
                ids.append(str(ev["id"]))
    return ids


def parse_summary(event_id: str):
    """Yields (player_row, game_log) tuples from one ESPN summary."""
    d = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/{NBA_PATH}/summary?event={event_id}")
    header = (d.get("header", {}).get("competitions") or [{}])[0]
    game_date = header.get("date") or ""
    competitors = header.get("competitors") or []
    for team in d.get("boxscore", {}).get("players") or []:
        abbr = (team.get("team") or {}).get("abbreviation") or "—"
        opp = next(
            (c["team"]["abbreviation"] for c in competitors if (c.get("team") or {}).get("abbreviation") != abbr),
            "—",
        )
        for st in team.get("statistics") or []:
            labels = st.get("names") or st.get("labels") or []
            for a in st.get("athletes") or []:
                ath = a.get("athlete") or {}
                if not ath.get("id") or a.get("didNotPlay"):
                    continue
                stats = {}
                for i, v in enumerate(a.get("stats") or []):
                    try:
                        stats[labels[i]] = float(v)
                    except (ValueError, TypeError, IndexError):
                        continue
                row = {
                    "id": f"espn-nba-{ath['id']}",
                    "league": "NBA",
                    "name": ath.get("displayName") or "",
                    "name_key": name_key(ath.get("displayName") or ""),
                    "team": abbr,
                    "position": (ath.get("position") or {}).get("abbreviation"),
                    "jersey": int(ath["jersey"]) if str(ath.get("jersey") or "").isdigit() else None,
                    "height_cm": None,
                    "weight_kg": None,
                    "headshot": (ath.get("headshot") or {}).get("href"),
                    "espn_id": str(ath["id"]),
                    "nba_stats_id": None,
                    "source": "espn",
                    "form_summary": None,
                    "stats_summary": None,
                }
                log = {
                    "espn_id": str(ath["id"]),
                    "game_id": f"espn-nba-{event_id}",
                    "date": game_date,
                    "opponent": opp,
                    "stats": stats,
                }
                yield row, log


def summarize(logs: list[dict]) -> tuple[dict, list[dict]]:
    """logs -> (season stats_summary, last-3 form_summary)."""
    def avg(k):
        return round(sum(l["stats"].get(k, 0) for l in logs) / len(logs), 1) if logs else None

    stats_summary = {
        "GP": len(logs),
        "MIN": avg("MIN"), "PTS": avg("PTS"), "REB": avg("REB"),
        "AST": avg("AST"), "STL": avg("STL"), "BLK": avg("BLK"),
    }
    ordered = sorted(logs, key=lambda l: l["date"], reverse=True)[:3]
    form = [
        {
            "date": (l["date"] or "")[:10],
            "opponent": l["opponent"],
            "PTS": l["stats"].get("PTS", 0),
            "REB": l["stats"].get("REB", 0),
            "AST": l["stats"].get("AST", 0),
            "seasonAvgPTS": stats_summary["PTS"] or 0,
        }
        for l in ordered
    ]
    return stats_summary, form


def stage_registry(cur) -> int:
    """nba_api registry -> nba-{statsId} rows (merged later by stage 2)."""
    from nba_api.stats.static import players as nba_players

    registry = nba_players.get_active_players()
    rows = []
    for p in registry:
        rows.append({
            "id": f"nba-{p['id']}",
            "league": "NBA",
            "name": p["full_name"],
            "name_key": name_key(p["full_name"]),
            "team": None, "position": None, "jersey": None,
            "height_cm": None, "weight_kg": None, "headshot": None,
            "espn_id": None,
            "nba_stats_id": str(p["id"]),
            "source": "nba_registry",
            "form_summary": None, "stats_summary": None,
        })
    n = upsert_rows(cur, '"Player"', rows, ["id"], ["name", "name_key"])
    print(f"  registry: {n} nba-* rows")
    return len(registry)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=12, help="recent final games to scan")
    args = ap.parse_args()

    conn = None
    try:
        conn = connect()
        with conn.cursor() as cur:
            # stage 1 — registry
            try:
                stage_registry(cur)
            except ImportError:
                print("WARN: nba_api not installed — registry stage skipped", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: registry stage failed (continuing): {e}", file=sys.stderr)

            # stage 2 — ESPN summaries (canonical)
            try:
                event_ids = recent_nba_event_ids(days=2)[: args.games]
            except Exception as e:  # noqa: BLE001
                print(f"FATAL: scoreboard fetch failed: {e}", file=sys.stderr)
                finish(conn, False)
                return EXIT_UPSTREAM

            logs_by_espn_id: dict[str, list[dict]] = {}
            meta_by_espn_id: dict[str, dict] = {}
            for eid in event_ids:
                try:
                    for row, log in parse_summary(eid):
                        meta_by_espn_id[row["id"]] = row
                        logs_by_espn_id.setdefault(row["id"], []).append(log)
                except Exception as e:  # noqa: BLE001
                    print(f"WARN: summary {eid} failed: {e}", file=sys.stderr)

            if not meta_by_espn_id:
                print("FATAL: no players parsed from summaries", file=sys.stderr)
                finish(conn, False)
                return EXIT_UPSTREAM

            # THE merge: retire nba-* duplicates by (league, name_key)
            retired = 0
            for pid, row in meta_by_espn_id.items():
                cur.execute(
                    'SELECT id, nba_stats_id FROM "Player" WHERE league = %s AND name_key = %s AND id <> %s',
                    ("NBA", row["name_key"], pid),
                )
                dupe = cur.fetchone()
                if dupe:
                    cur.execute('DELETE FROM "Player" WHERE id = %s', (dupe[0],))
                    row["nba_stats_id"] = dupe[1] or row["nba_stats_id"]
                    retired += 1

            rows = []
            for pid, row in meta_by_espn_id.items():
                stats_summary, form = summarize(logs_by_espn_id[pid])
                row["stats_summary"] = jsonb(stats_summary)
                row["form_summary"] = jsonb(form)
                rows.append(row)

            n = upsert_rows(
                cur, '"Player"', rows, ["id"],
                ["name", "name_key", "team", "position", "jersey", "headshot",
                 "espn_id", "nba_stats_id", "source", "form_summary", "stats_summary"],
            )
            print(f"  espn: {n} espn-nba-* players, {retired} registry rows retired by merge")

        finish(conn, True)
        conn = None
        print("OK: player ingest complete")
        return EXIT_OK
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: db write failed: {e}", file=sys.stderr)
        if conn:
            finish(conn, False)
        return EXIT_DB


if __name__ == "__main__":
    sys.exit(main())
