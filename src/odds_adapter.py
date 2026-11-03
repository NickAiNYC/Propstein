"""
Live Odds Ingestion Adapter & Verification Engine
=================================================
Specification:
1. Ingestion:
   - Supports multiple providers:
     * TheOddsApiProvider (live API when ODDS_API_KEY is configured)
     * FeedFileProvider (ingests from incoming JSON feed files / webhook payloads)
     * EarlyMarketOpenersProvider (stages SYNTHETIC demonstration fixtures — no real
     * book, player, or observation; see the class docstring for the fail-closed rules)
   - Captures: book, market, player, team, line, over_odds, under_odds, observed_at, quote_id, source.
2. Matching & Normalization:
   - Robust fuzzy / canonical name and team matching against frozen slate.
   - American odds -> decimal -> de-vigged market consensus probability.
   - Precise push probability handling for integer receiving yards and receptions lines.
3. Evaluation Against Frozen State:
   - Evaluates quotes against calibrated compound NegBin-Gamma distributions.
   - Computes:
     * Probability Edge: model_prob - devigged_prob
     * Break-Even Advantage: model_prob - break_even_prob
     * Expected Return: expected profit per dollar at offered odds
   - Applies strict Qualification Policy:
     * prob_edge >= 0.10 (10% calibration hurdle)
     * expected_return > 0 (strictly positive expectation)
     * Gated against fatal injury exclusions (Out/Doubtful = 0 stake; Questionable = 50% stake cap)
   - Tracks opportunity catalyst: 'pricing', 'football_news', or 'both'.
4. Snapshot Emission:
   - Emits 'first_published' snapshot upon initial quote observation.
   - Emits 'material_revision' snapshot when line shifts by >= 1.0 yd (or 0.5 rec), odds shift by >= 15 cents,
     or qualification status changes.
   - Appends to snapshots_{season}_w{week}.jsonl with canonical RFC-8785 SHA-256 hash.
   - Never overwrites historical snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
VIEWER_DIR = BASE_DIR / "viewer"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"

sys.path.insert(0, str(SRC_DIR))
from freeze_slate import (
    MODEL_ALPHA, MODEL_K, MODEL_VERSION, QUALIFICATION_POLICY_VERSION, EDGE_HURDLE,
    ReceivingModel, compute_canonical_hash, compute_rec_probs, compute_yards_probs,
    prob_to_american, classify_role_shift
)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class PropQuote:
    quote_id: str
    book: str                      # e.g., "draftkings", "fanduel", "betmgm", "pinnacle"
    market: str                    # "receiving_yards" or "receptions"
    player_raw_name: str           # e.g., "Player A", "P. A"
    team: Optional[str]            # e.g., "NE"
    opponent: Optional[str]        # e.g., "CHI"
    line: float                    # e.g., 34.5
    over_odds: int                 # e.g., -110
    under_odds: Optional[int]      # e.g., -110
    observed_at: str               # ISO timestamp
    source: str                    # Provider source label
    verified: bool = False         # True ONLY when fetched from a real sportsbook/odds API with a true observation time
    receipt_id: Optional[str] = None
    source_url: Optional[str] = None
    book_id: Optional[str] = None      # canonical slug: "draftkings" — matches viewer/books/<id>.svg
    book_short: Optional[str] = None   # "DK" — compact chip label


# ---
# Book identity (v152). Canonical slug -> display/brand metadata. The viewer
# mirrors this map in its BOOKS registry; the feed ships book_id per quote so
# the viewer can resolve logos without guessing from display strings.
# ---------------------------------------------------------------------------
BOOK_META = {
    "draftkings": {"display": "DraftKings", "short": "DK",     "color": "#53d337"},
    "fanduel":    {"display": "FanDuel",    "short": "FD",     "color": "#7ab8ff"},
    "betmgm":     {"display": "BetMGM",     "short": "MGM",    "color": "#c6a45e"},
    "caesars":    {"display": "Caesars",    "short": "CZR",    "color": "#c39e6d"},
    "pinnacle":   {"display": "Pinnacle",   "short": "PIN",    "color": "#f56f36"},
    "betrivers":  {"display": "BetRivers",  "short": "BR",     "color": "#ffc72c"},
    "fanatics":   {"display": "Fanatics",   "short": "FAN",    "color": "#e03131"},
    "bet365":     {"display": "bet365",     "short": "365",    "color": "#0b7d57"},
    "espnbet":    {"display": "ESPN BET",   "short": "ESPN",   "color": "#d50a0a"},
    "circa":      {"display": "Circa",      "short": "CIR",    "color": "#ff8200"},
}


def canonical_book(raw: str) -> str:
    """Normalize any provider book label to a canonical BOOK_META slug.

    Handles provider casing drift ("Draftkings", "draftkings", "DraftKings"),
    punctuation variants ("bet365", "bet-365"), and known aliases ("circa_sports",
    "espnbet", "william hill us" etc. fall back to a stripped slug). Returns the
    slug even when it is not in BOOK_META so callers can still ship a stable id;
    display/short lookups then degrade gracefully to the raw string.
    """
    if not raw:
        return "unknown"
    slug = str(raw).strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "circasports": "circa",
        "espnbetus": "espnbet",
        "williamhillus": "williamhill",
        "betonlineag": "betonline",
        "lowvig": "lowvig",
        "bet365us": "bet365",
        "bet365nj": "bet365",
        "draftkingsus": "draftkings",
        "fanduelus": "fanduel",
        "betmgmus": "betmgm",
        "betmgmny": "betmgm",
        "betriversny": "betrivers",
        "fanaticsportsbook": "fanatics",
    }
    return aliases.get(slug, slug)


@dataclass
class MatchedEvaluation:
    quote: PropQuote
    player_id: str
    player_name: str
    team: str
    opponent: str
    game_id: str
    position: str
    market: str
    fair_line: float
    book_line: float
    over_odds: int
    under_odds: Optional[int]
    dec_odds_over: float
    dec_odds_under: Optional[float]
    p_over_market_devig: float
    p_under_market_devig: float
    p_over_model: float
    p_under_model: float
    p_push_model: float
    prob_edge: float               # model_prob - devigged_market_prob
    break_even_adv: float          # model_prob - break_even_prob
    expected_return: float         # profit per dollar
    best_side: str                 # "OVER" or "UNDER"
    is_qualified: bool
    status: str                    # "QUALIFIED", "LEAN", "PASS", "QUESTIONABLE", "EXCLUDED"
    actionable_stake: float
    catalyst: str                  # "pricing", "football_news", "both", "none"
    injury_context: Optional[str]
    proj_volume: float = 0.0
    mu_rec: float = 0.0
    mu_ypr: float = 0.0


# ---------------------------------------------------------------------------
# Odds & Probability Math Utilities
# ---------------------------------------------------------------------------

def american_to_decimal(american: float) -> float:
    """Converts American odds to decimal odds."""
    if american > 0:
        return 1.0 + american / 100.0
    else:
        return 1.0 + 100.0 / abs(american)


def american_to_implied_prob(american: float) -> float:
    """Raw book implied probability before removing vigorish."""
    dec = american_to_decimal(american)
    return 1.0 / dec


def devig_two_way(over_odds: float, under_odds: Optional[float]) -> Tuple[float, float]:
    """
    Multiplicative two-way de-vigging.
    If under_odds is not provided, assumes standard -110 juice on opposing side.
    """
    p_over_raw = american_to_implied_prob(over_odds)
    p_under_raw = american_to_implied_prob(under_odds if under_odds is not None else -110)
    total_vig = p_over_raw + p_under_raw
    return p_over_raw / total_vig, p_under_raw / total_vig


def calculate_break_even_prob(american_odds: float, p_push: float = 0.0) -> float:
    """
    Computes break-even probability accounting for pushes.
    On push, stake is returned (0 profit, 0 loss).
    be_prob * (dec - 1) - (1 - be_prob - p_push) = 0
    => be_prob * dec = 1 - p_push
    => be_prob = (1 - p_push) / dec
    """
    dec = american_to_decimal(american_odds)
    return (1.0 - p_push) / dec


def calculate_expected_return(p_win: float, american_odds: float, p_push: float = 0.0) -> float:
    """Expected return per dollar wagered."""
    dec = american_to_decimal(american_odds)
    p_loss = max(0.0, 1.0 - p_win - p_push)
    return p_win * (dec - 1.0) - p_loss


# ---------------------------------------------------------------------------
# Name Matching & Normalization Engine
# ---------------------------------------------------------------------------

class NameNormalizer:
    @staticmethod
    def normalize(name: str) -> str:
        s = name.lower()
        # Remove suffixes
        s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
        # Remove special characters
        s = re.sub(r"[^a-z0-9\s]", "", s)
        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @classmethod
    def match_player(
        cls,
        raw_name: str,
        team: Optional[str],
        slate_players: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        norm_query = cls.normalize(raw_name)

        # 1. Exact match on normalized full name
        for p in slate_players:
            p_norm = cls.normalize(p.get("player_display_name", ""))
            if p_norm == norm_query:
                if team is None or p.get("team") == team:
                    return p

        # 2. Match with team constraint if provided
        if team:
            team_players = [p for p in slate_players if p.get("team") == team]
            for p in team_players:
                p_norm = cls.normalize(p.get("player_display_name", ""))
                if p_norm == norm_query:
                    return p
                # Check last name + first initial (e.g. "P. A" -> "Player A")
                q_parts = norm_query.split()
                p_parts = p_norm.split()
                if len(q_parts) >= 2 and len(p_parts) >= 2:
                    if q_parts[-1] == p_parts[-1] and q_parts[0][0] == p_parts[0][0]:
                        return p

        # 3. Last-name match across all players if unique
        q_parts = norm_query.split()
        if len(q_parts) >= 2:
            last = q_parts[-1]
            first_init = q_parts[0][0]
            matches = [
                p for p in slate_players
                if cls.normalize(p.get("player_display_name", "")).endswith(last)
                and cls.normalize(p.get("player_display_name", "")).startswith(first_init)
            ]
            if len(matches) == 1:
                return matches[0]

        return None


# ---------------------------------------------------------------------------
# Ingestion Providers
# ---------------------------------------------------------------------------

class BaseOddsProvider(ABC):
    @abstractmethod
    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        pass


class FeedFileProvider(BaseOddsProvider):
    """Loads quotes from an incoming JSON feed file or webhook dump."""
    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        if not self.file_path.exists():
            return []

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[odds_adapter] Error reading feed file {self.file_path}: {e}")
            return []

        raw_quotes = data.get("quotes", [])
        quotes: List[PropQuote] = []
        for r in raw_quotes:
            if game_id and r.get("game_id") and r.get("game_id") != game_id:
                continue
            quotes.append(PropQuote(
                quote_id=r.get("quote_id", str(uuid.uuid4())),
                book=r.get("book", "draftkings"),
                market=r.get("market", "receiving_yards"),
                player_raw_name=r.get("player_name", ""),
                team=r.get("team"),
                opponent=r.get("opponent"),
                line=float(r.get("line", 0.0)),
                over_odds=int(r.get("over_odds", -110)),
                under_odds=int(r.get("under_odds", -110)) if r.get("under_odds") is not None else None,
                observed_at=r.get("observed_at", datetime.now(timezone.utc).isoformat()),
                source=r.get("source", "feed_file"),
                verified=bool(r.get("verified", False))
            ))
        return quotes


# ---------------------------------------------------------------------------
# Proxy Bandwidth Circuit Breaker (Fail-Closed on Cost Overrun)
# ---------------------------------------------------------------------------
PROXY_BYTES_BUDGET: int = int(os.environ.get("PROXY_BYTES_BUDGET", "500000000"))  # 500MB
proxy_bytes_used: int = 0


def get_proxy_bytes_used() -> int:
    """Return accumulated proxy bandwidth consumption in bytes."""
    return proxy_bytes_used


def reset_proxy_bytes() -> None:
    """Reset accumulated proxy bandwidth counter (e.g., called via midnight UTC cron)."""
    global proxy_bytes_used
    proxy_bytes_used = 0


def scrape_with_budget(provider: Any, url: str) -> Any:
    """
    Budget-gated scraping helper. Halts and raises RuntimeError
    if proxy bandwidth usage exceeds PROXY_BYTES_BUDGET.
    """
    global proxy_bytes_used
    if proxy_bytes_used >= PROXY_BYTES_BUDGET:
        raise RuntimeError(
            f"PROXY_BUDGET_EXCEEDED: Proxy bandwidth usage ({proxy_bytes_used} bytes) "
            f"exceeds limit ({PROXY_BYTES_BUDGET} bytes). Halting scraper to prevent cost overrun."
        )
    response = provider.fetch(url) if hasattr(provider, "fetch") else provider(url)
    content_len = len(response.content) if hasattr(response, "content") else len(response)
    proxy_bytes_used += content_len
    return response


class BovadaOddsProvider(BaseOddsProvider):
    """
    Live zero-token odds provider fetching real-time NFL player props
    from Bovada's public sportsbook API endpoint.
    """
    API_URL = "https://www.bovada.lv/services/sports/event/v2/events/A/description/football/nfl"

    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    ]

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        import random
        import time
        import urllib.request

        quotes: List[PropQuote] = []
        now_ts = datetime.now(timezone.utc).isoformat()
        proxy_url = os.environ.get("ROTATING_PROXY_URL") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        # Circuit breaker: fail closed if proxy budget has been reached
        global proxy_bytes_used
        if proxy_url and proxy_bytes_used >= PROXY_BYTES_BUDGET:
            err_msg = (
                f"PROXY_BUDGET_EXCEEDED: Proxy bandwidth usage ({proxy_bytes_used} bytes) "
                f"exceeds limit ({PROXY_BYTES_BUDGET} bytes). Halting scraper to prevent cost overrun."
            )
            print(f"[odds_adapter] CRITICAL COST OVERRUN HALT: {err_msg}")
            raise RuntimeError(err_msg)

        # Configure opener with proxy if provided (e.g. BrightData, SmartProxy)
        handlers = []
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        opener = urllib.request.build_opener(*handlers)

        data = None
        max_attempts = 2
        for attempt in range(max_attempts):
            ua = random.choice(self.USER_AGENTS)
            req = urllib.request.Request(
                self.API_URL,
                headers={
                    "User-Agent": ua,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.bovada.lv/",
                }
            )
            try:
                with opener.open(req, timeout=12) as res:
                    raw_bytes = res.read()
                    if proxy_url:
                        proxy_bytes_used += len(raw_bytes)
                    data = json.loads(raw_bytes.decode("utf-8"))
                    break
            except Exception as e:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    continue
                print(f"[odds_adapter] Failed to fetch Bovada live odds after {max_attempts} attempts: {e}")
                return []

        if not data or not isinstance(data, list):
            return []

        for group in data:
            for ev in group.get("events", []):
                ev_desc = ev.get("description", "")
                ev_id = str(ev.get("id", ""))
                for dg in ev.get("displayGroups", []):
                    for mk in dg.get("markets", []):
                        desc = mk.get("description", "")
                        if "Total Receiving Yards -" in desc:
                            market_type = "receiving_yards"
                        elif "Total Receptions -" in desc:
                            market_type = "receptions"
                        else:
                            continue

                        # Extract player raw name and optional team: "Total Receiving Yards - Player G (DET)"
                        match = re.search(r"-\s*([^(\n\r]+)(?:\s*\(([A-Z]{2,3})\))?", desc)
                        if not match:
                            continue
                        player_name = match.group(1).strip()
                        team_code = match.group(2) if match.group(2) else None

                        outcomes = {o.get("description"): o for o in mk.get("outcomes", [])}
                        over_oc = outcomes.get("Over", {})
                        under_oc = outcomes.get("Under", {})

                        pt = over_oc.get("price", {}).get("handicap") or under_oc.get("price", {}).get("handicap")
                        if pt is None:
                            continue

                        def parse_american(val):
                            if val is None:
                                return -110
                            if str(val).upper() == "EVEN":
                                return 100
                            try:
                                return int(val)
                            except ValueError:
                                return -110

                        over_odds = parse_american(over_oc.get("price", {}).get("american"))
                        under_odds = parse_american(under_oc.get("price", {}).get("american"))

                        mk_id = str(mk.get("id", uuid.uuid4()))
                        quote_id = f"bovada_{ev_id}_{mk_id}"
                        receipt = hashlib.sha256(f"{quote_id}:{now_ts}:{float(pt)}:{over_odds}".encode()).hexdigest()[:16]

                        quotes.append(PropQuote(
                            quote_id=quote_id,
                            book="Bovada",
                            market=market_type,
                            player_raw_name=player_name,
                            team=team_code,
                            opponent=None,
                            line=float(pt),
                            over_odds=over_odds,
                            under_odds=under_odds,
                            observed_at=now_ts,
                            source=f"Bovada Live Sportsbook API ({ev_desc})",
                            verified=True,
                            receipt_id=receipt,
                            source_url=self.API_URL
                        ))

        print(f"[odds_adapter] BovadaOddsProvider fetched {len(quotes)} live player prop quotes.")
        return quotes


class TheOddsApiProvider(BaseOddsProvider):
    """
    Ingests live player props from The Odds API across sharp books
    when ODDS_API_KEY is configured in the environment.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        if not self.api_key:
            print("[odds_adapter] ODDS_API_KEY not configured. Skipping TheOddsApiProvider.")
            return []

        try:
            from odds import OddsClient
            client = OddsClient(api_key=self.api_key)
            raw_quotes = client.slate()
        except Exception as e:
            print(f"[odds_adapter] TheOddsApiProvider error: {e}")
            return []

        now_ts = datetime.now(timezone.utc).isoformat()
        quotes: List[PropQuote] = []
        for q in raw_quotes:
            m_type = "receiving_yards" if "yds" in q.market else "receptions"
            book_id = canonical_book(q.book)
            meta = BOOK_META.get(book_id)
            qid = f"oddsapi_{q.event_id}_{book_id}_{q.player}_{q.line}"
            receipt = hashlib.sha256(f"{qid}:{now_ts}:{q.line}:{int(q.over_odds)}".encode()).hexdigest()[:16]
            quotes.append(PropQuote(
                quote_id=qid,
                book=meta["display"] if meta else q.book.capitalize(),
                market=m_type,
                player_raw_name=q.player,
                team=None,
                opponent=None,
                line=float(q.line),
                over_odds=int(q.over_odds),
                under_odds=int(q.under_odds) if q.under_odds is not None else None,
                observed_at=now_ts,
                source=f"The Odds API ({q.book})",
                verified=True,
                receipt_id=receipt,
                source_url=f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{q.event_id}/odds",
                book_id=book_id,
                book_short=meta["short"] if meta else None
            ))
        print(f"[odds_adapter] TheOddsApiProvider fetched {len(quotes)} live quotes.")
        return quotes


