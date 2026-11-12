#!/usr/bin/env python3
"""Emit /nfl/{player_id}/{market} pages from the current slate JSON only.

Omits a page when that market's published fair line is missing.
No odds, no bet button, no edge claim. Does not grade.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
SLATE = VIEWER / "slate_2026_w10.json"
BASE = "https://propstein.com"
MARKETS = (
    ("receiving_yards", "Receiving yards", "fair_line_yards"),
    ("receptions", "Receptions", "fair_line_rec"),
)
FOOTER = (
    "PropStein full board: 2 of 37 beat close (Week 7). "
    "Holdout Brier skill −12.5%. Paid access frozen."
)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(row: dict, market: str, label: str, fair: object) -> str:
    name = row["player_display_name"]
    team = row.get("current_team") or row["team"]
    opponent = row["opponent_team"]
    slate = f"{row['season']}-W{int(row['week']):02d}"
    fair_text = json.dumps(fair)
    path = f"/nfl/{row['player_id']}/{market}/"
    title = f"{name} {label} fair line"
    description = (
        f"{name}, {label}, {team} vs {opponent}, slate {slate}. "
        "Published model fair line only. This is not a pick and not a price."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{BASE}{esc(path)}">
  <meta name="robots" content="index,follow">
  <link rel="stylesheet" href="/public.css">
</head>
<body>
  <header class="pub-header">
    <a class="pub-brand" href="/">PROPSTEIN</a>
    <nav class="pub-nav">
      <a href="/performance/">Performance</a>
      <a href="/methodology/">Methodology</a>
    </nav>
  </header>
  <main class="pub-main">
    <h1>{esc(name)}</h1>
    <p>{esc(label)}</p>
    <dl class="pub-stats">
      <div><dt>Team</dt><dd>{esc(team)}</dd></div>
      <div><dt>Opponent</dt><dd>{esc(opponent)}</dd></div>
      <div><dt>Slate</dt><dd>{esc(slate)}</dd></div>
      <div><dt>Published model fair line</dt><dd>{esc(fair_text)}</dd></div>
    </dl>
    <p>This is not a pick and not a price.</p>
    <p>{esc(FOOTER)} <a href="/performance/">Track record</a>.</p>
  </main>
</body>
</html>
"""


def main() -> None:
    rows = json.loads(SLATE.read_text(encoding="utf-8"))
    urls: list[str] = []
    written = 0
    for row in rows:
        player_id = row.get("player_id")
        if not player_id or not row.get("player_display_name"):
            continue
        if not (row.get("team") or row.get("current_team")) or not row.get("opponent_team"):
            continue
        if row.get("season") is None or row.get("week") is None:
            continue
        for market, label, field in MARKETS:
            fair = row.get(field)
            if fair is None:
                continue
            dest = VIEWER / "nfl" / str(player_id) / market / "index.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(page(row, market, label, fair), encoding="utf-8")
            urls.append(f"/nfl/{player_id}/{market}/")
            written += 1
    stamp_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in sorted(set(urls)):
        stamp_lines.append(f"  <url><loc>{BASE}{url}</loc></url>")
    stamp_lines.append("</urlset>")
    (VIEWER / "sitemap-players.xml").write_text("\n".join(stamp_lines) + "\n", encoding="utf-8")
    robots = VIEWER / "robots.txt"
    text = robots.read_text(encoding="utf-8") if robots.exists() else "User-agent: *\nAllow: /\n\nSitemap: https://propstein.com/sitemap.xml\n"
    line = "Sitemap: https://propstein.com/sitemap-players.xml\n"
    if line not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += line
        robots.write_text(text, encoding="utf-8")
    print(f"wrote {written} player-market pages from {SLATE.name}")


if __name__ == "__main__":
    main()
