#!/usr/bin/env python3
"""v171 — CSP-ify + version-discipline for the owner's verify landing (a336e2f).

The rewrite shipped with: inline <style> (365 lines), inline <script> (the
whole landing logic — dead under script-src 'self'), zero cache busters,
no build-hash, placeholder logo instead of the authentic lockup, un-busted
og:image, and 4 inline style="" attrs. This script:
  1. externalizes <style>  -> viewer/verify-landing.css
  2. externalizes <script> -> viewer/verify-landing.js
  3. swaps in busted <link>/<script> refs
  4. adds build-hash meta + busted favicon/style.css/og:image
  5. grafts the authentic pw-brand logo imgs (harness contract)
  6. converts the 4 inline style attrs -> classes in verify-landing.css
"""
import pathlib
import re
import sys

V = pathlib.Path(__file__).resolve().parents[1] / "viewer"
f = V / "verify.html"
html = f.read_text(encoding="utf-8")
orig = html

# 1. extract inline <style> -> verify-landing.css
m = re.search(r"[ \t]*<style>\n(.*?)\n[ \t]*</style>\n", html, re.S)
if not m:
    print("verify.html already externalized to verify-landing.css/js")
    sys.exit(0)
css = m.group(1).rstrip() + "\n"
html = html.replace(m.group(0), '  <link rel="stylesheet" href="/verify-landing.css?v=2026_v171">\n')

# 2. extract inline <script> -> verify-landing.js
m2 = re.search(r"[ \t]*<script>\n(.*?)\n[ \t]*</script>\n", html, re.S)
assert m2, "script block not found"
js = m2.group(1).rstrip() + "\n"
html = html.replace(m2.group(0), '  <script src="/verify-landing.js?v=2026_v171" defer></script>\n')

# 3. head wiring: build-hash, busted og:image/twitter:image
html = html.replace(
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '  <meta name="build-hash" content="2026-w8-v24">',
)
html = html.replace(
    '<meta name="twitter:image" content="https://propwire.vercel.app/propwire-logo.svg">',
    '<meta name="twitter:image" content="https://propwire.vercel.app/og-image.png?v=2026_v171">',
)
html = html.replace(
    '<meta property="og:image" content="https://propwire.vercel.app/propwire-logo.svg">',
    '<meta property="og:image" content="https://propwire.vercel.app/og-image.png?v=2026_v171">',
)

# 4. busters
html = html.replace('href="/favicon.svg"', 'href="/favicon.svg?v=2026_v171"')
html = html.replace('href="/style.css"', 'href="/style.css?v=2026_v171"')

# 5. authentic logo lockup replaces the placeholder svg (pw-brand-* = theme-aware, in shared style.css)
old_logo = re.search(r"[ \t]*<svg class=\"verify-logo-img\".*?</svg>\n", html, re.S)
assert old_logo, "placeholder logo svg not found"
html = html.replace(
    old_logo.group(0),
    '        <img src="/propwire-logo.svg?v=2026_v171" alt="PropWire" class="verify-logo-img pw-brand-dark-only" height="26">\n'
    '        <img src="/propwire-logo-dark.svg?v=2026_v171" alt="" aria-hidden="true" class="verify-logo-img pw-brand-light-only" height="26">\n',
)

# 6. the 4 inline style attrs -> classes (appended to verify-landing.css)
attr_map = [
    ('<div style="margin-top:6px; color:#10b981; font-weight:700;">', '<div class="verify-verif-stamp">'),
    ('<span style="color:#d4fb11;">', '<span class="verify-live-pill">'),
    ('<div style="font-size:16px; font-weight:800; color:#fff;">', '<div class="verify-gate-title">'),
    ('<div style="font-size:12px; color:#a1a1aa; max-width:360px;">', '<div class="verify-gate-sub">'),
]
for old, new in attr_map:
    assert old in html, f"expected attr not found: {old[:60]}"
    html = html.replace(old, new)

css += """
/* v171 — converted from inline style attributes (prod CSP strips style="") */
.verify-verif-stamp { margin-top: 6px; color: #10b981; font-weight: 700; }
.verify-live-pill { color: #d4fb11; }
.verify-gate-title { font-size: 16px; font-weight: 800; color: #fff; }
.verify-gate-sub { font-size: 12px; color: #a1a1aa; max-width: 360px; }
"""

(V / "verify-landing.css").write_text(css, encoding="utf-8")
(V / "verify-landing.js").write_text(js, encoding="utf-8")
f.write_text(html, encoding="utf-8")

# verification pass
bad = []
if re.search(r"<style[\s>]", html): bad.append("inline <style> remains")
if re.search(r"<script>(?!</script>)", html) and "<script>\n" in html: bad.append("inline <script> remains")
if ' style="' in html: bad.append('inline style=" remains')
if "2026_v170" in html: bad.append("stale v170 ref")
if 'content="2026-w8-v24"' not in html: bad.append("build-hash missing")
for need in ['src="/propwire-logo.svg?v=2026_v171"', 'src="/propwire-logo-dark.svg?v=2026_v171"',
             "/verify-landing.css?v=2026_v171", "/verify-landing.js?v=2026_v171",
             "og-image.png?v=2026_v171"]:
    if need not in html:
        bad.append(f"missing: {need}")
if bad:
    print("\n".join(bad)); sys.exit(1)
print("VERIFY-LANDING CSP-IFY CLEAN — style:%d lines, js:%d lines" % (css.count("\n"), js.count("\n")))
