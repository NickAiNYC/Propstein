"""Box-score providers — one normalized row per player-game.

DATA-SOURCE DECISION (Phase 0.5 gate, user-approved; see DECISIONS.md):

  The ONLY licensed NBA source wired for v1 is the balldontlie NBA API
  (https://docs.balldontlie.io). Games metadata is free tier; BOX SCORES
  (/v1/stats) require the ALL-STAR paid tier ($9.99/mo at decision time)
  or higher. Scraping NBA.com / ESPN / stat-site endpoints is FORBIDDEN
  by the project ToS rule.

  Fail-closed contract (mirrors scripts/fetch_nba.py exit semantics):
    - no BALLDONTLIE_API_KEY  -> MissingKeyError          (CLI exit 2)
    - HTTP 401                -> MissingKeyError          (CLI exit 2)
    - HTTP 402/403            -> TierError                (CLI exit 3)
    - HTTP 429                -> RateLimitError           (CLI exit 4)
    - anything else           -> ProviderNetworkError     (CLI exit 5)
  A provider error NEVER produces partial "best effort" model input.

  Swapping in another licensed provider later means implementing
  `fetch_range()` against the same normalized row schema below — the
  features/model/eval/publish layers never learn which provider ran.

Normalized row schema (one dict per player-game):
  bdl_game_id, game_id, game_date (ET calendar date, YYYY-MM-DD),
  tipoff_utc, player_id, player_display_name, team, opponent, is_home,
  position, minutes (float, 0.0 for DNP), minutes_raw, pts, rebounds,
  assists, fg3m, fgm, fga, ftm, fta, oreb, tov, _fixture, source
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable

from .timeutils import et_date_key

BASE_URL = "https://api.balldontlie.io/v1"
REQUEST_SPACING_SECONDS = 13.0   # free-tier 5 req/min; paid keys upgrade server-side
MAX_PAGES_PER_GAME = 50


class MissingKeyError(RuntimeError):
    """No API key configured (or key rejected). Fail closed."""


class TierError(RuntimeError):
    """The configured balldontlie tier lacks box-score access (HTTP 402/403)."""


class RateLimitError(RuntimeError):
    """Rate limit exhausted after honouring Retry-Once."""


class ProviderNetworkError(RuntimeError):
    """Network/protocol failure — no data can be trusted from this run."""


def _stat_field(stat: dict, key: str):
    val = stat.get(key)
    return val


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_minutes(val) -> float:
    """balldontlie 'min' is 'MM:SS' (e.g. '34:30'); also tolerates floats.
    Unparseable -> 0.0 (DNP semantics), never a silent crash."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip()
    if ":" in text:
        try:
            minutes, seconds = text.split(":")[:2]
            return float(minutes) + float(seconds) / 60.0
        except (ValueError, TypeError):
            return 0.0
    return _to_float(text) or 0.0


