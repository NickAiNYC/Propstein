"""PropStein pipeline — deterministic simulated feeds.

The reference deployment's data plane. Every value is a fixed function of
(run_date, entity keys, namespaces) so any stored number is reproducible from
the artifact alone. The production deployment swaps in licensed feeds behind
the same BoardFeed interface (providers/licensed.py); the source label
"synthetic" is carried end-to-end so no surface can mistake it for licensed
data (charter rule 5: no fabricated confidence).

Deliberate fail-closed fixtures are seeded into every slate:
  - ~6% of quotes are captured far before the run (STALE QUOTE rows)
  - ~10% of NFL rows lack a weather observation, ~3% carry a late spread
    observation (UNVERIFIED CONTEXT rows)
  - UFC method-of-victory rows have no model coverage (NO MODEL COVERAGE rows)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pipeline import config
from pipeline.determinism import gauss, mulberry32, seed_from
from pipeline.odds import american_from_probability
from pipeline.providers.base import BoardFeed
from pipeline.schemas import RawContextObservation, RawSlate, RawSlateEntry

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
    "TEN", "WAS",
]

NBA_TEAMS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

UFC_CITIES = ["Las Vegas NV", "Newark NJ", "London UK", "Abu Dhabi", "Kansas City MO", "Sydney AU"]

SURNAMES = [
    "Hargrove", "Bellamy", "Whitaker", "Sorrell", "Castellanos", "Okafor", "Marchetti",
    "Delaughter", "Kimura", "Vandermeer", "Ashcombe", "Ferraro", "Nwosu", "Trescott",
    "Gallo", "Mbeki", "Rasmussen", "Ilardi", "Vasquez", "Hollowbrook", "Castine",
    "Petrov", "Allman", "Zabala", "Kowalski", "Dufresne", "Sabatini", "Crews",
    "Olukayode", "Mireles", "Tanaka", "Bergeron", "Stovall", "Quintero", "Hagopian",
    "Winslow", "Braddock", "Oyelaran", "Delacroix", "Nakamura", "Fairbanks", "Solano",
    "Eriksen", "Battle", "Vidal", "Mazzari", "Cortland", "Abara", "Sandoval",
    "Kravchenko", "Tibbs", "Lavigne", "Overstreet", "Cai", "Bergstrom", "Amado",
    "Prescott", "Chukwu", "Fontaine", "Yarborough", "Salgado", "Renner", "Dunmore",
]

INITIALS = list("ABCDEFGHIJKLMNOPRSTVW")

# market id, label, (line baseline lo, hi), line step
NFL_MARKETS = [
    ("player_reception_yds", "Receiving Yards", (18.5, 96.5), 0.5),
    ("player_rushing_yds", "Rushing Yards", (22.5, 88.5), 0.5),
    ("player_passing_yds", "Passing Yards", (185.5, 292.5), 0.5),
]
NBA_MARKETS = [
    ("player_points", "Points", (11.5, 33.5), 0.5),
    ("player_threes", "3-Pointers Made", (1.5, 4.5), 0.5),
]
UFC_MARKETS = [
    ("player_method_of_victory", "Wins by KO/TKO", (0.5, 0.5), 0.5),
]

# players emitted per game per market
PLAYERS_PER_MARKET = {
    "player_reception_yds": 3,
    "player_rushing_yds": 2,
    "player_passing_yds": 1,
    "player_points": 3,
    "player_threes": 2,
    "player_method_of_victory": 1,
}

# feature drift per run (fraction of the spec's range)
FEATURE_DRIFT = 0.06
# day-over-day line drift scale
LINE_DRIFT = 0.9
# fraction of rows with a stale quote capture
STALE_QUOTE_RATE = 0.06
# fraction of NFL rows missing weather / carrying a late spread observation
WEATHER_MISSING_RATE = 0.10
LATE_SPREAD_RATE = 0.03


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class SyntheticBoardFeed(BoardFeed):
    id = config.SYNTHETIC_ODDS_PROVIDER_ID
    kind = "synthetic"

    # -- game-day calendar ---------------------------------------------------

    def _games_on(self, day: date) -> list[tuple[str, str, str, str, str]]:
        """(sport, event_id, event_label, commences_iso, cluster_id) for one day."""
        weekday = day.weekday()  # Mon=0 .. Sun=6
        games: list[tuple[str, str, str, str, str]] = []

        if weekday == 6:  # NFL Sunday
            games += self._pair_teams("NFL", day, count=8, kickoff_hours=(17.0, 20.25))
        elif weekday == 3:  # NFL Thursday
            games += self._pair_teams("NFL", day, count=1, kickoff_hours=(20.25,))
        elif weekday == 0:  # NFL Monday
            games += self._pair_teams("NFL", day, count=1, kickoff_hours=(19.25,))

        games += self._pair_teams("NBA", day, count=self._seeded_count("NBA", day, 4, 7), kickoff_hours=(23.0, 0.5))

        if weekday == 5:  # UFC Saturday card
            games += self._ufc_event(day)
        return games

    def _seeded_count(self, sport: str, day: date, lo: int, hi: int) -> int:
        rand = mulberry32(seed_from("GCOUNT", sport, day.isoformat()))
        return lo + int(rand() * (hi - lo + 1))

    def _pair_teams(self, sport: str, day: date, count: int, kickoff_hours: tuple[float, ...]):
        teams = NFL_TEAMS if sport == "NFL" else NBA_TEAMS
        rand = mulberry32(seed_from("PAIR", sport, day.isoformat()))
        order = list(range(len(teams)))
        # deterministic Fisher–Yates under the seeded stream
        for i in range(len(order) - 1, 0, -1):
            j = int(rand() * (i + 1))
            order[i], order[j] = order[j], order[i]
        chosen = [teams[i] for i in order[: count * 2]]
        out = []
        for i in range(count):
            away, home = chosen[2 * i], chosen[2 * i + 1]
            hour = kickoff_hours[i % len(kickoff_hours)]
            minute = int((hour % 1) * 60)
            kickoff = datetime(day.year, day.month, day.day, int(hour), minute, tzinfo=timezone.utc)
            event_id = f"EVT-{seed_from(sport, day.isoformat(), away, home):08X}"
            out.append((sport, event_id, f"{away} @ {home}", _iso(kickoff), event_id))
        return out

    def _ufc_event(self, day: date):
        rand = mulberry32(seed_from("UFC", day.isoformat()))
        city = UFC_CITIES[int(rand() * len(UFC_CITIES))]
        event_id = f"EVT-{seed_from('UFC', day.isoformat(), city):08X}"
        kickoff = datetime(day.year, day.month, day.day, 21, 0, tzinfo=timezone.utc)
        return [("UFC", event_id, f"UFC FIGHT NIGHT: {city.upper()}", _iso(kickoff), event_id)]

    # -- players -------------------------------------------------------------

    def _players(self, sport: str, event_id: str, market: str, count: int, run_date: date):
        rand = mulberry32(seed_from("PLAYERS", sport, event_id, market))
        out = []
        for i in range(count):
            surname = SURNAMES[int(rand() * len(SURNAMES))]
            initial = INITIALS[int(rand() * len(INITIALS))]
            name = f"{initial}. {surname}"
            player_id = f"PLR-{seed_from(sport, name, event_id):08X}"
            out.append((player_id, name))
        return out

    # -- slate ---------------------------------------------------------------

    def fetch_slate(self, run_date: date) -> RawSlate:
        entries: list[RawSlateEntry] = []
        context_count = 0
        events_seen: set[str] = set()

        horizon = [run_date + timedelta(days=d) for d in range(config.BOARD_HORIZON_DAYS)]
        for day in horizon:
            for sport, event_id, event_label, commences, cluster in self._games_on(day):
                events_seen.add(event_id)
                markets = NFL_MARKETS if sport == "NFL" else NBA_MARKETS if sport == "NBA" else UFC_MARKETS
                for market, market_label, (lo, hi), step in markets:
                    for player_id, player_name in self._players(sport, event_id, market, PLAYERS_PER_MARKET[market], run_date):
                        entries.append(self._entry(sport, event_id, event_label, commences, cluster, player_id, player_name, market, market_label, lo, hi, step, run_date))
                        context_count += 5

        n_records = len(events_seen) + len(entries) * 2 + context_count
        slate = RawSlate(
            run_date=run_date.isoformat(),
            source="synthetic",
            odds_provider=config.SYNTHETIC_ODDS_PROVIDER_ID,
            stats_provider=config.SYNTHETIC_STATS_PROVIDER_ID,
            n_records_analyzed=n_records,
            entries=entries,
        )
        return slate

    def _entry(
        self,
        sport: str,
        event_id: str,
        event_label: str,
        commences: str,
        cluster: str,
        player_id: str,
        player_name: str,
        market: str,
        market_label: str,
        line_lo: float,
        line_hi: float,
        step: float,
        run_date: date,
    ) -> RawSlateEntry:
        board_key = f"{sport}|{event_id}|{player_id}|{market}"
        base_rand = mulberry32(seed_from("BASE", board_key))

        # --- line: stable baseline + deterministic day-over-day drift -------
        baseline = line_lo + base_rand() * (line_hi - line_lo)
        drift_rand = mulberry32(seed_from("LINEDRIFT", run_date.isoformat(), board_key))
        line = baseline + gauss(drift_rand) * LINE_DRIFT
        line = round(line / step) * step
        if market == "player_method_of_victory":
            line = 0.5
        line = max(step, line)

        # --- quote: fair probability with day drift + vig --------------------
        p_fair_base = 0.35 + base_rand() * 0.30
        quote_rand = mulberry32(seed_from("QUOTE", run_date.isoformat(), board_key))
        p_fair = min(0.72, max(0.28, p_fair_base + gauss(quote_rand) * 0.012))
        vig = 0.045 + quote_rand() * 0.020
        over_raw = p_fair * (1.0 + vig)
        under_raw = (1.0 - p_fair) * (1.0 + vig)
        over_odds = american_from_probability(min(0.97, max(0.03, over_raw)))
        under_odds = american_from_probability(min(0.97, max(0.03, under_raw)))

        # --- capture time: fresh, with seeded stale fixtures ------------------
        run_morning = datetime(run_date.year, run_date.month, run_date.day, 10, 55, tzinfo=timezone.utc)
        if quote_rand() < STALE_QUOTE_RATE:
            captured = run_morning - timedelta(hours=13)  # stale (>300s threshold)
        else:
            captured = run_morning - timedelta(seconds=int(quote_rand() * 240))

        # --- context observations (Evidence DNA inputs) -----------------------
        cutoff = captured + timedelta(seconds=60)
        spread_pts = round(0.5 + base_rand() * 13.5, 1)
        total_pts = round(38.5 + base_rand() * 32.0, 1)
        context_rand = mulberry32(seed_from("CTX", run_date.isoformat(), board_key))

        spread_observed = captured - timedelta(seconds=240)
        if context_rand() < LATE_SPREAD_RATE:
            spread_observed = cutoff + timedelta(seconds=45)  # observed after cutoff

        context = [
            RawContextObservation(
                key="spread",
                label="Game spread",
                source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                observed_at_utc=_iso(spread_observed),
                value=f"{spread_pts} pts",
            ),
            RawContextObservation(
                key="total",
                label="Game total",
                source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                observed_at_utc=_iso(captured - timedelta(seconds=240)),
                value=f"{total_pts} pts",
            ),
            RawContextObservation(
                key="injury_status",
                label="Player injury status",
                source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                observed_at_utc=_iso(captured - timedelta(seconds=60)),
                value="Available",
            ),
            RawContextObservation(
                key="player_form",
                label="Recent player form",
                source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                observed_at_utc=_iso(captured - timedelta(seconds=90)),
                value="3-game rolling usage in band",
            ),
        ]
        if sport == "NFL":
            if context_rand() < WEATHER_MISSING_RATE:
                context.append(
                    RawContextObservation(
                        key="weather",
                        label="Kickoff weather",
                        source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                        observed_at_utc=None,  # never observed -> UNVERIFIED CONTEXT
                        value=None,
                    )
                )
            else:
                context.append(
                    RawContextObservation(
                        key="weather",
                        label="Kickoff weather",
                        source_id=config.SYNTHETIC_STATS_PROVIDER_ID,
                        observed_at_utc=_iso(captured - timedelta(seconds=120)),
                        value="Clear, 8 mph wind",
                    )
                )

        return RawSlateEntry(
            event_id=event_id,
            event_label=event_label,
            sport=sport,
            league=sport,
            commences_at_utc=commences,
            game_cluster_id=cluster,
            player_id=player_id,
            player_name=player_name,
            market=market,
            market_label=market_label,
            line=round(line, 2),
            over_american_odds=over_odds,
            under_american_odds=under_odds,
            quote_captured_at_utc=_iso(captured),
            quote_provider=config.SYNTHETIC_ODDS_PROVIDER_ID,
            quote_licensed=True,
            pricing_cutoff_utc=_iso(cutoff),
            context=context,
            feature_inputs=self._feature_inputs(market, board_key, run_date, base_rand),
        )

    def _feature_inputs(self, market: str, board_key: str, run_date: date, base_rand) -> dict[str, float]:
        """Seeded feature values with small day-over-day drift."""
        from pipeline.features import MARKET_FEATURES

        inputs: dict[str, float] = {}
        for spec in MARKET_FEATURES.get(market, []):
            base = spec.lo + base_rand() * (spec.hi - spec.lo)
            drift_rand = mulberry32(seed_from("FEATDRIFT", run_date.isoformat(), board_key, spec.name))
            value = base + gauss(drift_rand) * FEATURE_DRIFT * (spec.hi - spec.lo)
            inputs[spec.name] = round(min(spec.hi, max(spec.lo, value)), 4)
        return inputs
