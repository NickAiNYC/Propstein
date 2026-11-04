#!/usr/bin/env python3
"""Deeper probe: slate loading state + board render diagnostics."""
import pathlib, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

REPO = pathlib.Path("/home/z/my-project/propstein-src")
VIEWER = REPO / "viewer"

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)
    def log_message(self, *a): pass

httpd = ThreadingHTTPServer(("127.0.0.1", 8790), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    reqs = []
    pg.on("requestfailed", lambda r: reqs.append(f"FAILED {r.url}"))
    pg.on("response", lambda r: reqs.append(f"{r.status} {r.url}") if ".json" in r.url else None)
    pg.goto("http://127.0.0.1:8790/index.html", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(4000)
    print("slate count:", pg.evaluate("() => window.PropWireTest ? window.PropWireTest.getSlateCount() : 'no harness'"))
    print("visible count:", pg.evaluate("() => window.PropWireTest ? window.PropWireTest.getVisibleCount() : 'no harness'"))
    print("cardView children:", pg.evaluate("() => document.getElementById('cardView') ? document.getElementById('cardView').children.length : 'missing'"))
    print("slateRows rows:", pg.evaluate("() => document.getElementById('slateRows') ? document.getElementById('slateRows').rows.length : 'missing'"))
    print("emptyState hidden:", pg.evaluate("() => { const e = document.getElementById('emptyState'); return e ? e.hidden : 'missing'; }"))
    print("=== JSON requests ===")
    for r in reqs[:25]:
        print(r.replace("http://127.0.0.1:8790", ""))
    browser.close()
httpd.shutdown()