class BalldontlieProvider:
    """Licensed balldontlie NBA box scores. Fail-closed, rate-limited, paginated.

    `transport` and `sleep_fn` are injectable for offline tests; production
    leaves them at the urllib defaults.
    """

    source = "balldontlie"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        spacing_seconds: float = REQUEST_SPACING_SECONDS,
        transport: Callable[[str], tuple[int, dict]] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self.api_key = (api_key or os.environ.get("BALLDONTLIE_API_KEY", "")).strip()
        self.base_url = base_url.rstrip("/")
        self.spacing = spacing_seconds
        self._transport = transport or self._default_transport
        self._sleep = sleep_fn or time.sleep

    # ── transport ───────────────────────────────────────────────────────────
    @staticmethod
    def _default_transport(url: str) -> tuple[int, dict]:
        req = urllib.request.Request(url, headers={})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except Exception as exc:  # network layer
            raise ProviderNetworkError(f"network error: {exc}") from exc

    def _get(self, path: str) -> dict:
        if not self.api_key:
            raise MissingKeyError(
                "BALLDONTLIE_API_KEY is not set — fail-closed, nothing fetched."
            )
        url = f"{self.base_url}{path}"
        status, payload = self._transport(url)
        if status == 429:
            self._sleep(60.0)
            status, payload = self._transport(url)
            if status == 429:
                raise RateLimitError("balldontlie rate limit exhausted after retry")
        if status == 401:
            raise MissingKeyError("balldontlie rejected the API key (HTTP 401)")
        if status in (402, 403):
            raise TierError(
                "balldontlie tier lacks this endpoint (HTTP %s). Box scores (/v1/stats) "
                "need the ALL-STAR paid tier or higher per the Phase 0.5 gate." % status
            )
        if status != 200:
            raise ProviderNetworkError(f"balldontlie HTTP {status} on {path}")
        self._sleep(self.spacing)
        return payload or {}

    # ── public API ──────────────────────────────────────────────────────────
    def fetch_range(self, dates: Iterable[str]) -> dict:
        """Fetch games + full box scores for a list of ET calendar dates.

        Returns {"rows": [...], "games": [...], "meta": {...}}.
        """
        rows: list[dict] = []
        games: list[dict] = []
        for date in dates:
            day_games = self._fetch_games(date)
            games.extend(day_games)
            for game in day_games:
                rows.extend(self._fetch_game_stats(game))
        return {
            "rows": rows,
            "games": games,
            "meta": {
                "source": self.source,
                "dates": list(dates),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "_fixture": False,
            },
        }

    def _fetch_games(self, date: str) -> list[dict]:
        payload = self._get(f"/games?dates[]={date}&per_page=100")
        games = []
        for g in payload.get("data") or []:
            games.append(self._normalize_game(g))
        return games

    def _fetch_game_stats(self, game: dict) -> list[dict]:
        bdl_id = str(game["bdl_game_id"])
        season = game["game_date"][:4]
        rows: list[dict] = []
        cursor = ""
        for _ in range(MAX_PAGES_PER_GAME):
            path = f"/stats?game_ids[]={bdl_id}&season={season}&per_page=100"
            if cursor:
                path += f"&cursor={cursor}"
            payload = self._get(path)
            for stat in payload.get("data") or []:
                rows.append(self._normalize_stat(stat, game))
            meta = payload.get("meta") or {}
            cursor = meta.get("next_cursor") or ""
            if not cursor:
                break
        return rows

    # ── normalization ───────────────────────────────────────────────────────
    @staticmethod
    def _normalize_game(game: dict) -> dict:
        tipoff = game.get("date") or game.get("datetime")
        return {
            "bdl_game_id": game.get("id"),
            "game_id": f"bdl-{game.get('id')}",
            "game_date": et_date_key(tipoff),
            "tipoff_utc": tipoff,
            "status": game.get("status"),
            "home_team": (game.get("home_team") or {}).get("abbreviation"),
            "away_team": (game.get("visitor_team") or {}).get("abbreviation"),
            "home_team_score": game.get("home_team_score"),
            "away_team_score": game.get("visitor_team_score"),
            "_fixture": False,
            "source": "balldontlie",
        }

    def _normalize_stat(self, stat: dict, game: dict) -> dict:
        player = stat.get("player") or {}
        team = stat.get("team") or {}
        minutes_raw = _stat_field(stat, "min")
        minutes = parse_minutes(minutes_raw)
        return {
            "bdl_game_id": game["bdl_game_id"],
            "game_id": game["game_id"],
            "game_date": game["game_date"],
            "tipoff_utc": game["tipoff_utc"],
            "player_id": f"bdl-{player.get('id')}",
            "player_display_name": (
                f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            ),
            "team": team.get("abbreviation"),
            "opponent": (
                game["away_team"] if team.get("abbreviation") == game["home_team"]
                else game["home_team"]
            ),
            "is_home": team.get("abbreviation") == game["home_team"],
            "position": player.get("position"),
            "minutes": minutes if minutes is not None else 0.0,
            "minutes_raw": minutes_raw,
            "pts": _stat_field(stat, "pts"),
            "rebounds": _stat_field(stat, "reb"),
            "assists": _stat_field(stat, "ast"),
            "fg3m": _stat_field(stat, "fg3m"),
            "fgm": _stat_field(stat, "fgm"),
            "fga": _stat_field(stat, "fga"),
            "ftm": _stat_field(stat, "ftm"),
            "fta": _stat_field(stat, "fta"),
            "oreb": _stat_field(stat, "oreb"),
            "tov": _stat_field(stat, "tov"),
            "_fixture": False,
            "source": self.source,
        }