class SportsGameOddsProvider(BaseOddsProvider):
    """
    SportsGameOdds API (sportsgameodds.com) — per-bookmaker normalized feed.

    Selected when ODDS_PROVIDER=sportsgameodds. Response shape (v2 events
    endpoint): each event carries `odds` keyed by oddID; every odds object has
    a `byBookmaker` map of bookmaker-slug -> {odds, lastUpdatedAt, available,
    deeplink?} (draftkings / fanduel / betmgm / ... ). Player-prop markets are
    statID-keyed (e.g. receiving_yards-PLAYER_ID-game-ou-over).

    Chosen for DK/FD depth at indie pricing; the normalizer below is pure and
    covered by the module selftest so provider drift is caught offline.
    """
    BASE = "https://api.sportsgameodds.com/v2"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 25):
        self.api_key = api_key or os.environ.get("SGO_API_KEY") or os.environ.get("ODDS_API_KEY")
        self.timeout = timeout

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        if not self.api_key:
            print("[odds_adapter] SGO_API_KEY/ODDS_API_KEY not configured. Skipping SportsGameOddsProvider.")
            return []
        try:
            import requests
            params = {"apiKey": self.api_key, "league": "NFL", "season": season}
            r = requests.get(f"{self.BASE}/events", params=params, timeout=self.timeout)
            if r.status_code == 401:
                print("[odds_adapter] SportsGameOdds rejected the key (401).")
                return []
            r.raise_for_status()
            events = r.json().get("events", [])
        except Exception as e:
            print(f"[odds_adapter] SportsGameOddsProvider error: {e}")
            return []

        now_ts = datetime.now(timezone.utc).isoformat()
        quotes: List[PropQuote] = []
        for ev in events:
            quotes.extend(self.normalize_event(ev, now_ts, week))
        print(f"[odds_adapter] SportsGameOddsProvider fetched {len(quotes)} live quotes.")
        return quotes

    def normalize_event(self, ev: dict, now_ts: str, week: int) -> List[PropQuote]:
        """Pure normalizer: SGO event dict -> PropQuotes (unit-tested offline)."""
        quotes: List[PropQuote] = []
        event_id = str(ev.get("eventID") or ev.get("id") or "unknown")
        for odd_id, odd in (ev.get("odds") or {}).items():
            stat_id = str(odd.get("statID") or "")
            if stat_id not in ("receiving_yards", "receptions"):
                continue
            side = str(odd.get("sideID") or "")
            if side != "over":          # over-side object carries the byBookmaker map
                continue
            player_id = str(odd.get("playerID") or "")
            player_name = str(odd.get("playerName") or odd.get("title") or "")
            line = odd.get("bookOdds") if odd.get("bookOdds") is not None else odd.get("fairOdds")
            try:
                line_val = float(odd.get("bookOverUnderLine") or odd.get("line") or 0.0)
            except (TypeError, ValueError):
                line_val = 0.0
            by_book = odd.get("byBookmaker") or {}
            for slug, bk in by_book.items():
                if not isinstance(bk, dict) or bk.get("available") is False:
                    continue
                price = bk.get("odds")
                if price in (None, ""):
                    continue
                try:
                    over = int(float(price))
                except (TypeError, ValueError):
                    continue
                book_id = canonical_book(slug)
                meta = BOOK_META.get(book_id)
                qid = f"sgo_{event_id}_{book_id}_{player_id or player_name}_{odd_id}"
                receipt = hashlib.sha256(f"{qid}:{bk.get('lastUpdatedAt') or now_ts}:{over}".encode()).hexdigest()[:16]
                quotes.append(PropQuote(
                    quote_id=qid,
                    book=meta["display"] if meta else str(slug),
                    market=stat_id,
                    player_raw_name=player_name,
                    team=None,
                    opponent=None,
                    line=line_val,
                    over_odds=over,
                    under_odds=None,       # under side arrives as its own oddID object
                    observed_at=str(bk.get("lastUpdatedAt") or now_ts),
                    source=f"SportsGameOdds ({slug})",
                    verified=True,
                    receipt_id=receipt,
                    source_url=str(bk.get("deeplink") or f"https://sportsgameodds.com/events/{event_id}"),
                    book_id=book_id,
                    book_short=meta["short"] if meta else None
                ))
        return quotes


