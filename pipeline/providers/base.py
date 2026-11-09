"""PropStein pipeline — provider interface.

A BoardFeed produces the raw slate for one run date. Implementations:
  - synthetic.SyntheticBoardFeed  — deterministic simulated feeds (default;
    labelled as simulated data everywhere it surfaces)
  - licensed.LicensedBoardFeed    — HTTP-backed licensed feeds (env-keyed)

Selection is config-driven ("auto" picks licensed when keys are present).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pipeline.schemas import RawSlate


class BoardFeed(ABC):
    id: str
    kind: str  # "synthetic" | "licensed"

    @abstractmethod
    def fetch_slate(self, run_date: date) -> RawSlate:
        """Fetch the full board slate for the given run date.

        Implementations MUST validate through RawSlate (Pydantic) before
        returning; a malformed feed raises rather than returning partial data.
        """
        raise NotImplementedError


def select_feed(source: str = "auto"):
    """Resolve the feed implementation from a source selector."""
    from pipeline import config
    from pipeline.providers import licensed, synthetic

    if source == "synthetic":
        return synthetic.SyntheticBoardFeed()
    if source == "licensed":
        if not config.licensed_configured():
            raise FeedUnavailableError(
                "licensed source requested but PROPSTEIN_FEED_* env keys are not configured"
            )
        return licensed.LicensedBoardFeed(
            odds_url=config.LICENSED_ODDS_URL,
            odds_key=config.LICENSED_ODDS_KEY,
            stats_url=config.LICENSED_STATS_URL,
            stats_key=config.LICENSED_STATS_KEY,
        )
    if source == "auto":
        if config.licensed_configured():
            return licensed.LicensedBoardFeed(
                odds_url=config.LICENSED_ODDS_URL,
                odds_key=config.LICENSED_ODDS_KEY,
                stats_url=config.LICENSED_STATS_URL,
                stats_key=config.LICENSED_STATS_KEY,
            )
        return synthetic.SyntheticBoardFeed()
    raise ValueError(f"unknown source: {source}")


class FeedUnavailableError(RuntimeError):
    pass
