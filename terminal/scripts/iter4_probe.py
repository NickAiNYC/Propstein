#!/usr/bin/env python3
"""Probe the viewer for console errors and exercise the workspace flow."""
import json, pathlib, threading, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

REPO = pathlib.Path("/home/z/my-project/propstein-src")
VIEWER = REPO / "viewer"

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)
    def log_message(self, *a): pass

httpd = ThreadingHTTPServer(("127.0.0.1", 8789), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:8789/index.html", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(2500)
    # switch to the W7 research slate (W9 ships empty)
    pg.select_option("#slateSelector", "2026_w7")
    pg.wait_for_timeout(3000)

    # open the board, switch to cards view, then click the first card
    pg.click("#explorePropsBtn")
    pg.wait_for_timeout(2500)
    # ensure the cards view is active
    grid_btn = pg.query_selector('.pw-seg-btn[data-view="cards"]')
    if grid_btn:
        grid_btn.click()
        pg.wait_for_timeout(1200)
    # deep-link a QUOTED player so Market Line + Model Edge render values
    pg.evaluate("() => { window.location.hash = '#/player/jaxon-smith-njigba/receiving-yards'; }")
    pg.wait_for_timeout(3000)
    ws = pg.query_selector("#playerWorkspace")
    print("workspace hidden attr:", ws.get_attribute("hidden") if ws else "MISSING")
    print("body pww-open:", pg.evaluate("() => document.body.classList.contains('pww-open')"))
    print("hash:", pg.evaluate("() => window.location.hash"))
    print("metric cards:", pg.evaluate("() => document.querySelectorAll('.pww-metric-card').length"))
    print("dist svg path:", pg.evaluate("() => Boolean(document.querySelector('.pww-dist-svg path'))"))
    print("factor rows:", pg.evaluate("() => document.querySelectorAll('.pww-factor').length"))
    print("market line value:", pg.evaluate("() => { const els = document.querySelectorAll('.pww-metric-card'); return els[2] ? els[2].innerText.replace(/\\n/g,' | ').slice(0,120) : 'missing'; }"))
    pg.screenshot(path="/tmp/ws_probe_desktop.png")
    pg.screenshot(path="/tmp/ws_probe_desktop_full.png", full_page=True)
    print("=== CONSOLE ===")
    for e in errors[:20]:
        print(e[:300])
    browser.close()
httpd.shutdown()
