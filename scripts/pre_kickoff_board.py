"""
Pre-Kickoff Research Board Generator
Shows model-scored observations without claiming receipt-verified live edge.
Outputs markdown, plaintext, and HTML email formats.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
VIEWER_DIR = BASE_DIR / "viewer"


def generate_board(slate_key: str = "2026_w7") -> Dict[str, Any]:
    snaps_file = VIEWER_DIR / f"snapshots_{slate_key}.json"
    if not snaps_file.exists():
        snaps_file = VIEWER_DIR / "snapshots_2026_w7.json"

    with open(snaps_file, "r", encoding="utf-8") as f:
        snaps = json.load(f)

    # Filter to quoted props
    quoted = [
        s for s in snaps
        if (s.get("quote") or {}).get("line") is not None
        and ((s.get("quote") or {}).get("odds") is not None or (s.get("quote") or {}).get("over_odds") is not None)
    ]

    # Sort by projected volume or name
    items: List[Dict[str, Any]] = []
    observation_source = "Book observations"
    if not quoted:
        # Snapshot shelf not frozen yet: fall back to scored live picks.
        live_file = VIEWER_DIR / f"live_picks_{slate_key}.json"
        if live_file.exists():
            live = json.loads(live_file.read_text(encoding="utf-8"))
            observation_source = str(live.get("source") or observation_source)
            slate_file = VIEWER_DIR / f"slate_{slate_key}.json"
            slate = json.loads(slate_file.read_text(encoding="utf-8")) if slate_file.exists() else []
            players = {str(row.get("player_display_name", "")).casefold(): row for row in slate}
            for p in (live.get("picks") or [])[:25]:
                player = players.get(str(p.get("player", "")).casefold(), {})
                items.append({
                    "player": p.get("player"),
                    "team": p.get("team") or player.get("team") or "—",
                    "opponent": p.get("opponent") or player.get("opponent_team") or "—",
                    "market": "Yards" if p.get("market") == "receiving_yards" else "Receptions",
                    "book": p.get("book") or "Consensus",
                    "line": p.get("line"),
                    "odds": p.get("odds"),
                    "fair_line": "—",
                    "proj_volume": p.get("projection"),
                    "role": f"{(p.get('side') or '').upper()} EV {p.get('ev_per_unit', 0):+.1%}",
                })
    for s in quoted[:25]:
        q = s["quote"]
        proj = s.get("projection") or {}
        items.append({
            "player": s.get("player_name"),
            "team": s.get("team"),
            "opponent": s.get("opponent"),
            "market": "Yards" if s.get("market") == "receiving_yards" else "Receptions",
            "book": q.get("book", "Consensus"),
            "line": q.get("line"),
            "odds": q.get("over_odds") or q.get("odds"),
            "fair_line": proj.get("fair_line"),
            "proj_volume": proj.get("proj_volume"),
            "role": (s.get("role") or {}).get("label", "none")
        })

    source_note = (f"{observation_source} model-scored observations; entry prices are not independently receipt-audited. "
                   "Confirm price and availability at the book.") if not quoted else (
                   "Snapshot quotes require independent receipt checks before they can be called audited.")

    # Build text format
    text_lines = [
        "PROPSTEIN PRE-KICKOFF RESEARCH BOARD",
        f"Slate: {slate_key} | Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "Zero Tout Fluff · Pure Distribution Math · Transparent Limitations",
        "=" * 60,
        "STATUS NOTE:",
        source_note,
        "Model has no statistically verified edge over market closing lines at this time.",
        "Historical Week 07 trigger decisions (N=37) 95% CI: [-0.10, +1.45], spans zero.",
        "-" * 60,
        f"{'PLAYER':<20} {'MKT':<6} {'LINE':<6} {'ODDS':<6} {'FAIR':<6} {'PROJ':<6} {'BOOK'}",
        "-" * 60,
    ]
    for it in items:
        text_lines.append(
            f"{it['player']:<20} {it['market']:<6} {it['line']:<6} {it['odds']:<6} "
            f"{it['fair_line']:<6} {it['proj_volume']:<6} {it['book']}"
        )
    text_lines.append("=" * 60)
    text_lines.append("Research terminal: https://propstein.vercel.app")
    text_lines.append("To inspect model distributions: https://propstein.vercel.app/methodology/")

    # Build HTML format
    rows_html = "".join([
        f"<tr>"
        f"<td><strong>{html_lib.escape(str(it['player']))}</strong> ({html_lib.escape(str(it['team']))} vs {html_lib.escape(str(it['opponent']))})</td>"
        f"<td>{html_lib.escape(str(it['market']))}</td>"
        f"<td>{html_lib.escape(str(it['line']))} ({html_lib.escape(str(it['odds']))})</td>"
        f"<td>{html_lib.escape(str(it['fair_line']))}</td>"
        f"<td>{html_lib.escape(str(it['proj_volume']))}</td>"
        f"<td>{html_lib.escape(str(it['book']))}</td>"
        f"</tr>"
        for it in items
    ])

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>PropStein Pre-Kickoff Research Board</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #070708; color: #f8fafc; padding: 24px; }}
    .container {{ max-width: 680px; margin: 0 auto; background: #0e1117; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 20px; }}
    h1 {{ font-size: 18px; margin-top: 0; color: #D4FB11; }}
    .meta {{ font-size: 12px; color: #94a3b8; margin-bottom: 16px; }}
    .warning {{ background: rgba(245, 158, 11, 0.1); border-left: 3px solid #f59e0b; padding: 10px; font-size: 12px; color: #cbd5e1; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-weight: 600; }}
    td {{ padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
    .footer {{ font-size: 11px; color: #64748b; margin-top: 20px; text-align: center; }}
    a {{ color: #D4FB11; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>PROPSTEIN PRE-KICKOFF RESEARCH BOARD</h1>
    <div class="meta">Slate {slate_key} &middot; Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
    <div class="warning">
      <strong>Research only:</strong> {html_lib.escape(source_note)} Model edge is unvalidated across closing lines (95% CI includes zero).
    </div>
    <table>
      <thead>
        <tr><th>Player</th><th>Market</th><th>Market Line</th><th>Fair Line</th><th>Proj Vol</th><th>Book</th></tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <div class="footer">
      Live terminal: <a href="https://propstein.vercel.app">propstein.vercel.app</a> &middot; Methodology: <a href="https://propstein.vercel.app/methodology/">propstein.vercel.app/methodology/</a>
    </div>
  </div>
</body>
</html>"""

    return {
        "text": "\n".join(text_lines),
        "html": html,
        "item_count": len(items)
    }


def main():
    parser = argparse.ArgumentParser(description="Generate zero-fluff pre-kickoff board")
    parser.add_argument("--slate", default="2026_w7", help="Slate key")
    parser.add_argument("--output-html", default=None, help="Path to write HTML email")
    args = parser.parse_args()

    res = generate_board(args.slate)
    if args.output_html:
        with open(args.output_html, "w", encoding="utf-8") as f:
            f.write(res["html"])
        print(f"Wrote HTML board ({res['item_count']} items) to {args.output_html}")
    else:
        print(res["text"])


if __name__ == "__main__":
    main()
