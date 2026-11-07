"""stats.nba.com provider — the FREE, keyless path (DECISIONS.md D7).

Owner call 2026-11-03: Propstein runs on official NBA.com league feeds at
$0. The endpoints, parameters and browser-grade headers mirror the
production-tested contracts maintained by swar/nba_api (MIT, ~3.9k stars;
header drift is tracked upstream and patched in releases like v1.11.4 —
swar/nba_api#633). We speak the same endpoint language through our own
injectable transport so the provider stays hermetically testable and
dependency-light; swapping to the library itself later is a one-function
change (``_default_transport``).

Honest trade-offs (recorded in D7 — read before relying on this path):
- unofficial access to league endpoints: no SLA, no contract, no guarantee
  the edge does not block datacenter IPs (GitHub Actions runners included);
- headers/paths can drift — when NBA.com changes, mirror the upstream fix;
- politeness discipline: 1.2 s spacing between successful calls, one
  60 s backoff retry on HTTP 429, then fail closed.

Fail-closed contract (same error classes as the balldontlie provider):
    - HTTP 429 twice       -> RateLimitError        (CLI exit 4)
    - HTTP 403 / any 4xx-5xx -> ProviderNetworkError (CLI exit 5)
    - malformed payload    -> ProviderNetworkError   (CLI exit 5)
  A provider error NEVER produces partial "best effort" model input.

Normalized row schema is byte-identical to `data/providers.py` (the
features/model/eval/publish layers never learn which provider ran); the
legacy `bdl_game_id` field carries the raw stats.nba.com GAME_ID. ET
slate keying: stats.nba.com dates are already Eastern — GAME_DATE is used
as-is, matching viewer/js/sports/nba.js etDateKey() semantics.
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Callable, Iterable

from .providers import ProviderNetworkError, RateLimitError, parse_minutes

BASE_URL = "https://stats.nba.com/stats"
REQUEST_SPACING_SECONDS = 1.2   # politeness; do not lower without an owner decision
BACKOFF_SECONDS = 60.0          # one 429 retry after this, then fail closed

# Mirrors swar/nba_api's header requirements (swar/nba_api#633): the edge
# rejects clients that do not look like a browser tab on nba.com.
NBA_COM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def _decode_body(raw: bytes) -> dict:
    """Decode a stats.nba.com response body (gzip/deflate/identity) to JSON."""
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise ProviderNetworkError(f"gzip decode failed: {exc}") from exc
    elif raw[:1] == b"\x78":  # zlib/deflate magic (0x78 0x01/0x9C/0xDA)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error as exc:
                raise ProviderNetworkError(f"deflate decode failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderNetworkError(f"stats.nba.com returned non-JSON: {exc}") from exc


def _int_or_none(val):
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


class NbaComProvider:
    """Official stats.nba.com box scores — keyless, free, fail-closed.

    `transport` and `sleep_fn` are injectable for offline tests; production
    leaves them at the urllib defaults.
    """

    source = "stats_nba_com"

    def __init__(
        self,
        base_url: str = BASE_URL,
        spacing_seconds: float = REQUEST_SPACING_SECONDS,
        transport: Callable[[str], tuple[int, dict]] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        league_id: str = "00",
        season_type: str = "Regular Season",
    ):
        self.base_url = base_url.rstrip("/")
        self.spacing = spacing_seconds
        self._transport = transport or self._default_transport
        self._sleep = sleep_fn or time.sleep
        self.league_id = league_id
        self.season_type = season_type

    # ── transport ───────────────────────────────────────────────────────────
    @staticmethod
    def _default_transport(url: str) -> tuple[int, dict]:
        # Node transport provides HTTP/2 + modern browser TLS negotiation to satisfy
        # Akamai Bot Manager (DECISIONS.md D7). Falls back to urllib if node is absent.
        node_bin = shutil.which("node")
        script = Path(__file__).resolve().parents[3] / "scripts" / "fetch_nbacom_endpoint.mjs"
        if node_bin and script.exists():
            try:
                proc = subprocess.run(
                    [node_bin, str(script), url],
                    capture_output=True,
                    text=True,
                    timeout=35,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout)
                    status = data.get("status", 500)
                    if status == 429:
                        return 429, {}
                    if status >= 400:
                        return status, {}
                    return status, data.get("body", {})
            except Exception as exc:
                raise ProviderNetworkError(f"node transport error: {exc}") from exc

        req = urllib.request.Request(url, headers=NBA_COM_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, _decode_body(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except ProviderNetworkError:
            raise
        except Exception as exc:  # network layer
            raise ProviderNetworkError(f"network error: {exc}") from exc

    def _get(self, path: str, params: dict) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(clean)}"
        for attempt in range(3):
            status, payload = self._transport(url)
            if status == 429:
                self._sleep(BACKOFF_SECONDS)
                status, payload = self._transport(url)
                if status == 429:
                    raise RateLimitError("stats.nba.com rate limit exhausted after backoff retry")
            if status in (500, 502, 503, 504) and attempt < 2:
                self._sleep(3.0 * (attempt + 1))
                continue
            if status != 200:
                raise ProviderNetworkError(f"stats.nba.com HTTP {status} on {path}")
            break
        self._sleep(self.spacing)
        return payload or {}

    # ── result-set plumbing ─────────────────────────────────────────────────
    @staticmethod
    def _result_set(payload: dict, *names: str) -> list[dict]:
        sets = payload.get("resultSets") or payload.get("dataSets") or []
        for rs in sets:
            if rs.get("name") in names:
                headers = rs.get("headers") or rs.get("columns") or []
                return [dict(zip(headers, row)) for row in (rs.get("rowSet") or [])]
        raise ProviderNetworkError(
            f"stats.nba.com response missing result set {names} — fail-closed"
        )

    @staticmethod
    def _season_key(et_date: str) -> str:
        """NBA season key ('2026-27') for a YYYY-MM-DD Eastern date.

        Seasons run Oct-Jun; July-September belongs to the upcoming season.
        """
        y, m = int(et_date[:4]), int(et_date[5:7])
        start = y if m >= 7 else y - 1
        return f"{start}-{str(start + 1)[-2:]}"

    # ── public API ──────────────────────────────────────────────────────────
    def fetch_range(self, dates: Iterable[str]) -> dict:
        """Fetch games + full box scores for ET calendar dates (YYYY-MM-DD).

        Returns {"rows": [...], "games": [...], "meta": {...}} — the same
        world shape as every other provider.
        """
        dates = list(dates)
        rows: list[dict] = []
        games: list[dict] = []
        for date in dates:
            games.extend(self._fetch_day(date, rows))
        return {
            "rows": rows,
            "games": games,
            "meta": {
                "source": self.source,
                "dates": dates,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "_fixture": False,
            },
        }

    # ── per-day ingestion ───────────────────────────────────────────────────
    def _fetch_day(self, date: str, rows: list[dict]) -> list[dict]:
        mm, dd, yyyy = date[5:7], date[8:10], date[:4]
        payload = self._get("/leaguegamefinder", {
            "LeagueID": self.league_id,
            "SeasonType": self.season_type,
            "Season": self._season_key(date),
            "PlayerOrTeam": "T",
            "DateFrom": f"{mm}/{dd}/{yyyy}",
            "DateTo": f"{mm}/{dd}/{yyyy}",
        })
        team_rows = self._result_set(payload, "LeagueGameFinderResults")
        by_game: dict[str, list[dict]] = {}
        for r in team_rows:
            gid = str(r.get("GAME_ID") or "").strip()
            if gid:
                by_game.setdefault(gid, []).append(r)
        day_games: list[dict] = []
        for gid in sorted(by_game):
            game = self._game_from_team_rows(gid, by_game[gid], date)
            day_games.append(game)
            if game["status"] == "Final":
                rows.extend(self._fetch_game_boxscore(game))
        return day_games

    def _game_from_team_rows(self, gid: str, trs: list[dict], date: str) -> dict:
        seen: dict[str, dict] = {}
        for r in trs:
            abbr = (r.get("TEAM_ABBREVIATION") or "").strip()
            if abbr and abbr not in seen:
                seen[abbr] = r
        if len(seen) != 2:
            raise ProviderNetworkError(
                f"game {gid}: expected 2 team rows from leaguegamefinder, got {len(seen)}"
            )
        home_row = next(
            (r for r in seen.values() if "vs." in str(r.get("MATCHUP", ""))), None)
        if home_row is None:
            raise ProviderNetworkError(
                f"game {gid}: no home ('vs.') row in MATCHUP set — fail-closed"
            )
        home_abbr = home_row["TEAM_ABBREVIATION"]
        away_row = next(r for a, r in seen.items() if a != home_abbr)
        away_abbr = away_row["TEAM_ABBREVIATION"]

        home_pts, away_pts = _int_or_none(home_row.get("PTS")), _int_or_none(away_row.get("PTS"))
        if home_pts is not None and away_pts is not None:
            status = "Final"
        elif home_pts is None and away_pts is None:
            status = "Scheduled"
        else:
            status = "InProgress"
        return {
            "bdl_game_id": gid,
            "game_id": f"nba-{gid}",
            "game_date": date,   # stats.nba.com dates are Eastern — the slate key itself
            "tipoff_utc": None,
            "status": status,
            "home_team": home_abbr,
            "away_team": away_abbr,
            "home_team_score": home_pts,
            "away_team_score": away_pts,
            "_fixture": False,
            "source": self.source,
        }

    def _fetch_game_boxscore(self, game: dict) -> list[dict]:
        payload = self._get("/boxscoretraditionalv2", {
            "GameID": game["bdl_game_id"],
            "StartPeriod": 0,
            "EndPeriod": 14,
            "StartRange": 0,
            "EndRange": 2147483647,
            "RangeType": 0,
        })
        player_rows = self._result_set(payload, "PlayerStats")
        return [self._normalize_box_row(pr, game) for pr in player_rows]

    # ── normalization ───────────────────────────────────────────────────────
    def _normalize_box_row(self, pr: dict, game: dict) -> dict:
        team = (pr.get("TEAM_ABBREVIATION") or "").strip()
        minutes_raw = pr.get("MIN")
        return {
            "bdl_game_id": game["bdl_game_id"],
            "game_id": game["game_id"],
            "game_date": game["game_date"],
            "tipoff_utc": game["tipoff_utc"],
            "player_id": f"nba-{pr.get('PLAYER_ID')}",
            "player_display_name": (pr.get("PLAYER_NAME") or "").strip(),
            "team": team,
            "opponent": (game["away_team"] if team == game["home_team"]
                         else game["home_team"]),
            "is_home": team == game["home_team"],
            "position": (pr.get("START_POSITION") or "").strip() or None,
            "minutes": parse_minutes(minutes_raw) if minutes_raw is not None else 0.0,
            "minutes_raw": minutes_raw,
            "pts": _int_or_none(pr.get("PTS")),
            "rebounds": _int_or_none(pr.get("REB")),
            "assists": _int_or_none(pr.get("AST")),
            "fg3m": _int_or_none(pr.get("FG3M")),
            "fgm": _int_or_none(pr.get("FGM")),
            "fga": _int_or_none(pr.get("FGA")),
            "ftm": _int_or_none(pr.get("FTM")),
            "fta": _int_or_none(pr.get("FTA")),
            "oreb": _int_or_none(pr.get("OREB")),
            "tov": _int_or_none(pr.get("TOV")),
            "_fixture": False,
            "source": self.source,
        }
