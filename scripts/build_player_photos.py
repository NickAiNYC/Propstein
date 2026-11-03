#!/usr/bin/env python3
"""v155 — player headshot map builder.

Resolves ESPN athlete headshots for every player appearing in the viewer
slates (NFL week files + NBA night files) and writes
viewer/feeds/player_photos.json — a {photos, by_name} map keyed by the
app's own player_id (GSIS for NFL, fx slugs for NBA) with a normalized
display-name index for rows that only carry a name (picks, injuries, CLV).

- Source: ESPN public search v2 (site.api.espn.com/apis/search/v2), strict
  normalized full-name match against result displayName. Headshots are
  hosted on a.espncdn.com, which the production CSP img-src already allows
  (v150 team-crest precedent) — no CSP change required.
- Every URL is verified (HTTP 200 + image/* + non-trivial body) before it
  enters the map — no broken images ship.
- Incremental + idempotent: existing entries are kept as-is; only names
  still unresolved hit the search API. Safe to re-run daily (the autopilot
  pipeline calls refresh() after slate build).
- Fail-open by contract: any network/API error is downgraded to an
  unresolved name. This module must never abort the daily pipeline.

Usage:
  python3 scripts/build_player_photos.py            # incremental refresh
  python3 scripts/build_player_photos.py --force    # re-resolve everyone
  python3 scripts/build_player_photos.py --limit 5  # smoke run
  python3 scripts/build_player_photos.py --selftest # offline, exit 6 on fail
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer"
FEEDS = VIEWER / "feeds"
OUT_PATH = FEEDS / "player_photos.json"

SEARCH_URL = "https://site.api.espn.com/apis/search/v2?limit=5&query={q}"
REQUEST_TIMEOUT = 10.0
POLITENESS_SLEEP = 0.10
MIN_IMAGE_BYTES = 1000

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# Documented ESPN first-name spellings that differ from slate/nflverse forms.
# Kept tiny and explicit — only add entries proven by a real resolution miss.
ALIAS_FIRST = {
    "terrence": ["terance"],
    "herb": ["herbert"],
    "josh": ["joshua"],
    "deuce": ["miles"],
    "ron": ["ronald"],
    "marquise": ["hollywood"],
}
_DROP_RE = re.compile(r"[.,'’]")   # removed outright: A.J.==AJ, De'Vonta==DeVonta (ESPN style)
_SPACE_RE = re.compile(r"[-]")      # hyphenated surnames -> space-separated

# v221 — ESPN search `subtitle` carries the player's current team as a display
# name ("Brooklyn Nets", "LA Clippers"). Mapped to the app's team codes so the
# avatar badge can ride the photo entry when a data source ships team:null
# (The Odds API quotes do exactly that). Slate rows keep working as fallback
# hints for already-resolved players (no network needed to backfill).
TEAM_BY_NAME = {
    # ── NBA (30) ──
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GSW", "houston rockets": "HOU", "indiana pacers": "IND",
    "la clippers": "LAC", "los angeles clippers": "LAC",
    "los angeles lakers": "LAL", "la lakers": "LAL",
    "memphis grizzlies": "MEM", "miami heat": "MIA", "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN", "new orleans pelicans": "NOP", "new york knicks": "NYK",
    "oklahoma city thunder": "OKC", "orlando magic": "ORL", "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX", "portland trail blazers": "POR", "sacramento kings": "SAC",
    "san antonio spurs": "SAS", "toronto raptors": "TOR", "utah jazz": "UTA",
    "washington wizards": "WAS",
    # ── NFL (32) ──
    "arizona cardinals": "ARI", "atlanta falcons": "ATL", "baltimore ravens": "BAL",
    "buffalo bills": "BUF", "carolina panthers": "CAR", "cincinnati bengals": "CIN",
    "cleveland browns": "CLE", "dallas cowboys": "DAL", "denver broncos": "DEN",
    "detroit lions": "DET", "green bay packers": "GB", "houston texans": "HOU",
    "indianapolis colts": "IND", "jacksonville jaguars": "JAX", "kansas city chiefs": "KC",
    "las vegas raiders": "LV", "los angeles chargers": "LAC", "los angeles rams": "LAR",
    "miami dolphins": "MIA", "minnesota vikings": "MIN", "new england patriots": "NE",
    "new orleans saints": "NO", "new york giants": "NYG", "new york jets": "NYJ",
    "philadelphia eagles": "PHI", "pittsburgh steelers": "PIT", "san francisco 49ers": "SF",
    "seattle seahawks": "SEA", "tampa bay buccaneers": "TB", "tennessee titans": "TEN",
    "washington commanders": "WAS", "washington football team": "WAS",
}


def team_code_of(hit: dict) -> str:
    """Team code from an ESPN search hit's subtitle; '' when unmapped.

    Subtitles observed in the wild are clean team display names
    ("Brooklyn Nets"). Tolerates decorations by matching on the longest
    known team name that prefixes the subtitle.
    """
    raw = str(hit.get("subtitle") or "").strip().lower()
    if not raw:
        return ""
    if raw in TEAM_BY_NAME:
        return TEAM_BY_NAME[raw]
    for name, code in sorted(TEAM_BY_NAME.items(), key=lambda kv: -len(kv[0])):
        if raw.startswith(name + " ") or raw.startswith(name + "·") or raw.startswith(name):
            return code
    return ""


def normalize_name(value: str) -> str:
    """Mirror of viewer/app.js normalizePlayerName — keep the two in lockstep."""
    text = str(value or "").lower()
    # Accent folding: slate data keeps "Audric Estimé", ESPN ships "Estime".
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = _SPACE_RE.sub(" ", _DROP_RE.sub("", text))
    tokens = [t for t in text.split() if t and t not in SUFFIXES]
    return " ".join(tokens).strip()


def load_existing() -> dict:
    try:
        data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("photos"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"photos": {}, "by_name": {}}


def collect_players() -> dict:
    """normalized name -> {player_id, name, league} across all viewer slates
    and NBA odds feeds (v221: The Odds API market-only slates have empty slate
    files — their player roster lives in the nba_odds_*.json quote lists, so
    those names must be collected too or they never resolve a headshot)."""
    players: dict[str, dict] = {}
    if not VIEWER.exists():
        return players

    for path in sorted(VIEWER.glob("slate_2026_w*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get("player_display_name") or "").strip()
            pid = str(row.get("player_id") or "").strip()
            if not name:
                continue
            entry = {"player_id": pid, "name": name, "league": "nfl"}
            key = normalize_name(name)
            if key not in players or (pid and not players[key]["player_id"]):
                players[key] = entry

    for path in sorted(VIEWER.glob("nba_slate_*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get("player_display_name") or "").strip()
            pid = str(row.get("player_id") or "").strip()
            if not name:
                continue
            entry = {"player_id": pid, "name": name, "league": "nba"}
            key = normalize_name(name)
            if key not in players or (pid and not players[key]["player_id"]):
                players[key] = entry

    # v221: market-only slates carry their roster in the odds feed quotes.
    # player_id there is a stable provider id ("odds-nba-<slug>"); when a name
    # already resolved via a fixture slate the fixture entry wins (same photo,
    # same name match path).
    for path in sorted(VIEWER.glob("nba_odds_*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        quotes = doc.get("quotes") if isinstance(doc, dict) else None
        for row in quotes if isinstance(quotes, list) else []:
            name = str(row.get("player_name") or "").strip()
            pid = str(row.get("player_id") or "").strip()
            if not name:
                continue
            entry = {"player_id": pid, "name": name, "league": "nba"}
            key = normalize_name(name)
            if key not in players or (pid and not players[key]["player_id"]):
                players[key] = entry

    return players


def collect_team_hints() -> dict:
    """normalized name -> team code from slate rows (no network).

    Fixture/audit slates carry a team code per row; used to backfill the team
    field of already-resolved photo entries without touching ESPN again.
    """
    hints: dict[str, str] = {}
    if not VIEWER.exists():
        return hints
    for glob_pat in ("slate_2026_w*.json", "nba_slate_*.json"):
        for path in sorted(VIEWER.glob(glob_pat)):
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for row in rows if isinstance(rows, list) else []:
                name = str(row.get("player_display_name") or "").strip()
                team = str(row.get("team") or "").strip().upper()
                if name and team:
                    hints.setdefault(normalize_name(name), team)
    return hints


def _http_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": "PropWire-photos/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def espn_search_variants(display_name: str) -> list[str]:
    """Query strings to try, best-first.

    1. the slate's display name,
    2. accent-folded (slate "Audric Estimé" vs ESPN "Audric Estime"),
    3. first-name alias swaps for documented ESPN spellings
       (Terance Mann, Herbert Jones, Joshua Palmer, Miles "Deuce" McBride).
    Surname-only queries are deliberately NOT generated — the surname pool is
    ambiguous ("mann" -> Tre Mann, not Terance) and a wrong photo is worse
    than no photo.
    """
    folded = "".join(c for c in unicodedata.normalize("NFKD", display_name)
                     if not unicodedata.combining(c))
    queries = [display_name]
    if folded != display_name:
        queries.append(folded)
    tokens = display_name.split()
    if tokens:
        alias_list = ALIAS_FIRST.get(tokens[0].lower(), [])
        for alias in alias_list:
            queries.append(" ".join([alias] + tokens[1:]))
    # v221: ESPN search can return NOTHING for suffixed names ("Paul Reed Jr"
    # -> 0 results) while the bare name resolves. Try the suffix-stripped form.
    stripped = " ".join(t for t in tokens if t.lower() not in SUFFIXES)
    if stripped and stripped != display_name:
        queries.append(stripped)
    return queries


def espn_search(name: str) -> list[dict]:
    """Player-type result contents for ONE query string."""
    payload = _http_json(SEARCH_URL.format(q=urllib.request.quote(name)))
    if not payload:
        return []
    hits = []
    for block in payload.get("results", []):
        if block.get("type") == "player":
            hits.extend(block.get("contents", []))
    return hits


def _pool(hits: list[dict], league: str) -> list[dict]:
    """League-filtered, de-duplicated candidate pool. Pure.

    - defaultLeagueSlug ('nfl'/'nba') is the primary filter — it kills
      same-name college/WNBA pros that plain sport matching lets through.
    - Duplicated athlete payloads (ESPN often returns the same player twice,
      once with image=None) collapse to the image-bearing copy.
    """
    league_slug = league
    league_tag = {"nfl": "football", "nba": "basketball"}.get(league, "")
    pool: list[dict] = []
    by_uid: dict[str, dict] = {}
    for h in hits:
        slug = str(h.get("defaultLeagueSlug") or "").lower()
        if slug:
            if slug != league_slug:
                continue
        elif league_tag and h.get("sport") != league_tag:
            continue
        uid = str(h.get("uid") or h.get("id") or h.get("displayName"))
        entry = {**h, "_nn": normalize_name(h.get("displayName") or ""),
                 "_img": bool(headshot_of(h))}
        if uid in by_uid:
            if entry["_img"] and not by_uid[uid]["_img"]:
                pool[pool.index(by_uid[uid])] = entry
                by_uid[uid] = entry
            continue
        by_uid[uid] = entry
        pool.append(entry)
    return pool


def pick_best(hits: list[dict], norm_query: str, league: str) -> dict | None:
    """Strict normalized full-name match on the league pool; prefer images."""
    strict = [p for p in _pool(hits, league) if p["_nn"] == norm_query]
    if not strict:
        return None
    strict.sort(key=lambda p: not p["_img"])
    return strict[0]


def pick_fuzzy(hits: list[dict], norm_query: str, league: str) -> dict | None:
    """Guarded second pass for name-variant cases (Terrence/Terance Mann,
    Josh/Joshua Palmer, Audric Estime/Estimé after folding).

    Acceptance is deliberately tight — a wrong photo in a betting terminal is
    worse than no photo:
      * league pool (slug or sport filtered, deduped, image-preferred),
      * identical normalized LAST token,
      * same first-initial,
      * and exactly ONE such candidate in the pool.
    Anything looser stays unresolved and ships the initials fallback instead.
    """
    q_tokens = norm_query.split()
    if not q_tokens:
        return None
    q_last, q_first0 = q_tokens[-1], q_tokens[0][:1]
    cands = []
    for p in _pool(hits, league):
        t = p["_nn"].split()
        if not t or t[-1] != q_last or t[0][:1] != q_first0:
            continue
        if p["_nn"] == norm_query:
            continue  # strict pass would already have taken it
        cands.append(p)
    if len(cands) != 1:
        return None
    return cands[0]


def verify_url(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "PropWire-photos/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            ctype = str(resp.headers.get("Content-Type", ""))
            body = resp.read(MIN_IMAGE_BYTES + 1)
            return resp.status == 200 and ctype.startswith("image/") and len(body) >= MIN_IMAGE_BYTES
    except (urllib.error.URLError, OSError):
        return False


def headshot_of(hit: dict) -> str:
    image = hit.get("image") or {}
    url = image.get("default") or image.get("defaultDark") or ""
    return url.strip() if isinstance(url, str) else ""


def refresh(limit: int | None = None, force: bool = False, quiet: bool = False) -> dict:
    """Resolve every still-unmapped player; write feeds/player_photos.json."""
    existing = load_existing()
    photos: dict = existing.get("photos", {})
    by_name: dict = existing.get("by_name", {})

    players = collect_players()
    team_hints = collect_team_hints()
    todo = [
        (key, meta) for key, meta in sorted(players.items())
        if force or not (meta["player_id"] and meta["player_id"] in photos)
    ]
    if limit:
        todo = todo[:limit]

    resolved = new = failed = 0
    unresolved_names: list[str] = []
    for i, (key, meta) in enumerate(todo, 1):
        best = None
        for query in espn_search_variants(meta["name"]):
            time.sleep(POLITENESS_SLEEP)
            hits = espn_search(query)
            q_norm = normalize_name(query)
            best = (pick_best(hits, key, meta["league"]) or
                    pick_best(hits, q_norm, meta["league"]) or
                    pick_fuzzy(hits, key, meta["league"]) or
                    pick_fuzzy(hits, q_norm, meta["league"]))
            if best and headshot_of(best):
                break
        url = headshot_of(best) if best else ""
        if url and verify_url(url):
            pid = meta["player_id"] or f"name:{key}"
            # v221: team code rides the entry (ESPN subtitle first, slate hint
            # as fallback) so avatarFor can badge market-only rows whose
            # quotes ship team:null.
            team = team_code_of(best) if best else ""
            if not team:
                team = team_hints.get(key, "")
            entry_payload = {"url": url, "name": meta["name"], "league": meta["league"]}
            if team:
                entry_payload["team"] = team
            photos[pid] = entry_payload
            by_name[key] = pid
            resolved += 1
            new += 1
        else:
            by_name.pop(key, None)
            failed += 1
            unresolved_names.append(meta["name"])
        if not quiet and i % 50 == 0:
            print(f"[photos] {i}/{len(todo)} scanned, {new} new", flush=True)

    # v221: backfill team codes on already-resolved entries (slate hints only —
    # no extra network; missing hints leave the entry unchanged).
    backfilled = 0
    for key, pid in by_name.items():
        entry = photos.get(pid)
        if not isinstance(entry, dict) or entry.get("team"):
            continue
        hint = team_hints.get(key, "")
        if hint:
            entry["team"] = hint
            backfilled += 1

    # Drop by_name keys whose photo vanished (keeps map self-consistent).
    by_name = {k: pid for k, pid in by_name.items() if pid in photos}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ESPN search v2 -> a.espncdn.com headshots (verified 200 image/*)",
        "count": len(photos),
        "photos": photos,
        "by_name": by_name,
    }
    FEEDS.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=FEEDS, delete=False, suffix=".tmp") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        tmp = Path(fh.name)
    tmp.replace(OUT_PATH)

    return {
        "total_players": len(players),
        "scanned": len(todo),
        "resolved": resolved,
        "new": new,
        "unresolved": failed,
        "kept": len(photos) - new,
        "teams_backfilled": backfilled,
        "unresolved_names": unresolved_names,
    }


def selftest() -> int:
    """Offline pure-function checks (no network)."""
    assert normalize_name("A.J. Brown Jr.") == "aj brown", normalize_name("A.J. Brown Jr.")
    assert normalize_name("A.J. Brown") == normalize_name("AJ Brown"), "dot variants must collapse identically"
    assert normalize_name("De'Vonta Smith, III") == "devonta smith", normalize_name("De'Vonta Smith, III")
    assert normalize_name("DeVonta Smith") == normalize_name("De'Vonta Smith"), "apostrophe variants must collapse"
    assert normalize_name("JuJu Smith-Schuster") == "juju smith schuster"
    assert normalize_name("Audric Estimé") == "audric estime", "accent folding"
    assert normalize_name("  Puka   Nacua ") == "puka nacua"
    assert normalize_name("") == ""

    hit_ok = {
        "displayName": "Puka Nacua",
        "sport": "football",
        "image": {"default": "https://a.espncdn.com/i/headshots/nfl/players/full/4426515.png"},
    }
    hit_wrong = {
        "displayName": "Puka Nakua",
        "sport": "football",
        "image": {"default": None},   # imgless dupe shape ESPN often returns
    }
    # _pool copies entries — assert on values, not identity.
    best = pick_best([hit_wrong, hit_ok], "puka nacua", "nfl")
    assert best and best["displayName"] == "Puka Nacua", best
    assert pick_best([hit_wrong], "puka nacua", "nfl") is None

    hit_hoops = {"displayName": "Donovan Mitchell", "sport": "basketball",
                 "image": {"default": "https://a.espncdn.com/i/headshots/nba/players/full/3059327.png"}}
    hit_grid = {"displayName": "Donovan Mitchell", "sport": "football",
                "image": {"default": "https://a.espncdn.com/i/headshots/nfl/players/full/1.png"}}
    best_hoops = pick_best([hit_grid, hit_hoops], "donovan mitchell", "nba")
    assert best_hoops and best_hoops["sport"] == "basketball", best_hoops

    # fuzzy pass: variant first-name, same surname+initial, unique candidate
    terance = {"displayName": "Terance Mann", "sport": "basketball",
               "image": {"default": "https://a.espncdn.com/i/headshots/nba/players/full/1.png"}}
    got = pick_fuzzy([terance], "terrence mann", "nba")
    assert got and got["displayName"] == "Terance Mann", got
    # fuzzy refuses ambiguous or wrong-initial cases
    moore_a = {"displayName": "Chris Moore", "sport": "football"}
    moore_b = {"displayName": "Chris Moore Jr.", "sport": "football"}
    assert pick_fuzzy([moore_a, moore_b], "chris moore", "nfl") is None
    assert pick_fuzzy([terance], "deuce mcbride", "nba") is None

    assert headshot_of({"image": {"default": " x "}}) == "x"
    assert headshot_of({}) == ""

    # v221: team code parsing from ESPN subtitle.
    assert team_code_of({"subtitle": "Brooklyn Nets"}) == "BKN", team_code_of({"subtitle": "Brooklyn Nets"})
    assert team_code_of({"subtitle": "LA Clippers"}) == "LAC"
    assert team_code_of({"subtitle": "Philadelphia 76ers"}) == "PHI"
    assert team_code_of({"subtitle": "Philadelphia Eagles"}) == "PHI"
    assert team_code_of({"subtitle": ""}) == ""
    assert team_code_of({"subtitle": "Some College Team"}) == ""

    players = collect_players()
    assert players, "collect_players found zero players in viewer slates"
    assert all(m["league"] in ("nfl", "nba") for m in players.values())
    # v221: the odds feed roster must be collected too — market-only slates
    # have empty slate files, so without this scan their players never resolve.
    odds_only = [m for m in players.values() if str(m["player_id"]).startswith("odds-nba-")]
    assert odds_only, "collect_players missed the nba_odds_*.json quote roster"

    hints = collect_team_hints()
    assert hints, "collect_team_hints found zero slate team hints"
    assert all(isinstance(v, str) and v.isupper() and len(v) <= 4 for v in hints.values())

    print(f"build_player_photos selftest: ALL PASS ({len(players)} players in slates+feeds, "
          f"{len(odds_only)} odds-feed ids, {len(hints)} team hints)")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        try:
            return selftest()
        except AssertionError as exc:
            print(f"build_player_photos selftest: FAIL — {exc}", file=sys.stderr)
            return 6
    force = "--force" in args
    quiet = "--quiet" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    stats = refresh(limit=limit, force=force, quiet=quiet)
    print(f"[photos] players={stats['total_players']} scanned={stats['scanned']} "
          f"new={stats['new']} kept={stats['kept']} unresolved={stats['unresolved']} "
          f"teams_backfilled={stats.get('teams_backfilled', 0)}")
    if stats.get("unresolved_names"):
        print(f"[photos] unresolved: {', '.join(stats['unresolved_names'][:12])}")
    print(f"[photos] wrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
