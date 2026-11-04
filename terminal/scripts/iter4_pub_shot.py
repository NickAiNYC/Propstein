#!/usr/bin/env python3
"""Screenshot the generated public performance page at 1440/375."""
import pathlib, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

VIEWER = pathlib.Path("/home/z/my-project/propstein-src/viewer")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)
    def log_message(self, *a): pass

httpd = ThreadingHTTPServer(("127.0.0.1", 8791), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://127.0.0.1:8791/performance/", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path="/tmp/pub_perf_1440.png")
    ovf = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    print("1440 overflow px:", ovf)
    pg2 = browser.new_page(viewport={"width": 375, "height": 812})
    pg2.goto("http://127.0.0.1:8791/performance/", wait_until="networkidle", timeout=30000)
    pg2.wait_for_timeout(800)
    pg2.screenshot(path="/tmp/pub_perf_375.png")
    ovf2 = pg2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    print("375 overflow px:", ovf2)
    browser.close()
httpd.shutdown()
