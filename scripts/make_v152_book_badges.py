#!/usr/bin/env python3
"""v152 — self-hosted sportsbook wordmark badges for the viewer.

Why self-authored SVG wordmarks instead of scraped brand files:
  - Wikimedia/brand CDN fetches are blocked from this environment, and
    hotlinking third-party CDNs was exactly the CSP fragility v150 fixed.
  - A deterministic, self-hosted set means `img-src 'self'` keeps working,
    zero external requests, and the asset pipeline is reproducible.
  - Nominative display of sportsbook names in an odds-comparison context is
    standard industry practice; the marks are plain wordmark chips styled
    with each book's approximate brand color (not reproductions).

Design: 2:1 rounded chip, dark plate, book-colored wordmark + left tick.
Fonts: web-safe sans stack (SVG <text>, rendered by the browser).
"""
from __future__ import annotations

import os

OUT = os.path.join(os.path.dirname(__file__), "..", "viewer", "books")

# display-key → (file stem, wordmark text, brand color, plate color)
BOOKS = {
    "draftkings": ("draftkings", "DraftKings", "#53d337", "#0b0e14"),
    "fanduel": ("fanduel", "FanDuel", "#7ab8ff", "#0a1e3d"),
    "betmgm": ("betmgm", "BetMGM", "#c6a45e", "#0b0e14"),
    "caesars": ("caesars", "Caesars", "#c39e6d", "#0b0e14"),
    "pinnacle": ("pinnacle", "Pinnacle", "#f56f36", "#0b0e14"),
    "betrivers": ("betrivers", "BetRivers", "#ffc72c", "#101820"),
    "fanatics": ("fanatics", "Fanatics", "#e03131", "#0b0e14"),
    "bet365": ("bet365", "bet365", "#0b7d57", "#ffd400"),
    "espnbet": ("espnbet", "ESPN BET", "#d50a0a", "#0b0e14"),
    "circa": ("circa", "Circa", "#ff8200", "#0b0e14"),
}

FONT = "Arial, 'Helvetica Neue', Helvetica, sans-serif"


def badge(stem: str, text: str, color: str, plate: str) -> str:
    """318x64 viewBox chip (≈5:1), scales to any render size via CSS."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 318 64" role="img" aria-label="{text}">
  <rect x="1" y="1" width="316" height="62" rx="14" fill="{plate}" stroke="{color}" stroke-opacity="0.55" stroke-width="2"/>
  <rect x="1" y="1" width="14" height="62" rx="7" fill="{color}"/>
  <text x="34" y="42" font-family="{FONT}" font-size="26" font-weight="700" letter-spacing="0.5" fill="{color}">{text}</text>
</svg>
"""


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for key, (stem, text, color, plate) in BOOKS.items():
        path = os.path.join(OUT, f"{stem}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(badge(stem, text, color, plate))
        print(f"  wrote {path}")
    print(f"books: {len(BOOKS)} badges")


if __name__ == "__main__":
    main()