class FixtureProvider:
    """Committed research fixtures (_fixture: true rows). Never passes as live.

    Reads the committed viewer fixture files so tests and offline demos run
    against the exact schema the terminal already ships. Real attribution
    rules apply: fixture data is synthetic and every row keeps its flag.
    """

    source = "committed_fixtures"

    def __init__(self, games_file: str, boxscore_file: str | None = None):
        self.games_file = games_file
        self.boxscore_file = boxscore_file

    def fetch_range(self, dates: Iterable[str] | None = None) -> dict:
        with open(self.games_file, "r", encoding="utf-8") as fh:
            games_payload = json.load(fh)
        games_raw = games_payload if isinstance(games_payload, list) else games_payload.get("games", [])
        games = []
        for g in games_raw:
            games.append({
                "bdl_game_id": g.get("bdl_game_id") or g.get("game_id"),
                "game_id": g.get("game_id"),
                "game_date": g.get("gameday") or g.get("game_date"),
                "tipoff_utc": g.get("tipoff_utc"),
                "status": g.get("status", "Final"),
                "home_team": g.get("home_team"),
                "away_team": g.get("away_team"),
                "home_team_score": g.get("home_team_score"),
                "away_team_score": g.get("away_team_score"),
                "_fixture": True,
                "source": self.source,
            })
        rows = []
        if self.boxscore_file:
            with open(self.boxscore_file, "r", encoding="utf-8") as fh:
                box_payload = json.load(fh)
            box_rows = box_payload.get("rows", []) if isinstance(box_payload, dict) else box_payload
            for r in box_rows:
                game = next((g for g in games if g["game_id"] == r.get("game_id")), {})
                rows.append({
                    **r,
                    "game_date": r.get("game_date") or game.get("game_date"),
                    "tipoff_utc": r.get("tipoff_utc") or game.get("tipoff_utc"),
                    "is_home": r.get("is_home", r.get("team") == game.get("home_team")),
                    "opponent": r.get("opponent") or (
                        game.get("home_team") if r.get("team") != game.get("home_team")
                        else game.get("away_team")
                    ),
                    "_fixture": True,
                    "source": r.get("source", self.source),
                })
        return {
            "rows": rows,
            "games": games,
            "meta": {"source": self.source, "_fixture": True,
                     "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        }


class SyntheticSeasonProvider:
    """Deterministic synthetic season for offline demos and tests.

    Generates a small league (10 invented teams, 8 invented players each)
    over N days with a KNOWN generative process (role minutes, per-player
    ppm, pace effects, blowout trims, occasional DNP + Out injuries), plus
    two synthetic book feeds for de-vig comparison. Every row is
    _fixture: true and player/team names are invented — no real attribution.
    """

    source = "synthetic_season"

    TEAM_ABBRS = ["ALP", "BRV", "CHR", "DLX", "EAG", "FLC", "GLD", "HWK", "ION", "JSN"]
    POSITIONS = ["G1", "G2", "W1", "W2", "B1", "B2", "B3", "B4"]
    ROLE_MINUTES = {"G1": 33.0, "G2": 31.0, "W1": 28.0, "W2": 26.0,
                    "B1": 22.0, "B2": 19.0, "B3": 16.0, "B4": 13.0}

    def __init__(self, start_date: str, n_days: int = 45, seed: int = 20261022):
        import numpy as np

        self.start_date = start_date
        self.n_days = n_days
        self.rng = np.random.default_rng(seed)
        self.players = {
            abbr: [
                {
                    "player_id": f"syn-{abbr.lower()}-{pos.lower()}",
                    "player_display_name": f"{abbr} {pos}",
                    "team": abbr,
                    "position": pos,
                    "role_minutes": self.ROLE_MINUTES[pos],
                    "ppm_base": float(self.rng.uniform(0.42, 0.72)),
                    "ppm_sd": float(self.rng.uniform(0.09, 0.16)),
                }
                for pos in self.POSITIONS
            ]
            for abbr in self.TEAM_ABBRS
        }
        # Team pace ratios: possessions per game vs league average.
        self.team_pace_ratio = {
            abbr: float(self.rng.uniform(0.93, 1.07)) for abbr in self.TEAM_ABBRS
        }
        # Stable Out list per team (a starter or two occasionally sits).
        self.chronic_out = {
            abbr: (self.rng.random() < 0.25 and "B4" or None) for abbr in self.TEAM_ABBRS
        }

    def _dates(self) -> list[str]:
        from datetime import date, timedelta

        y, m, d = (int(x) for x in self.start_date.split("-"))
        base = date(y, m, d)
        return [(base + timedelta(days=i)).isoformat() for i in range(self.n_days)]

    def fetch_range(self, dates: Iterable[str] | None = None) -> dict:
        rows: list[dict] = []
        games: list[dict] = []
        injuries: list[dict] = []
        game_odds: list[dict] = []
        day_index = 0
        for date in self._dates():
            # 4 games per night, rotating pairings of the 10 teams.
            order = list(self.TEAM_ABBRS)
            self.rng.shuffle(order)
            for gi in range(4):
                away, home = order[2 * gi], order[2 * gi + 1]
                game_id = f"syn-{date.replace('-', '')}-{home}-{away}"
                games.append({
                    "bdl_game_id": game_id,
                    "game_id": game_id,
                    "game_date": date,
                    "tipoff_utc": f"{date}T23:30:00Z",
                    "status": "Final",
                    "home_team": home,
                    "away_team": away,
                    "_fixture": True,
                    "source": self.source,
                })
                away_out, home_out = [], []
                for team, out_list in ((away, away_out), (home, home_out)):
                    for p in self.players[team]:
                        row, dnp = self._simulate_player_game(p, game_id, date,
                                                              home=team == home)
                        if dnp is not None:
                            out_list.append((p, dnp))
                        else:
                            rows.append(row)
                injuries.extend(self._injuries_for_game(game_id, date, home, away, out_list))
                game_odds.extend(self._odds_for_game(game_id, date, home, away, rows))
            day_index += 1
        return {
            "rows": rows,
            "games": games,
            "injuries": injuries,
            "odds": game_odds,
            "meta": {"source": self.source, "_fixture": True,
                     "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        }

    # ── generative pieces ───────────────────────────────────────────────────
    def _simulate_player_game(self, p: dict, game_id: str, date: str, home: bool):
        rng = self.rng
        minutes = max(4.0, rng.normal(p["role_minutes"], 3.2))
        # Blowouts trim minutes ~12% with prob 0.12.
        if rng.random() < 0.12:
            minutes *= 0.88
        if home:
            minutes *= 1.01
        # ~2% rest/DNP nights.
        if rng.random() < 0.02:
            return None, p
        ppm = max(0.05, rng.normal(p["ppm_base"], p["ppm_sd"]))
        pts = int(round(minutes * ppm * float(rng.gamma(6.0, 1 / 6.0))))
        fga = int(round(pts / rng.uniform(1.05, 1.5)))
        fta = int(round(pts * rng.uniform(0.08, 0.25)))
        oreb = int(round(minutes * rng.uniform(0.03, 0.09)))
        tov = int(round(minutes * rng.uniform(0.05, 0.13)))
        return {
            "bdl_game_id": game_id,
            "game_id": game_id,
            "game_date": date,
            "tipoff_utc": f"{date}T23:30:00Z",
            "player_id": p["player_id"],
            "player_display_name": p["player_display_name"],
            "team": p["team"],
            "opponent": "",  # filled by dataset join via games
            "is_home": home,
            "position": p["position"],
            "minutes": float(minutes),
            "minutes_raw": f"{int(minutes)}:{int(round((minutes % 1) * 60)):02d}",
            "pts": pts,
            "rebounds": int(round(minutes * rng.uniform(0.10, 0.22))),
            "assists": int(round(minutes * rng.uniform(0.08, 0.28))),
            "fg3m": int(round(pts * rng.uniform(0.05, 0.35))),
            "fgm": int(round(fga * rng.uniform(0.4, 0.55))),
            "fga": fga,
            "ftm": int(round(fta * rng.uniform(0.7, 0.9))),
            "fta": fta,
            "oreb": oreb,
            "tov": tov,
            "_fixture": True,
            "source": self.source,
        }, None

    def _injuries_for_game(self, game_id, date, home, away, out_list):
        if not out_list:
            return []
        injuries = []
        for p, _dnp in out_list:
            injuries.append({
                "injury_id": f"syn-inj-{game_id}-{p['player_id']}",
                "player_id": p["player_id"],
                "player_name": p["player_display_name"],
                "team": p["team"],
                "game_id": game_id,
                "report_status": "Out",
                "as_of": f"{date}T21:00:00Z",
                "_fixture": True,
            })
        return injuries

    def _odds_for_game(self, game_id, date, home, away, all_rows):
        """Two synthetic independent books quoting points lines for starters.

        Market line = player's true mean points + noise, priced near -110/-110
        with small book-to-book dispersion — good enough for de-vig demos,
        deliberately imperfect so the walk-forward comparison is honest.
        """
        odds = []
        booked = ("Book One", "Book Two")
        for p in self.players[home] + self.players[away]:
            if p["position"] in ("B3", "B4"):
                continue  # books only quote rotation players
            expected_pts = p["ppm_base"] * self.ROLE_MINUTES[p["position"]]
            true_line = expected_pts * float(self.rng.uniform(0.96, 1.04))
            for bi, book in enumerate(booked):
                line = round(true_line + float(self.rng.normal(0, 1.1)) * (1 if bi else -1), 1)
                if line < 4.5:
                    line = 4.5
                over_odds, under_odds = self._pair_around(line, true_line)
                odds.append({
                    "quote_id": f"synq-{game_id}-{p['player_id']}-{book.replace(' ', '')}",
                    "book": book,
                    "player_id": p["player_id"],
                    "player_name": p["player_display_name"],
                    "team": p["team"],
                    "game_id": game_id,
                    "market": "points",
                    "line": line,
                    "over_odds": over_odds,
                    "under_odds": under_odds,
                    "observed_at": f"{date}T22:45:00Z",
                    "verified": True,
                    "_fixture": True,
                    "source": "synthetic book feed (not a sportsbook quote)",
                })
        return odds

    def _pair_around(self, line: float, true_mean: float):
        """Price a pair around the market's view; slight vig, slight error."""
        import numpy as np

        edge = true_mean - line  # books shade toward the true mean with noise
        p_over = float(np.clip(0.5 + edge / 18.0 + self.rng.normal(0, 0.02), 0.3, 0.7))
        vig = 1.045
        p_over_vig = p_over * vig
        p_under_vig = (1 - p_over) * vig
        over_odds = self._prob_to_american(p_over_vig)
        under_odds = self._prob_to_american(p_under_vig)
        return over_odds, under_odds

    @staticmethod
    def _prob_to_american(p: float) -> int:
        p = min(max(p, 0.01), 0.99)
        if p >= 0.5:
            return int(round(-100.0 * p / (1.0 - p)))
        return int(round(100.0 * (1.0 - p) / p))
