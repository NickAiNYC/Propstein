#!/usr/bin/env python3
"""Brief 4 baseline/after screenshot capture for the PropStein viewer.

Usage: iter4_screenshots.py <label> <outdir>
Serves viewer/ on 127.0.0.1:8788 and captures:
  - desktop 1440x900 board + player deep-link
  - mobile 390x844 and 375x812 board + player
Also records horizontal-overflow measurements for each viewport.
"""
import json
import pathlib
import subprocess
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import functools

REPO = pathlib.Path("/home/z/my-project/propstein-src")
VIEWER = REPO / "viewer"

label = sys.argv[1] if len(sys.argv) > 1 else "before"
outdir = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(f"/home/z/my-project/download/propstein-2027-redesign/iteration-4/{label}")
outdir.mkdir(parents=True, exist_ok=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)

    def log_message(self, *a):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", 8788), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print("serving on 8788")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8788/index.html"
results = {}

with sync_playwright() as p:
    browser = p.chromium.launch()

    def shoot(page, name, url, wait_ms=3800, extra=None):
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(wait_ms)
        if extra:
            extra(page)
        page.screenshot(path=str(outdir / f"{name}.png"), full_page=False)
        m = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth,"
            " cw: document.documentElement.clientWidth,"
            " body: document.body.scrollWidth})"
        )
        results[name] = m

    # Desktop 1440
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    shoot(pg, f"{label}_desktop_1440_board", BASE)
    # Player deep link (first player in slate once rendered)
    def open_first_player(page):
        page.wait_for_timeout(1500)
        page.evaluate(
            """() => {
              const cards = document.querySelectorAll('[data-inspect], .prop-card, [data-player-id]');
              for (const c of cards) { if (c.dataset && c.dataset.inspect) { c.click(); return; } }
              const rows = document.querySelectorAll('tbody tr');
              if (rows.length) rows[0].click();
            }"""
        )
        page.wait_for_timeout(2500)
    shoot(pg, f"{label}_desktop_1440_player", BASE, extra=open_first_player)
    pg.close()

    # Mobile 390
    pg = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    shoot(pg, f"{label}_mobile_390_board", BASE)
    shoot(pg, f"{label}_mobile_390_player", BASE, extra=open_first_player)
    pg.close()

    # Mobile 375
    pg = browser.new_page(viewport={"width": 375, "height": 812}, device_scale_factor=2, is_mobile=True, has_touch=True)
    shoot(pg, f"{label}_mobile_375_board", BASE)
    shoot(pg, f"{label}_mobile_375_player", BASE, extra=open_first_player)
    pg.close()

    browser.close()

httpd.shutdown()
(outdir / f"{label}_overflow.json").write_text(json.dumps(results, indent=1))
print(json.dumps(results, indent=1))
print("saved to", outdir)