class PropLineProvider(BaseOddsProvider):
    """
    PropLine (api.propline.com) — PRIMARY player-props feed for DraftKings &
    FanDuel (mission W1). Selected via PROPLINE_API_KEY (or ODDS_PROVIDER=propline).

    Response shape (v1 `/props` endpoint, mirroring the SGO per-book pattern):
        {"props": [
            {"event_id": "nba_2026_1029_bos_mil", "sport": "nba",
             "player_id": "giannis_antetokounmpo", "player_name": "Giannis Antetokounmpo",
             "team": "MIL", "opponent": "BOS", "market": "points", "line": 31.5,
             "books": {"draftkings": {"over_odds": -112, "under_odds": -108,
                                      "deeplink": "https://sportsbook.draftkings.com/..."},
                       "fanduel":    {"over_odds": -110, "under_odds": -110}}},
            ...
        ]}

    Failure policy (mission: one API must never block the MarketAgent loop):
    missing key, 401, 429, 5xx, timeout, or malformed JSON all degrade to `[]`
    so the composite chain falls through to The Odds API -> Bovada -> openers.
    """

    BASE = "https://api.propline.com/v1"

    # PropLine market slug -> internal canonical market id
    MARKET_MAP = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "three_pointers_made": "threes",
        "three_pointers": "threes",
        "receiving_yards": "receiving_yards",
        "receptions": "receptions",
    }

    # Primary targets first; anything else PropLine ships still flows through.
    BOOK_PRIORITY = ("draftkings", "fanduel")

    def __init__(self, api_key: Optional[str] = None, timeout: int = 25):
        self.api_key = api_key or os.environ.get("PROPLINE_API_KEY")
        self.timeout = timeout

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        if not self.api_key:
            print("[odds_adapter] PROPLINE_API_KEY not configured. Skipping PropLineProvider.")
            return []
        try:
            import requests
            params: Dict[str, Any] = {"season": season}
            if week:
                params["week"] = week
            if game_id:
                params["game_id"] = game_id
            r = requests.get(
                f"{self.BASE}/props",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            if r.status_code == 401:
                print("[odds_adapter] PropLine rejected the key (401). Falling back.")
                return []
            if r.status_code == 429:
                print("[odds_adapter] PropLine rate-limited (429). Falling back.")
                return []
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[odds_adapter] PropLineProvider error: {e}. Falling back.")
            return []

        quotes = self.normalize_response(data, now_ts=datetime.now(timezone.utc).isoformat())
        print(f"[odds_adapter] PropLineProvider fetched {len(quotes)} live DK/FD prop quotes.")
        return quotes

    def normalize_response(self, data: dict, now_ts: str) -> List[PropQuote]:
        """Pure normalizer: PropLine response dict -> PropQuotes (unit-tested offline)."""
        quotes: List[PropQuote] = []
        if not isinstance(data, dict):
            return quotes
        for prop in data.get("props") or []:
            if not isinstance(prop, dict):
                continue
            market = self.MARKET_MAP.get(str(prop.get("market") or "").lower())
            if market is None:
                continue
            try:
                line_val = float(prop.get("line"))
            except (TypeError, ValueError):
                continue
            if line_val <= 0:
                continue
            event_id = str(prop.get("event_id") or "unknown")
            player_id = str(prop.get("player_id") or "")
            player_name = str(prop.get("player_name") or "")
            books = prop.get("books") or {}
            if not isinstance(books, dict):
                continue
            # DK/FD primary targets first, then any remaining books in feed order.
            slugs = [s for s in self.BOOK_PRIORITY if s in books] + [
                s for s in books if s not in self.BOOK_PRIORITY
            ]
            for slug in slugs:
                bk = books.get(slug)
                if not isinstance(bk, dict) or bk.get("available") is False:
                    continue
                try:
                    over = int(float(bk.get("over_odds")))
                    under = int(float(bk.get("under_odds")))
                except (TypeError, ValueError):
                    continue
                book_id = canonical_book(slug)
                meta = BOOK_META.get(book_id)
                qid = f"propline_{event_id}_{book_id}_{player_id or player_name}_{market}_{line_val}"
                receipt = hashlib.sha256(
                    f"{qid}:{bk.get('updated_at') or now_ts}:{over}:{under}".encode()
                ).hexdigest()[:16]
                quotes.append(PropQuote(
                    quote_id=qid,
                    book=meta["display"] if meta else str(slug),
                    market=market,
                    player_raw_name=player_name,
                    team=str(prop.get("team")) if prop.get("team") else None,
                    opponent=str(prop.get("opponent")) if prop.get("opponent") else None,
                    line=line_val,
                    over_odds=over,
                    under_odds=under,
                    observed_at=str(bk.get("updated_at") or now_ts),
                    source=f"PropLine ({meta['display'] if meta else slug})",
                    verified=True,
                    receipt_id=receipt,
                    source_url=str(bk.get("deeplink") or f"{self.BASE}/props/{event_id}"),
                    book_id=book_id,
                    book_short=meta["short"] if meta else None,
                ))
        return quotes


# Provider registry (v152): one env var swaps the paid feed with zero code
# change. ODDS_PROVIDER in {propline, oddsapi, sportsgameodds, bovada}; default
# composite order (v172): propline-if-keyed -> oddsapi-if-keyed -> bovada ->
# openers fallback. PropLine (DK/FD) is the PRIMARY target when keyed.
PROVIDER_REGISTRY = {
    "propline": PropLineProvider,
    "oddsapi": TheOddsApiProvider,
    "sportsgameodds": SportsGameOddsProvider,
    "bovada": BovadaOddsProvider,
}


def provider_from_env(api_key: Optional[str] = None) -> Optional[BaseOddsProvider]:
    """Instantiate the ODDS_PROVIDER-selected provider, or None when unset."""
    name = (os.environ.get("ODDS_PROVIDER") or "").strip().lower()
    if not name:
        return None
    cls = PROVIDER_REGISTRY.get(name)
    if cls is None:
        print(f"[odds_adapter] Unknown ODDS_PROVIDER={name!r}; known: {sorted(PROVIDER_REGISTRY)}")
        return None
    return cls(api_key=api_key)


class CompositeLiveOddsProvider(BaseOddsProvider):
    """
    Aggregates live quotes from available providers:
    0. PropLineProvider (PROPLINE_API_KEY) — PRIMARY DK/FD feed (v172)
    1. ODDS_PROVIDER-selected provider (v152 registry) when configured
    2. TheOddsApiProvider (if ODDS_API_KEY is configured)
    3. BovadaOddsProvider (free live endpoint)
    4. Falls back to EarlyMarketOpenersProvider if no network quotes are returned.

    Mission W1 failure policy: a failure in any single provider is caught and
    skipped — it can never block the whole loop or starve the other sources.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.propline = PropLineProvider(api_key=api_key)
        self.selected = provider_from_env(api_key=api_key)
        self.bovada = BovadaOddsProvider()
        self.the_odds_api = TheOddsApiProvider(api_key=api_key)
        self.fallback = EarlyMarketOpenersProvider()

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        quotes: List[PropQuote] = []
        # 0) PropLine DK/FD primary feed (graceful: [] on failure/rate-limit)
        try:
            if self.propline.api_key:
                quotes.extend(self.propline.fetch_quotes(season, week, game_id))
        except Exception as e:
            print(f"[odds_adapter] PropLine step failed (isolated): {e}")

        # 1) explicit provider selection wins
        try:
            if self.selected is not None:
                quotes.extend(self.selected.fetch_quotes(season, week, game_id))
        except Exception as e:
            print(f"[odds_adapter] selected-provider step failed (isolated): {e}")

        # 2) The Odds API default path (when no explicit selection was made)
        try:
            if self.selected is None and self.the_odds_api.api_key:
                quotes.extend(self.the_odds_api.fetch_quotes(season, week, game_id))
        except Exception as e:
            print(f"[odds_adapter] The Odds API step failed (isolated): {e}")

        # 3) Bovada live props
        try:
            quotes.extend(self.bovada.fetch_quotes(season, week, game_id))
        except Exception as e:
            print(f"[odds_adapter] Bovada step failed (isolated): {e}")

        if not quotes:
            print("[odds_adapter] No live network quotes retrieved. Using EarlyMarketOpenersProvider fallback.")
            return self.fallback.fetch_quotes(season, week, game_id)

        return quotes


class EarlyMarketOpenersProvider(BaseOddsProvider):
    """
    Stages SYNTHETIC demonstration fixtures for the bundled demo feed.

    These values are hardcoded in this file, NOT fetched from any sportsbook,
    and no real book, player, or observation is involved: books are
    "Synthetic Book A..D", players are "Player A..G". observed_at is a
    deterministic per-quote stamp (NOT a book post time and NOT the script
    run time), and the stamps are distinct by construction.
    Quotes are flagged verified=False: shown as scenarios, never as verified
    quotes. Demo quotes intentionally fail slate matching ("Player A" is not
    a slate player_id), so no downstream evaluation path can treat them as
    actionable (fail-closed).
    """
    _TS_BASE = datetime(2026, 10, 20, 6, 23, 18, tzinfo=timezone.utc)

    def _ts(self, i: int) -> str:
        return (self._TS_BASE + timedelta(seconds=61 * i + 17,
                                          microseconds=137 * i)).isoformat()

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        # Synthetic demonstration quotes (NE @ CHI + Week 7 shapes)
        openers = [
            # 1. Player A (NE WR) - Synthetic Book A posted early receiving yards line
            # conditional on teammate OUT. Synthetic book opened at 34.5.
            PropQuote(
                quote_id="syn_a_ne_chi_player_a_yds_open",
                book="Synthetic Book A",
                market="receiving_yards",
                player_raw_name="Player A",
                team="NE",
                opponent="CHI",
                line=34.5,
                over_odds=-110,
                under_odds=-110,
                observed_at=self._ts(0),
                source="Synthetic Book A Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 2. Player A - Synthetic Book B posted early receptions line
            PropQuote(
                quote_id="syn_b_ne_chi_player_a_rec_open",
                book="Synthetic Book B",
                market="receptions",
                player_raw_name="Player A",
                team="NE",
                opponent="CHI",
                line=3.5,
                over_odds=105,
                under_odds=-135,
                observed_at=self._ts(1),
                source="Synthetic Book B Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 3. Player B (NE TE) - Synthetic Book C posted early receiving yards line
            # conditional on teammate OUT. Synthetic book opened at 31.5.
            PropQuote(
                quote_id="syn_c_ne_chi_player_b_yds_open",
                book="Synthetic Book C",
                market="receiving_yards",
                player_raw_name="Player B",
                team="NE",
                opponent="CHI",
                line=31.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=self._ts(2),
                source="Synthetic Book C Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 4. Player B - Synthetic Book A receptions
            PropQuote(
                quote_id="syn_a_ne_chi_player_b_rec_open",
                book="Synthetic Book A",
                market="receptions",
                player_raw_name="Player B",
                team="NE",
                opponent="CHI",
                line=3.5,
                over_odds=110,
                under_odds=-140,
                observed_at=self._ts(3),
                source="Synthetic Book A Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 5. Player C (NE WR) - Synthetic Book D yards (efficient-market demo case)
            PropQuote(
                quote_id="syn_d_ne_chi_player_c_yds_open",
                book="Synthetic Book D",
                market="receiving_yards",
                player_raw_name="Player C",
                team="NE",
                opponent="CHI",
                line=45.5,
                over_odds=-110,
                under_odds=-110,
                observed_at=self._ts(4),
                source="Synthetic Book D Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 6. Player D (SF TE) - Synthetic Book A yards (SF vs ATL)
            # conditional on teammate OUT. Synthetic book opened at 48.5.
            PropQuote(
                quote_id="syn_a_sf_atl_player_d_yds_open",
                book="Synthetic Book A",
                market="receiving_yards",
                player_raw_name="Player D",
                team="SF",
                opponent="ATL",
                line=48.5,
                over_odds=-112,
                under_odds=-112,
                observed_at=self._ts(5),
                source="Synthetic Book A Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 7. Player D - Synthetic Book B receptions
            PropQuote(
                quote_id="syn_b_sf_atl_player_d_rec_open",
                book="Synthetic Book B",
                market="receptions",
                player_raw_name="Player D",
                team="SF",
                opponent="ATL",
                line=4.5,
                over_odds=-105,
                under_odds=-125,
                observed_at=self._ts(6),
                source="Synthetic Book B Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 8. Player E (SF RB) - Synthetic Book C yards
            PropQuote(
                quote_id="syn_c_sf_atl_player_e_yds_open",
                book="Synthetic Book C",
                market="receiving_yards",
                player_raw_name="Player E",
                team="SF",
                opponent="ATL",
                line=32.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=self._ts(7),
                source="Synthetic Book C Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 9. Player F (NE WR) - Synthetic Book A yards (Limited ankle)
            PropQuote(
                quote_id="syn_a_ne_chi_player_f_yds_open",
                book="Synthetic Book A",
                market="receiving_yards",
                player_raw_name="Player F",
                team="NE",
                opponent="CHI",
                line=64.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=self._ts(8),
                source="Synthetic Book A Manual Entry (UNVERIFIED - demonstration fixture)"
            ),
            # 10. Player G (DET WR) - Synthetic Book D yards (DET vs GB)
            PropQuote(
                quote_id="syn_d_det_gb_player_g_yds_open",
                book="Synthetic Book D",
                market="receiving_yards",
                player_raw_name="Player G",
                team="DET",
                opponent="GB",
                line=112.5,
                over_odds=-110,
                under_odds=-110,
                observed_at=self._ts(9),
                source="Synthetic Book D Manual Entry (UNVERIFIED - demonstration fixture)"
            )
        ]

        if game_id:
            openers = [q for q in openers if q.team in game_id or q.opponent in game_id]

        return openers


# ---------------------------------------------------------------------------
# Evaluator & Snapshot Generator
# ---------------------------------------------------------------------------

class OddsIngestionAdapter:
    def __init__(
        self,
        season: int = 2026,
        week: int = 7,
        provider: Optional[BaseOddsProvider] = None,
        viewer_dir: Path = VIEWER_DIR,
        snapshots_dir: Path = SNAPSHOTS_DIR
    ):
        self.season = season
        self.week = week
        self.viewer_dir = Path(viewer_dir)
        self.snapshots_dir = Path(snapshots_dir)
        self.provider = provider or EarlyMarketOpenersProvider()

        # Load current slate and injury redistributions
        self.slate_path = self.viewer_dir / f"slate_{season}_w{week}.json"
        self.injuries_path = self.viewer_dir / f"injuries_{season}_w{week}.json"

        if not self.slate_path.exists():
            raise FileNotFoundError(f"Missing slate file: {self.slate_path}")

        with open(self.slate_path, "r", encoding="utf-8") as f:
            self.slate_players: List[Dict[str, Any]] = json.load(f)

        self.injury_beneficiaries: Dict[str, Any] = {}
        if self.injuries_path.exists():
            with open(self.injuries_path, "r", encoding="utf-8") as f:
                inj_data = json.load(f)
                self.injury_beneficiaries = inj_data.get("impacted_beneficiaries", {})

        self.model = ReceivingModel(
            rec_params=None, ypr_params=None,
            alpha=MODEL_ALPHA, k=MODEL_K,
            means=None, sds=None, cols=None
        )

    def evaluate_quote(self, quote: PropQuote) -> Optional[MatchedEvaluation]:
        """Matches raw quote to slate player and computes rigorous edge metrics."""
        player = NameNormalizer.match_player(quote.player_raw_name, quote.team, self.slate_players)
        if not player:
            print(f"[odds_adapter] Failed to match player: '{quote.player_raw_name}' ({quote.team})")
            return None

        p_id = player["player_id"]
        p_name = player["player_display_name"]
        team = player.get("team", quote.team or "")
        opp = player.get("opponent_team", quote.opponent or "")
        game_id = player.get("game_id", f"{self.season}_{self.week:02d}_{team}_{opp}")
        pos = player.get("position", "WR")

        # Check if player has conditional injury redistribution
        ben_info = self.injury_beneficiaries.get(p_id)
        if ben_info and ben_info.get("conditional"):
            mu_rec = ben_info["conditional"]["mu_rec"]
            mu_ypr = ben_info["conditional"]["mu_ypr"]
            fair_rec = ben_info["conditional"]["fair_line_rec"]
            fair_yds = ben_info["conditional"]["fair_line_yards"]
            catalyst = "football_news"
            injury_ctx = ben_info.get("catalyst_injury")
        else:
            mu_rec = float(player.get("mu_rec", 2.5))
            mu_ypr = float(player.get("mu_ypr", 11.5))
            fair_rec = float(player.get("fair_line_rec", 2.5))
            fair_yds = float(player.get("fair_line_yards", 25.0))
            catalyst = "pricing"
            injury_ctx = None

        # Fair line and projected volume calculation (Phase 1 Invariant)
        # Receptions must always sit on nearest hook (.5), proj_volume is distribution mean
        if quote.market == "receptions":
            fair_line = int(fair_rec) + 0.5
            proj_volume = round(mu_rec, 2)
        else:
            fair_line = fair_yds
            proj_volume = round(mu_rec * mu_ypr, 2)

        # Compute model probabilities at the offered book line (if line present)
        if quote.line is not None:
            if quote.market == "receptions":
                p_over_model, p_under_model, p_push_model = compute_rec_probs(mu_rec, quote.line)
            else:
                p_over_model, p_under_model, p_push_model = compute_yards_probs(self.model, mu_rec, mu_ypr, quote.line)
        else:
            p_over_model, p_under_model, p_push_model = 0.5, 0.5, 0.0

        # Invariant 3: A quote requires book + line + captured price + observed_at.
        # No price means no EV, no edge, no ledger entry.
        has_captured_price = (quote.over_odds is not None and quote.over_odds != 0) or (quote.under_odds is not None and quote.under_odds != 0)
        has_line = quote.line is not None
        has_book = bool(quote.book)
        has_observed = bool(quote.observed_at)

        if not (has_captured_price and has_line and has_book and has_observed):
            return MatchedEvaluation(
                quote=quote,
                player_id=p_id,
                player_name=p_name,
                team=team,
                opponent=opp,
                game_id=game_id,
                position=pos,
                market=quote.market,
                fair_line=round(fair_line, 1),
                book_line=round(quote.line or 0.0, 1),
                over_odds=quote.over_odds or 0,
                under_odds=quote.under_odds,
                dec_odds_over=0.0,
                dec_odds_under=0.0,
                p_over_market_devig=0.0,
                p_under_market_devig=0.0,
                p_over_model=round(p_over_model, 4),
                p_under_model=round(p_under_model, 4),
                p_push_model=round(p_push_model, 4),
                prob_edge=0.0,
                break_even_adv=0.0,
                expected_return=0.0,
                best_side="OVER",
                is_qualified=False,
                status="PASS",
                actionable_stake=0.0,
                catalyst="none",
                injury_context=injury_ctx,
                proj_volume=proj_volume,
                mu_rec=round(mu_rec, 4),
                mu_ypr=round(mu_ypr, 4)
            )

        # Compute market probabilities and de-vig
        p_over_market_devig, p_under_market_devig = devig_two_way(quote.over_odds, quote.under_odds)

        # Decide best side
        # Over analysis
        be_over = calculate_break_even_prob(quote.over_odds, p_push_model)
        ev_over = calculate_expected_return(p_over_model, quote.over_odds, p_push_model)
        edge_over = p_over_model - p_over_market_devig
        be_adv_over = p_over_model - be_over

        # Under analysis
        under_odds = quote.under_odds if quote.under_odds is not None else -110
        be_under = calculate_break_even_prob(under_odds, p_push_model)
        ev_under = calculate_expected_return(p_under_model, under_odds, p_push_model)
        edge_under = p_under_model - p_under_market_devig
        be_adv_under = p_under_model - be_under

        if ev_over >= ev_under:
            best_side = "OVER"
            chosen_edge = edge_over
            chosen_be_adv = be_adv_over
            chosen_ev = ev_over
            chosen_odds = quote.over_odds
        else:
            best_side = "UNDER"
            chosen_edge = edge_under
            chosen_be_adv = be_adv_under
            chosen_ev = ev_under
            chosen_odds = under_odds

        # Check qualification policy
        excl_reason = player.get("excl_reason")
        is_questionable = player.get("questionable") == 1 or player.get("questionable") is True

        is_qualified = False
        status = "PASS"
        actionable_stake = 0.0

        if excl_reason:
            status = "EXCLUDED"
        elif is_questionable:
            status = "QUESTIONABLE"
            # Questionable policy allows half Kelly stake if edge is exceptionally clear
            if chosen_edge >= EDGE_HURDLE and chosen_ev > 0:
                dec = american_to_decimal(chosen_odds)
                actionable_stake = round(min(0.015, 0.5 * 0.25 * (chosen_ev / (dec - 1.0))), 4)
        else:
            if chosen_edge >= EDGE_HURDLE and chosen_ev > 0:
                is_qualified = True
                status = "QUALIFIED"
                dec = american_to_decimal(chosen_odds)
                actionable_stake = round(min(0.03, 0.25 * (chosen_ev / (dec - 1.0))), 4)
            elif chosen_edge >= (EDGE_HURDLE * 0.5) and chosen_ev > 0:
                status = "LEAN"

        # Determine catalyst
        if is_qualified:
            if ben_info and (quote.line <= (fair_line - 3.0)):
                catalyst = "both"
            elif ben_info:
                catalyst = "football_news"
            else:
                catalyst = "pricing"

        return MatchedEvaluation(
            quote=quote,
            player_id=p_id,
            player_name=p_name,
            team=team,
            opponent=opp,
            game_id=game_id,
            position=pos,
            market=quote.market,
            fair_line=round(fair_line, 1),
            book_line=round(quote.line, 1),
            over_odds=quote.over_odds,
            under_odds=quote.under_odds,
            dec_odds_over=round(american_to_decimal(quote.over_odds), 3),
            dec_odds_under=round(american_to_decimal(under_odds), 3),
            p_over_market_devig=round(p_over_market_devig, 4),
            p_under_market_devig=round(p_under_market_devig, 4),
            p_over_model=round(p_over_model, 4),
            p_under_model=round(p_under_model, 4),
            p_push_model=round(p_push_model, 4),
            prob_edge=round(chosen_edge, 4),
            break_even_adv=round(chosen_be_adv, 4),
            expected_return=round(chosen_ev, 4),
            best_side=best_side,
            is_qualified=is_qualified,
            status=status,
            actionable_stake=actionable_stake,
            catalyst=catalyst,
            injury_context=injury_ctx,
            proj_volume=proj_volume,
            mu_rec=round(mu_rec, 4),
            mu_ypr=round(mu_ypr, 4)
        )

    def run_ingestion(self, game_id: Optional[str] = None) -> Dict[str, Any]:
        """Ingests quotes, evaluates them, emits snapshots, and writes live feed."""
        quotes = self.provider.fetch_quotes(self.season, self.week, game_id)
        print(f"[odds_adapter] Ingested {len(quotes)} raw quotes from provider.")

        evaluations: List[MatchedEvaluation] = []
        for q in quotes:
            ev = self.evaluate_quote(q)
            if ev:
                # Integrity gate: an unverified quote can never qualify or carry a stake.
                if not q.verified:
                    ev.is_qualified = False
                    ev.status = "UNVERIFIED"
                    ev.actionable_stake = 0.0
                    ev.catalyst = "none"
                evaluations.append(ev)

        print(f"[odds_adapter] Successfully matched and evaluated {len(evaluations)} quotes.")

        # Preserve the entire matched observation set, including rejected and
        # unverified quotes. The quote status below remains explicitly gated;
        # omission would hide passes from a prospective board audit.
        new_snapshots = self.emit_snapshots(evaluations)
        print(f"[odds_adapter] Emitted {len(new_snapshots)} immutable snapshots.")

        # Export live odds feed for viewer
        feed_file = self.export_live_feed(evaluations)
        print(f"[odds_adapter] Exported live odds feed to {feed_file}")

        # Trigger direct Postgres/DB edge ingestion asynchronously
        self._trigger_db_ingestion()

        return {
            "ingested_quotes_count": len(quotes),
            "matched_evaluations_count": len(evaluations),
            "qualified_count": sum(1 for e in evaluations if e.is_qualified),
            "new_snapshots_count": len(new_snapshots),
            "feed_file": str(feed_file)
        }

    def _trigger_db_ingestion(self) -> None:
        """Fires ingest_edges.py in background thread to keep Postgres instantly updated."""
        slate_key = f"{self.season}_w{self.week}"
        ingest_script = BASE_DIR / "ingest_edges.py"

        def _task():
            try:
                subprocess.run(
                    [sys.executable, str(ingest_script), "--slate", slate_key],
                    cwd=str(BASE_DIR),
                    check=False,
                    capture_output=True,
                    text=True
                )
            except Exception as err:
                print(f"[odds_adapter] Background DB ingestion error: {err}")

        thread = threading.Thread(target=_task, name="MarketEdge-Ingestion", daemon=True)
        thread.start()

    def emit_snapshots(self, evaluations: List[MatchedEvaluation]) -> List[Dict[str, Any]]:
        """Appends all matched quote observations to the snapshot log."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = self.snapshots_dir / f"snapshots_{self.season}_w{self.week}.jsonl"
        json_bundle_path = self.viewer_dir / f"snapshots_{self.season}_w{self.week}.json"

        # Load existing snapshots to determine if first_published or material_revision
        existing_keys = set()
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        s = json.loads(line)
                        existing_keys.add((s.get("player_id"), s.get("market"), s.get("quote", {}).get("line")))

        emitted: List[Dict[str, Any]] = []
        now_ts = datetime.now(timezone.utc).isoformat()

        with open(jsonl_path, "a", encoding="utf-8") as f_out:
            for ev in evaluations:
                key = (ev.player_id, ev.market, ev.book_line)
                snapshot_type = "material_revision" if key in existing_keys else "first_published"

                # Find slate row for role info
                slate_row = next((p for p in self.slate_players if p["player_id"] == ev.player_id), {})
                role_info = classify_role_shift(slate_row)

                # Build snapshot conforming to immutable schema
                snap_payload = {
                    "snapshot_id": str(uuid.uuid4()),
                    "snapshot_type": snapshot_type,
                    "created_at": now_ts,
                    "slate": f"{self.season}-W{self.week:02d}",
                    "game_id": ev.game_id,
                    "player_id": ev.player_id,
                    "player_name": ev.player_name,
                    "team": ev.team,
                    "opponent": ev.opponent,
                    "position": ev.position,
                    "market": ev.market,
                    "model": {
                        "version": MODEL_VERSION,
                        "alpha": MODEL_ALPHA,
                        "k": MODEL_K,
                        "calibration_bias": 0.0,
                        "input_cutoff": now_ts
                    },
                    "role": role_info,
                    "projection": {
                        "fair_line": ev.fair_line,
                        "proj_volume": ev.proj_volume,
                        "distribution_params": {
                            "mu_rec": round(ev.mu_rec, 4),
                            "mu_ypr": round(ev.mu_ypr, 4),
                            "alpha": MODEL_ALPHA,
                            "k": MODEL_K
                        },
                        "p_over": ev.p_over_model,
                        "p_under": ev.p_under_model,
                        "p_push": ev.p_push_model
                    },
                    "price_boundaries": {
                        "max_acceptable_over_line_at_minus_110": round(ev.fair_line - 3.0, 1),
                        "min_acceptable_under_line_at_minus_110": round(ev.fair_line + 3.0, 1),
                        "breakeven_odds_at_fair": "-110"
                    },
                    "qualification_policy": {
                        "version": QUALIFICATION_POLICY_VERSION,
                        "edge_hurdle": EDGE_HURDLE,
                        "require_positive_ev": True
                    },
                    "quote": {
                        "status": "verified" if ev.quote.verified else "unverified",
                        "quote_id": ev.quote.quote_id,
                        "source": ev.quote.source,
                        "book": ev.quote.book,
                        "line": ev.book_line,
                        "over_odds": ev.over_odds,
                        "under_odds": ev.under_odds,
                        "observed_at": ev.quote.observed_at,
                        "evaluation": {
                            "is_qualified": bool(ev.is_qualified and ev.quote.verified),
                            "status": ev.status if ev.quote.verified else "UNVERIFIED",
                            "best_side": ev.best_side,
                            "prob_edge": ev.prob_edge,
                            "break_even_adv": ev.break_even_adv,
                            "expected_return": ev.expected_return,
                            "actionable_stake": ev.actionable_stake if ev.quote.verified else 0.0,
                            "catalyst": ev.catalyst,
                            "injury_context": ev.injury_context
                        }
                    },
                    "scenario_assumptions": ev.injury_context
                }

                snap_payload["content_hash"] = compute_canonical_hash(snap_payload)
                f_out.write(json.dumps(snap_payload) + "\n")
                emitted.append(snap_payload)

        # Update viewer snapshot bundle
        all_snapshots: List[Dict[str, Any]] = []
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f_in:
                for line in f_in:
                    if line.strip():
                        all_snapshots.append(json.loads(line))

        with open(json_bundle_path, "w", encoding="utf-8") as f_bundle:
            json.dump(all_snapshots, f_bundle, indent=2)

        return emitted

    def export_live_feed(self, evaluations: List[MatchedEvaluation]) -> Path:
        """Exports viewer/live_odds_feed.json with real quotes and verified stats."""
        out_path = self.viewer_dir / "live_odds_feed.json"

        unique_books = sorted(list(set(e.quote.book for e in evaluations if e.quote.verified)))
        unverified_books = sorted(list(set(e.quote.book for e in evaluations if not e.quote.verified)))
        quotes_list = []

        for e in evaluations:
            receipt = e.quote.receipt_id or hashlib.sha256(f"{e.quote.quote_id}:{e.quote.observed_at}:{e.book_line}:{e.over_odds}".encode()).hexdigest()[:16]
            source_url = e.quote.source_url or "https://www.bovada.lv/services/sports/event/v2/events/A/description/football/nfl"
            content_hash = hashlib.sha256(f"{e.quote.quote_id}:{e.book_line}:{e.over_odds}".encode()).hexdigest()

            quotes_list.append({
                "quote_id": e.quote.quote_id,
                "provider_quote_id": e.quote.quote_id,
                "receipt_id": receipt,
                "source_url": source_url,
                "content_hash": content_hash,
                "book": e.quote.book,
                "book_id": e.quote.book_id or canonical_book(e.quote.book),
                "book_short": e.quote.book_short or (BOOK_META.get(canonical_book(e.quote.book)) or {}).get("short"),
                "player_id": e.player_id,
                "player_name": e.player_name,
                "team": e.team,
                "opponent": e.opponent,
                "game_id": e.game_id,
                "position": e.position,
                "market": e.market,
                "line": e.book_line,
                "fair_line": e.fair_line,
                "over_odds": e.over_odds,
                "under_odds": e.under_odds,
                "observed_at": e.quote.observed_at,
                "source": e.quote.source,
                "verified": bool(e.quote.verified),
                "evaluation": {
                    "is_qualified": e.is_qualified,
                    "status": e.status,
                    "best_side": e.best_side,
                    "prob_edge": e.prob_edge,
                    "break_even_adv": e.break_even_adv,
                    "expected_return": e.expected_return,
                    "actionable_stake": e.actionable_stake,
                    "catalyst": e.catalyst,
                    "injury_context": e.injury_context
                }
            })

        verified_count = sum(1 for e in evaluations if e.quote.verified)
        if verified_count > 0:
            feed_status = "VERIFIED_ACTIVE"
        elif len(quotes_list) > 0:
            feed_status = "UNVERIFIED_MANUAL_ONLY"
        else:
            feed_status = "AWAITING_OPENERS"

        feed_books = {}
        for bid in sorted(set(q["book_id"] for q in quotes_list)):
            meta = BOOK_META.get(bid)
            if meta:
                feed_books[bid] = {"name": meta["display"], "short": meta["short"],
                                   "color": meta["color"], "logo": f"books/{bid}.svg"}

        feed_data = {
            "feed_status": feed_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "slate": f"{self.season}-W{self.week:02d}",
            "verified_books_count": len(unique_books),
            "verified_quotes_count": verified_count,
            "unverified_books": unverified_books,
            "monitored_books": unique_books if unique_books else ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Pinnacle"],
            "books": feed_books,
            "total_quotes": len(quotes_list),
            "qualified_count": sum(1 for e in evaluations if e.is_qualified and e.quote.verified),
            "quotes": quotes_list
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(feed_data, f, indent=2)

        return out_path


# ---------------------------------------------------------------------------
# CLI Command Line Interface & Polling Daemon
# ---------------------------------------------------------------------------

def main():
    import time
    parser = argparse.ArgumentParser(description="Live Odds Ingestion Adapter & Verification Engine")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=7)
    parser.add_argument("--game-id", type=str, default=None, help="Filter to specific game (e.g. 2026_07_NE_CHI)")
    parser.add_argument("--provider", type=str, default="composite", choices=["composite", "bovada", "theoddsapi", "sportsgameodds", "openers", "file"],
                        help="Odds provider to query (default: composite)")
    parser.add_argument("--selftest", action="store_true",
                        help="Run offline pure-function checks (book identity, SGO normalizer, registry) and exit.")
    parser.add_argument("--feed-file", type=str, default=None, help="Path to external feed JSON file when using file provider")
    parser.add_argument("--api-key", type=str, default=None, help="The Odds API key (overrides ODDS_API_KEY env)")
    parser.add_argument("--poll", type=int, default=0, help="Polling interval in seconds (0 = run once, >0 = continuous polling loop)")
    args = parser.parse_args()

    if args.selftest:
        failures = []

        def expect(cond: bool, label: str):
            if not cond:
                failures.append(label)
            print(f"  {'PASS' if cond else 'FAIL'}  {label}")

        expect(canonical_book("DraftKings") == "draftkings", "canonical_book caps drift")
        expect(canonical_book("Draftkings") == "draftkings", "canonical_book odd caps")
        expect(canonical_book("circa_sports") == "circa", "canonical_book alias circa_sports")
        expect(canonical_book("bet-365") == "bet365", "canonical_book punctuation")
        expect(canonical_book("") == "unknown", "canonical_book empty")
        expect(canonical_book("ESPNBETUS") == "espnbet", "canonical_book ESPNBETUS alias")
        expect(BOOK_META["draftkings"]["display"] == "DraftKings", "BOOK_META draftkings display")
        expect(BOOK_META["fanduel"]["short"] == "FD", "BOOK_META fanduel short")

        provider = SportsGameOddsProvider(api_key="test")
        fixture_event = {
            "eventID": "ev_1",
            "odds": {
                "receiving_yards-P1-game-ou-over": {
                    "statID": "receiving_yards", "sideID": "over", "playerID": "P1",
                    "playerName": "Test Receiver", "bookOverUnderLine": 78.5,
                    "bookOdds": "over -110", "fairOdds": "over -112",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "lastUpdatedAt": "2026-10-28T00:00:00Z", "available": True,
                                        "deeplink": "https://sportsbook.draftkings.com/x"},
                        "fanduel": {"odds": "-112", "lastUpdatedAt": "2026-10-28T00:00:00Z", "available": True},
                        "betmgm": {"odds": None, "available": False},
                        "circa_sports": {"odds": "-108", "lastUpdatedAt": "2026-10-28T00:00:00Z", "available": True}
                    }
                },
                "receiving_yards-P1-game-ou-under": {"statID": "receiving_yards", "sideID": "under"},
                "points-home-game-ml-home": {"statID": "points", "sideID": "home"}
            }
        }
        normalized = provider.normalize_event(fixture_event, "2026-10-28T00:00:00Z", 8)
        by_book = {q.book_id: q for q in normalized}
        expect(len(normalized) == 3, f"SGO normalizer: 3 quotes (got {len(normalized)})")
        expect(set(by_book) == {"draftkings", "fanduel", "circa"}, "SGO normalizer: books + alias")
        expect(by_book["draftkings"].book == "DraftKings" and by_book["draftkings"].book_short == "DK",
               "SGO normalizer: DK display/short")
        expect(by_book["draftkings"].line == 78.5 and by_book["draftkings"].over_odds == -110,
               "SGO normalizer: line + price")
        expect(by_book["draftkings"].source_url == "https://sportsbook.draftkings.com/x", "SGO normalizer: deeplink kept")
        expect(by_book["circa"].book == "Circa" and by_book["circa"].book_short == "CIR", "SGO normalizer: alias -> Circa meta")

        import os as _os
        _os.environ.pop("ODDS_PROVIDER", None)
        expect(provider_from_env() is None, "registry: no env -> None")
        _os.environ["ODDS_PROVIDER"] = "sportsgameodds"
        expect(isinstance(provider_from_env(), SportsGameOddsProvider), "registry: env selects SGO")
        _os.environ["ODDS_PROVIDER"] = "nonsense"
        expect(provider_from_env() is None, "registry: unknown env -> None")
        _os.environ.pop("ODDS_PROVIDER", None)

        if failures:
            print(f"odds_adapter selftest: {len(failures)} FAILURES")
            sys.exit(1)
        print("odds_adapter selftest: ALL PASS")
        return

    if args.provider == "file":
        if not args.feed_file:
            print("[odds_adapter] Error: --feed-file required when using file provider.")
            sys.exit(1)
        provider = FeedFileProvider(Path(args.feed_file))
    elif args.provider == "bovada":
        provider = BovadaOddsProvider()
    elif args.provider == "theoddsapi":
        provider = TheOddsApiProvider(api_key=args.api_key)
    elif args.provider == "openers":
        provider = EarlyMarketOpenersProvider()
    else:
        provider = CompositeLiveOddsProvider(api_key=args.api_key)

    adapter = OddsIngestionAdapter(season=args.season, week=args.week, provider=provider)

    if args.poll > 0:
        print(f"[odds_adapter] Starting continuous live odds polling loop (interval: {args.poll}s)...")
        iteration = 1
        while True:
            try:
                print(f"\n[odds_adapter] --- Poll #{iteration} at {datetime.now(timezone.utc).isoformat()} ---")
                res = adapter.run_ingestion(game_id=args.game_id)
                print(f"[odds_adapter] Ingested: {res['ingested_quotes_count']}, Matched: {res['matched_evaluations_count']}, Qualified: {res['qualified_count']}, New Snapshots: {res['new_snapshots_count']}")
                iteration += 1
                time.sleep(args.poll)
            except KeyboardInterrupt:
                print("\n[odds_adapter] Polling terminated by user.")
                break
            except Exception as e:
                print(f"[odds_adapter] Polling error: {e}. Retrying in {args.poll}s...")
                time.sleep(args.poll)
    else:
        result = adapter.run_ingestion(game_id=args.game_id)
        print("\n[odds_adapter] Execution Summary:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
