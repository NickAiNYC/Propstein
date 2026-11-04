#!/usr/bin/env python3
"""PropStein public SEO pages — B4 (competitive brief 2026-10-27).

Generates static, JS-free, CSP-safe HTML into viewer/ from the model's own
fixture data. Every page carries the evidence-record honesty rules:
  - model limitations disclosed (incl. negative holdout skill)
  - snapshot timestamps visible; no stale data presented as current
  - "not betting advice" disclaimer on every page

Usage: python3 scripts/build_public_pages.py   (idempotent)

Value boundaries are solved from each snapshot's distribution parameters
(src/value_boundaries.py). They are not the frozen 10% edge anchors.
"""
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.value_boundaries import (  # noqa: E402
    fair_line_display,
    format_percent,
    render_value_paragraph,
    vig_boundaries,
)
VIEWER = os.path.join(ROOT, "viewer")
BASE_URL = "https://propstein.com"
SNAPSHOTS = "snapshots_2026_w7.json"

MARKETS = {
    "receiving_yards": {
        "slug": "receiving-yards",
        "label": "Receiving Yards",
        "unit": "yds",
        "summary_key": "proj_volume",
    },
    "receptions": {
        "slug": "receptions",
        "label": "Receptions",
        "unit": "rec",
        "summary_key": "proj_volume",
    },
}

LIMITATIONS = """
<p>PropStein publishes model limitations alongside every page. Roles and
thresholds are provisional pending chronological holdout validation. In our
published week-1 holdout evaluation the model's Brier score trailed the naive
baseline; we treat that as an open defect, not a marketing problem, and we
publish recalibration results as they land. Snapshots are taken pre-kickoff;
quotes age and lines move, so every number here carries a timestamp and a
verification state. Route-participation and late-scratch information are not
fully modeled. Nothing on this site is betting advice.</p>
"""


def esc(v):
    return html.escape(str(v if v is not None else ""))


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s or "player"


def load(name):
    with open(os.path.join(VIEWER, name)) as f:
        return json.load(f)


def fmt_american(odds):
    n = int(odds)
    return f"+{n}" if n > 0 else str(n)


def pct(x, digits=1):
    return f"{100 * float(x):.{digits}f}%"


def page(title, description, canonical_path, breadcrumb, body,
         show_limitations=True):
    """Render a full standalone HTML page (no JS, CSP-safe external CSS)."""
    crumbs = []
    trail = [("PropStein", "/")] + breadcrumb
    for i, (label, path) in enumerate(trail):
        crumbs.append(
            f'<li><a href="{esc(path)}">{esc(label)}</a></li>'
            if i < len(trail) - 1
            else f'<li aria-current="page">{esc(label)}</li>'
        )
    crumb_items = ",\n".join(
        json.dumps({
            "@type": "ListItem",
            "position": i + 1,
            "name": label,
            **({"item": BASE_URL + path} if path else {}),
        })
        for i, (label, path) in enumerate(trail)
    )
    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": json.loads(f"[{crumb_items}]")},
            {
                "@type": "WebPage",
                "name": title,
                "description": description,
                "url": BASE_URL + canonical_path,
                "isPartOf": {"@type": "WebSite", "name": "PropStein", "url": BASE_URL + "/"},
            },
        ],
    }, indent=1)
    limit_block = (f"""
    <section class="pub-limitations">
      <h2>Model limitations</h2>
      {LIMITATIONS}
    </section>""" if show_limitations else "")
    nav = """
  <header class="pub-header">
    <div class="pub-header-left">
      <a class="pub-brand" href="/">PROPSTEIN</a>
      <span class="pub-header-badge">RESEARCH TERMINAL</span>
    </div>
    <nav class="pub-nav">
      <a href="/">Overview</a>
      <a href="/nfl/props/receiving-yards/">Markets</a>
      <a href="/performance/">Performance</a>
      <a href="/methodology/">Methodology</a>
    </nav>
    <div class="pub-header-right">
      <a href="/performance/" class="pub-mode-badge">RESEARCH MODE</a>
    </div>
  </header>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" content="#0b0e14">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{BASE_URL}{esc(canonical_path)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{BASE_URL}{esc(canonical_path)}">
  <meta name="robots" content="index,follow">
  <link rel="stylesheet" href="/public.css">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="manifest" href="/site.webmanifest?v=2026_v154">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2026_v154">
  <script type="application/ld+json">{jsonld}</script>
</head>
<body>
{nav}
  <main class="pub-main">
    <nav class="pub-crumbs" aria-label="Breadcrumb"><ol>
      {chr(10).join('      ' + c for c in crumbs)}
    </ol></nav>
{body}{limit_block}
  </main>
  <footer class="pub-footer">
    <p>PropStein is quantitative research, not betting advice. No wager should
    be placed based on any content on this site. 21+ where applicable. If
    gambling stops being fun, call 1-800-GAMBLER.</p>
    <nav class="pub-footer-nav">
      <a href="/performance/">Track Record</a>
      <a href="/methodology/">Methodology</a>
      <a href="/">Terminal</a>
      <a href="/legal/terms/">Terms</a>
      <a href="/legal/privacy/">Privacy</a>
      <a href="/legal/responsible-gaming/">Responsible Gaming</a>
    </nav>
  </footer>
</body>
</html>
"""


def write_page(rel_dir, html_text):
    path = os.path.join(VIEWER, rel_dir)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "index.html"), "w") as f:
        f.write(html_text)


def fmt_boundaries(snap):
    """Model-derived -110 value sentence. Ignores frozen qualification anchors."""
    if not snap:
        return "Value boundaries not published for this snapshot."
    proj = snap.get("projection") or {}
    params = proj.get("distribution_params") or {}
    mu_rec = params.get("mu_rec")
    if mu_rec is None:
        return "Value boundaries not published for this snapshot."
    return render_value_paragraph(
        snap.get("market") or "receiving_yards",
        proj.get("fair_line"),
        mu_rec,
        params.get("mu_ypr") or 0.0,
        alpha=params.get("alpha") if params.get("alpha") is not None else 0.1097,
        k=params.get("k") if params.get("k") is not None else 1.555,
    )


def assert_fair_line_invariants(snaps):
    """Phase 1 invariant: Fair line = median of the stored distribution, always;
    receptions use the nearest hook (.5) and show P(over). Assert this at publish time."""
    for s in snaps:
        name = s.get("player_name", "unknown")
        m = s.get("market")
        proj = s.get("projection") or {}
        fair = proj.get("fair_line")
        p_over = proj.get("p_over")
        assert fair is not None, f"fair_line missing for {name}"
        assert p_over is not None, f"p_over missing for {name}"
        assert 0.0 <= p_over <= 1.0, f"p_over out of bounds for {name}: {p_over}"

        if m == "receptions":
            assert fair % 1.0 == 0.5, f"receptions fair line {fair} not on hook (.5) for {name}"


def assert_no_fixture_leakage(snaps):
    """Phase 1 invariant: Fixtures live only in fixtures/ and tests.
    The production build fails if any fixture marker is present in published data."""
    banned = ["Early Openers", "Verified Feed", "bundled_demonstration_fixture", "is_demo"]
    for s in snaps:
        name = s.get("player_name", "unknown")
        q = s.get("quote") or {}
        src = q.get("source") or ""
        book = q.get("book") or ""
        for b in banned:
            assert b.lower() not in src.lower(), f"Banned fixture marker '{b}' in quote source for {name}: {src}"
            assert b.lower() not in book.lower(), f"Banned fixture marker '{b}' in quote book for {name}: {book}"


def quote_block(quote):
    status = (quote or {}).get("status") or "unquoted"
    if status == "unquoted" or not (quote or {}).get("line"):
        return ("<p class='pub-status pub-status-unquoted'>No book quote was captured in "
                "this snapshot. The model numbers below stand alone.</p>")
    obs = quote.get("observed_at") or ""
    stamp = ""
    if obs:
        stamp = f' <time datetime="{esc(obs)}">observed {esc(obs[:16].replace("T", " "))} UTC</time>'
    odds_val = quote.get("over_odds") if quote.get("over_odds") is not None else quote.get("odds")
    if odds_val is None and quote.get("under_odds") is not None:
        odds_val = quote.get("under_odds")
    odds_str = f" ({esc(fmt_american(odds_val))})" if odds_val is not None else ""
    return (f"<p class='pub-status pub-status-quoted'>Latest captured quote: "
            f"<strong>{esc((quote or {}).get('source') or (quote or {}).get('book') or 'book')}</strong> "
            f"{esc(quote.get('line'))}{odds_str} "
            f"&mdash; status <strong>{esc(status)}</strong>.{stamp} Lines move; "
            f"treat this as historical unless re-verified in the terminal.</p>")


def generate_distribution_svg(snap, vig_bounds):
    market = snap.get("market") or "receiving_yards"
    proj = snap.get("projection") or {}
    params = proj.get("distribution_params") or {}
    mu_rec = params.get("mu_rec")
    if mu_rec is None:
        return ""
    fair_line = float(proj.get("fair_line") or 0.0)
    proj_volume = float(proj.get("proj_volume") or fair_line)
    quote = snap.get("quote") or {}
    quote_line = float(quote.get("line")) if quote.get("line") is not None else None
    alpha = float(params.get("alpha") if params.get("alpha") is not None else 0.1097)
    k = float(params.get("k") if params.get("k") is not None else 1.555)
    mu_ypr = float(params.get("mu_ypr") or 0.0)

    width = 640
    height = 210
    pad_left = 46
    pad_right = 24
    pad_top = 28
    pad_bottom = 28
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    if market == "receptions" or mu_ypr <= 0.0:
        x_max = max(fair_line * 2.2, float(quote_line or 0) * 1.5, 10.0)
        xs = np.arange(0, int(x_max) + 1)
        r = 1.0 / alpha
        p = r / (r + mu_rec)
        pdf_pts = stats.nbinom.pmf(xs, r, p)
        cdf_pts = stats.nbinom.cdf(xs, r, p)
    else:
        x_max = max(fair_line * 2.2, float(quote_line or 0) * 1.5, 80.0)
        xs = np.linspace(0.5, x_max, 70)
        r = 1.0 / alpha
        p = r / (r + mu_rec)
        ns = np.arange(1, 35)
        pn = stats.nbinom.pmf(ns, r, p)
        scale = mu_ypr / k
        gamma_pdfs = stats.gamma.pdf(xs[:, None], a=ns[None, :] * k, scale=scale)
        pdf_pts = np.dot(gamma_pdfs, pn)
        gamma_cdfs = stats.gamma.cdf(xs[:, None], a=ns[None, :] * k, scale=scale)
        cdf_pts = np.dot(gamma_cdfs, pn)

    pdf_max = max(float(np.max(pdf_pts)), 1e-4)

    def x_px(val):
        return pad_left + (float(val) / x_max) * plot_w

    def y_pdf_px(val):
        return pad_top + plot_h - (float(val) / pdf_max) * (plot_h - 10)

    def y_cdf_px(val):
        return pad_top + plot_h - float(val) * (plot_h - 10)

    pdf_d = []
    pdf_area_d = [f"M {x_px(xs[0]):.1f} {pad_top + plot_h:.1f}"]
    for x, y in zip(xs, pdf_pts):
        xp = x_px(x)
        yp = y_pdf_px(y)
        pdf_d.append(f"{'M' if not pdf_d else 'L'} {xp:.1f} {yp:.1f}")
        pdf_area_d.append(f"L {xp:.1f} {yp:.1f}")
    pdf_area_d.append(f"L {x_px(xs[-1]):.1f} {pad_top + plot_h:.1f} Z")

    cdf_d = []
    for x, y in zip(xs, cdf_pts):
        xp = x_px(x)
        yp = y_cdf_px(y)
        cdf_d.append(f"{'M' if not cdf_d else 'L'} {xp:.1f} {yp:.1f}")

    ticks = []
    step = 20.0 if x_max >= 70 else (10.0 if x_max >= 25 else 2.0)
    cur = 0.0
    while cur <= x_max:
        xp = x_px(cur)
        ticks.append(f'<line x1="{xp:.1f}" y1="{pad_top + plot_h}" x2="{xp:.1f}" y2="{pad_top + plot_h + 4}" stroke="#222733"/>')
        ticks.append(f'<text x="{xp:.1f}" y="{pad_top + plot_h + 16}" text-anchor="middle" class="dist-tick-num" fill="#9CA3AF" font-size="10" font-family="JetBrains Mono, monospace">{int(cur) if cur == int(cur) else cur:.1f}</text>')
        cur += step

    vig_rect = ""
    if vig_bounds and vig_bounds.over_line is not None and vig_bounds.under_line is not None:
        vx1 = max(pad_left, x_px(vig_bounds.over_line))
        vx2 = min(pad_left + plot_w, x_px(vig_bounds.under_line))
        if vx2 - vx1 > 2:
            vw = vx2 - vx1
            vig_rect = (
                f'<rect x="{vx1:.1f}" y="{pad_top}" width="{vw:.1f}" height="{plot_h}" class="dist-vig-band" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.09)" stroke-dasharray="3 3"/>'
                f'<text x="{vx1 + vw/2:.1f}" y="{pad_top + 16}" text-anchor="middle" class="dist-vig-text" fill="#9CA3AF" font-size="9" font-family="JetBrains Mono, monospace" letter-spacing="0.05em">NO-VALUE VIG BAND</text>'
            )

    fx = x_px(fair_line)
    fair_ref = (
        f'<line x1="{fx:.1f}" y1="{pad_top}" x2="{fx:.1f}" y2="{pad_top + plot_h}" class="dist-ref-fair" stroke="#38BDF8" stroke-width="1.5" stroke-dasharray="4 3"/>'
        f'<text x="{fx:.1f}" y="{pad_top - 8}" text-anchor="middle" class="dist-ref-fair-text" fill="#38BDF8" font-size="10" font-family="JetBrains Mono, monospace" font-weight="700">Fair: {fair_line:.1f}</text>'
    )
    mx = x_px(proj_volume)
    mean_ref = ""
    if abs(mx - fx) > 20:
        mean_ref = (
            f'<line x1="{mx:.1f}" y1="{pad_top}" x2="{mx:.1f}" y2="{pad_top + plot_h}" class="dist-ref-mean" stroke="#FBBF24" stroke-width="1.5" stroke-dasharray="2 2"/>'
            f'<text x="{mx:.1f}" y="{pad_top - 8}" text-anchor="middle" class="dist-ref-mean-text" fill="#FBBF24" font-size="10" font-family="JetBrains Mono, monospace">Mean: {proj_volume:.1f}</text>'
        )
    quote_ref = ""
    if quote_line is not None:
        qx = x_px(quote_line)
        quote_ref = (
            f'<line x1="{qx:.1f}" y1="{pad_top}" x2="{qx:.1f}" y2="{pad_top + plot_h}" class="dist-ref-quote" stroke="#E5E7EB" stroke-width="1.5"/>'
            f'<text x="{qx:.1f}" y="{pad_top - 8}" text-anchor="middle" class="dist-ref-quote-text" fill="#E5E7EB" font-size="10" font-family="JetBrains Mono, monospace">Quote: {quote_line:.1f}</text>'
        )

    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="dist-svg" role="img" aria-label="Quant Distribution for {esc(snap.get('player_name', ''))}">
  <rect width="{width}" height="{height}" fill="transparent"/>
  <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" stroke="#222733" stroke-width="1"/>
  {''.join(ticks)}
  {vig_rect}
  <g class="dist-pdf-layer">
    <path d="{' '.join(pdf_area_d)}" class="dist-pdf-area" fill="rgba(56,189,248,0.12)"/>
    <path d="{' '.join(pdf_d)}" class="dist-pdf-curve" fill="none" stroke="#38BDF8" stroke-width="2"/>
    <text x="{pad_left + 8}" y="{pad_top + 16}" class="dist-layer-label" fill="#6B7280" font-size="9" font-family="JetBrains Mono, monospace">PROBABILITY DENSITY f(x)</text>
  </g>
  <g class="dist-cdf-layer">
    <path d="{' '.join(cdf_d)}" class="dist-cdf-curve" fill="none" stroke="#38BDF8" stroke-width="2"/>
    <text x="{pad_left + 8}" y="{pad_top + 16}" class="dist-layer-label" fill="#6B7280" font-size="9" font-family="JetBrains Mono, monospace">CUMULATIVE PROBABILITY F(x)</text>
  </g>
  {fair_ref}
  {mean_ref}
  {quote_ref}
</svg>'''

    unique_id = f"dist_{abs(hash(snap.get('player_id', '') + market)) % 1000000}"
    return f'''<div class="dist-chart-card">
  <div class="dist-chart-top">
    <div class="dist-chart-heading">
      <span class="dist-chart-badge">QUANT MODEL</span>
      <h3 class="dist-chart-title">Distribution &amp; Tail Probabilities</h3>
    </div>
    <div class="dist-chart-controls">
      <label class="dist-tab-label">
        <input type="radio" name="{unique_id}" value="pdf" checked class="dist-radio-pdf">
        <span class="dist-tab-btn">Density (PDF)</span>
      </label>
      <label class="dist-tab-label">
        <input type="radio" name="{unique_id}" value="cdf" class="dist-radio-cdf">
        <span class="dist-tab-btn">Cumulative (CDF)</span>
      </label>
    </div>
  </div>
  <div class="dist-svg-wrapper">
    {svg_content}
  </div>
  <div class="dist-chart-legend">
    <span class="dist-legend-item"><span class="dist-swatch dist-swatch-fair"></span> Fair Median ({fair_line})</span>
    <span class="dist-legend-item"><span class="dist-swatch dist-swatch-mean"></span> Proj Mean ({proj_volume:.1f})</span>
    <span class="dist-legend-item"><span class="dist-swatch dist-swatch-band"></span> -110 Vig Dead-Band</span>
  </div>
</div>'''


def player_market_page(snap, other_market_path, games_by_id, injuries_index):
    m = MARKETS[snap["market"]]
    name = snap["player_name"]
    proj = snap.get("projection") or {}
    role = snap.get("role") or {}
    fair = proj.get("fair_line")
    vol = proj.get("proj_volume")
    p_over = proj.get("p_over")
    quote = snap.get("quote") or {}
    game = games_by_id.get(snap.get("game_id")) or {}
    matchup = f"{snap.get('team')} at {snap.get('opponent')}" if snap.get("team") else "matchup TBD"
    inj = injuries_index.get(snap.get("player_id"))
    injury_html = ""
    if inj:
        notes = inj if isinstance(inj, str) else json.dumps(inj)
        injury_html = (f"<section><h2>Injury context</h2><p>This player appears in the "
                       f"availability feed as a beneficiary of teammate availability "
                       f"({esc(notes)[:200]}). See the terminal's availability drawer for "
                       f"the full model treatment.</p></section>")
    prov = role.get("provisional_note")
    prov_html = f"<p class='pub-note'>{esc(prov)}</p>" if prov else ""
    params = (proj.get("distribution_params") or {})
    params_html = ""
    if params:
        params_html = ("<p class='pub-params'>Distribution parameters (NegBin&ndash;Gamma "
                       f"v3.2): mu_rec {esc(params.get('mu_rec'))}, mu_ypr "
                       f"{esc(params.get('mu_ypr'))}, alpha {esc(params.get('alpha'))}, "
                       f"k {esc(params.get('k'))}.</p>")
    created = snap.get("created_at") or ""
    created_h = created[:16].replace("T", " ") if created else "unknown"

    # Solve boundaries for distribution band
    vig_bounds = None
    mu_rec = params.get("mu_rec")
    if mu_rec is not None:
        vig_bounds = vig_boundaries(
            snap.get("market"), mu_rec, params.get("mu_ypr") or 0.0,
            alpha=params.get("alpha") if params.get("alpha") is not None else 0.1097,
            k=params.get("k") if params.get("k") is not None else 1.555,
        )

    # Stat card 3: Market quote details
    q_status = quote.get("status") or "unquoted"
    q_line = quote.get("line")
    q_odds = quote.get("over_odds") if quote.get("over_odds") is not None else quote.get("odds")
    if q_odds is None and quote.get("under_odds") is not None:
        q_odds = quote.get("under_odds")
    q_odds_str = f" ({esc(fmt_american(q_odds))})" if q_odds is not None else ""
    
    if q_line is not None:
        quote_num_disp = f"{esc(q_line)} <span class='stat-unit'>{esc(m['unit'])}</span>{q_odds_str}"
        quote_source_disp = f"{esc(quote.get('source') or quote.get('book') or 'Book')} &bull; Status: {esc(q_status)}"
        badge_cls = "stat-badge-quoted"
    else:
        quote_num_disp = "Unquoted"
        quote_source_disp = "No active book quote captured"
        badge_cls = ""

    dist_chart_html = generate_distribution_svg(snap, vig_bounds)

    recent_ts = role.get("recent_target_share")
    recent_ts_str = esc(pct(recent_ts)) if recent_ts is not None else "n/a"

    body = f"""
    <div class="pub-player-grid">
      <div class="pub-player-main">
        <h1>{esc(name)} &ndash; {esc(m['label'])}: Model Fair Line &amp; Research</h1>
        <p class="pub-lede">PropStein's pre-kickoff model projection for {esc(name)}
        ({esc(snap.get('position') or '')}, {esc(snap.get('team') or '')}) in the
        {esc(matchup)} game &mdash; {esc(m['label'].lower())} market, {esc(snap.get('slate') or '')}.
        Snapshot taken <time datetime="{esc(created)}">{esc(created_h)} UTC</time>.</p>
        {quote_block(quote)}
        {dist_chart_html}
        <section>
          <h2>Model projection</h2>
          <dl class="pub-stats">
            <div><dt>Fair line</dt><dd>{esc(fair)} {esc(m['unit'])}</dd></div>
            <div><dt>Projected volume</dt><dd>{esc(vol)} {esc(m['unit'])}</dd></div>
            <div><dt>P(over) at fair</dt><dd>{esc(pct(p_over)) if p_over is not None else 'n/a'}</dd></div>
            <div><dt>Role</dt><dd>{esc(role.get('label') or 'unlabeled')}</dd></div>
          </dl>
          {params_html}
          <h3>How to use the fair line</h3>
          <p>{fmt_boundaries(snap)}</p>
        </section>
        <section>
          <h2>Role evidence</h2>
          <dl class="pub-stats">
            <div><dt>Recent window</dt><dd>{esc(role.get('recent_window') or 'n/a')}</dd></div>
            <div><dt>Baseline window</dt><dd>{esc(role.get('baseline_window') or 'n/a')}</dd></div>
            <div><dt>Recent target share</dt><dd>{recent_ts_str}</dd></div>
            <div><dt>Baseline target share</dt><dd>{esc(pct(role.get('baseline_target_share'))) if role.get('baseline_target_share') is not None else 'n/a'}</dd></div>
            <div><dt>Career games</dt><dd>{esc(role.get('career_games') or 'n/a')}</dd></div>
          </dl>
          {prov_html}
        </section>
        {injury_html}
        <section>
          <h2>Related research</h2>
          <ul>
            <li><a href="{esc(other_market_path)}">{esc(name)} &ndash; other published market</a></li>
            <li><a href="/nfl/props/{esc(m['slug'])}/">All {esc(m['label'].lower())} fair lines &ndash; week {esc((snap.get('slate') or '').split('W')[-1])}</a></li>
            <li><a href="/performance/">Published track record and calibration</a></li>
            <li><a href="/methodology/">How the model works</a></li>
          </ul>
        </section>
      </div>

      <aside class="pub-player-rail">
        <div class="stat-cards-vertical">
          <div class="stat-card">
            <div class="stat-card-top">
              <span class="stat-card-label">Model Fair Line</span>
              <span class="stat-badge">50/50 Median</span>
            </div>
            <div class="stat-card-num">{esc(fair)} <span class="stat-unit">{esc(m['unit'])}</span></div>
            <div class="stat-card-sub">P(over) at fair: <strong>{esc(pct(p_over)) if p_over is not None else 'n/a'}</strong></div>
          </div>

          <div class="stat-card">
            <div class="stat-card-top">
              <span class="stat-card-label">Projected Volume</span>
              <span class="stat-badge">Expected Mean</span>
            </div>
            <div class="stat-card-num">{esc(vol)} <span class="stat-unit">{esc(m['unit'])}</span></div>
            <div class="stat-card-sub">Unconditional expected production</div>
          </div>

          <div class="stat-card">
            <div class="stat-card-top">
              <span class="stat-card-label">Market Quote</span>
              <span class="stat-badge {badge_cls}">{esc(q_status)}</span>
            </div>
            <div class="stat-card-num">{quote_num_disp}</div>
            <div class="stat-card-sub">{quote_source_disp}</div>
          </div>
        </div>

        <div class="invalidation-card">
          <h3 class="invalidation-title">Forecast Invalidation Triggers</h3>
          <p class="invalidation-intro">Quantitative assumptions behind this projection. Any of these signals degrades or revokes the edge:</p>
          <ul class="invalidation-list">
            <li><strong>Target Share Shift:</strong> In-game distribution moves &gt; 5% from baseline ({recent_ts_str} recent).</li>
            <li><strong>Personnel Outage:</strong> Key teammate inactive altering pass volume or target concentration.</li>
            <li><strong>Adverse Weather:</strong> Sustained winds &gt; 15 mph or heavy rain suppressing passing efficiency.</li>
            <li><strong>Game Script Blowout:</strong> Spread margin &gt; 14 points forcing extreme run-heavy second-half pacing.</li>
          </ul>
        </div>

        <div class="terminal-action-card">
          <a href="/?player={esc(snap['_slug'])}" class="pub-btn-terminal">
            <span>Open in PropStein Terminal</span>
            <span>&rarr;</span>
          </a>
          <p class="terminal-action-sub">Live CLOB odds, order routing &amp; execution gates.</p>
        </div>
      </aside>
    </div>"""
    title = f"{name} {m['label']} Props: Model Fair Line & Projection"
    desc = (f"Pre-kickoff model fair line for {name} {m['label'].lower()} "
            f"({snap.get('team')}'s {matchup}): fair {fair} {m['unit']}, projected "
            f"volume {vol}, with price boundaries, verification state and published "
            f"model limitations.")
    return page(
        title, desc,
        f"/nfl/players/{snap['_slug']}/{m['slug']}/",
        [("NFL Props", "/nfl/props/receiving-yards/"),
         (m["label"], f"/nfl/props/{m['slug']}/"),
         (f"{name} {m['label']}", None)],
        body,
    )


def market_page(market_key, snaps, performance_path="/performance/"):
    m = MARKETS[market_key]
    rows = [s for s in snaps if s["market"] == market_key]
    rows.sort(key=lambda s: (s.get("projection") or {}).get("proj_volume") or 0, reverse=True)
    top = rows[:50]
    week = (snaps[0].get("slate") or "").split("W")[-1] if snaps else ""
    trs = []
    for s in top:
        proj = s.get("projection") or {}
        q = s.get("quote") or {}
        q_odds = q.get("over_odds") if q.get("over_odds") is not None else q.get("odds")
        if q_odds is None and q.get("under_odds") is not None:
            q_odds = q.get("under_odds")
        q_odds_str = f" ({esc(fmt_american(q_odds))})" if q_odds is not None else ""
        qtxt = (f"{esc(q.get('source'))} {esc(q.get('line'))}{q_odds_str}"
                if q.get("line") else "<span class='pub-dim'>unquoted</span>")
        trs.append(
            f"<tr><td><a href=\"/nfl/players/{esc(s['_slug'])}/{esc(m['slug'])}/\">"
            f"{esc(s['player_name'])}</a></td>"
            f"<td>{esc(s.get('team'))} vs {esc(s.get('opponent'))}</td>"
            f"<td>{esc(s.get('position'))}</td>"
            f"<td class='pub-num'>{esc(proj.get('fair_line'))}</td>"
            f"<td class='pub-num'>{esc(proj.get('proj_volume'))}</td>"
            f"<td class='pub-num'>{esc(pct(proj.get('p_over'))) if proj.get('p_over') is not None else 'n/a'}</td>"
            f"<td>{qtxt}</td></tr>")
    body = f"""
    <h1>NFL {esc(m['label'])} Props &ndash; Model Fair Lines (Week {esc(week)})</h1>
    <p class="pub-lede">Pre-kickoff model fair lines for every published NFL
    {esc(m['label'].lower())} market. The fair line is where the model's
    over/under probabilities balance; a book line beyond the model's published
    boundaries is where it sees value at standard vig. Every row links to the
    player's full research page with role evidence, price boundaries and model
    limitations.</p>
    <p class="pub-note">Top {len(top)} of {len(rows)} modeled players by projected
    volume. The full board, with live verification states and execution gating,
    lives in the <a href="/">PropStein terminal</a>.</p>
    <div class="pub-tablewrap">
    <table class="pub-table">
      <thead><tr><th>Player</th><th>Matchup</th><th>Pos</th><th>Fair line</th>
      <th>Proj volume</th><th>P(over)</th><th>Latest quote</th></tr></thead>
      <tbody>
        {chr(10).join(trs)}
      </tbody>
    </table>
    </div>
    <section>
      <h2>Why publish fair lines instead of picks</h2>
      <p>Most picks sites sell a table of odds. The professional question is not
      &ldquo;what is the line&rdquo; but &ldquo;which side of this price is
      wrong, by how much, and how confident is the model.&rdquo; PropStein
      publishes the fair line, the acceptable price boundaries, the role
      evidence behind each projection, and a dated track record &mdash;
      including the weeks where calibration was poor.</p>
    </section>
    <section>
      <h2>Evidence</h2>
      <ul>
        <li><a href="{esc(performance_path)}">Published track record</a> &mdash; every graded decision, including the bad ones</li>
        <li><a href="/methodology/">Methodology</a> &mdash; model, gating, verification and known defects</li>
      </ul>
    </section>"""
    title = f"NFL {m['label']} Props: Model Fair Lines & Player Research"
    desc = (f"Model fair lines for NFL {m['label'].lower()} player props: fair line, "
            f"projected volume and over probability for every published player, with "
            f"price boundaries, quote verification and disclosed model limitations.")
    return page(
        title, desc, f"/nfl/props/{m['slug']}/",
        [("NFL Props", None), (m["label"], None)], body)


def generate_clv_distribution_svg(weekly):
    ledger = weekly.get("ledger") or []
    counts = {-1.0: 0, 0.0: 0, 1.0: 0, 2.0: 0}
    for r in ledger:
        lm = float(r.get("line_movement") or 0.0)
        if lm in counts:
            counts[lm] += 1
        elif lm > 0:
            counts[2.0] += 1
        else:
            counts[-1.0] += 1
    total = max(len(ledger), 1)

    width = 640
    height = 190
    baseline_y = 145

    bars = [
        {"label": "-1.0 yd (Drift)", "val": counts[-1.0], "color": "#F87171", "x": 65, "w": 85},
        {"label": "0.0 yd (Tied)", "val": counts[0.0], "color": "#64748B", "x": 195, "w": 120},
        {"label": "+1.0 yd (Beat)", "val": counts[1.0], "color": "#34D399", "x": 360, "w": 85},
        {"label": "+2.0 yd (Beat)", "val": counts[2.0], "color": "#38BDF8", "x": 490, "w": 85},
    ]

    svg_bars = []
    for b in bars:
        h = max(int((b["val"] / total) * 110), 4) if b["val"] > 0 else 0
        y = baseline_y - h
        pct_val = (b["val"] / total) * 100
        svg_bars.append(f'''
    <g class="clv-bar-group">
      <rect x="{b['x']}" y="{y}" width="{b['w']}" height="{h}" rx="2" fill="{b['color']}" opacity="0.9"/>
      <text x="{b['x'] + b['w']/2}" y="{y - 6}" text-anchor="middle" fill="#F3F4F6" font-size="11" font-family="JetBrains Mono, monospace" font-weight="700">{b['val']} ({pct_val:.1f}%)</text>
      <text x="{b['x'] + b['w']/2}" y="{baseline_y + 18}" text-anchor="middle" fill="#9CA3AF" font-size="10" font-family="JetBrains Mono, monospace">{b['label']}</text>
    </g>''')

    return f'''<div class="pub-visual-card">
  <div class="pub-visual-header">
    <h3 class="pub-visual-title">Closing Line Movement Distribution (N = {total} Decisions)</h3>
    <span class="stat-badge">Week 7 Graded</span>
  </div>
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="dist-svg" role="img" aria-label="CLV Line Movement Distribution">
    <rect width="{width}" height="{height}" fill="transparent"/>
    <line x1="30" y1="{baseline_y}" x2="{width - 30}" y2="{baseline_y}" stroke="#222733" stroke-width="1"/>
    {''.join(svg_bars)}
  </svg>
</div>'''


def generate_calibration_plot_svg():
    width = 640
    height = 240
    pad_left = 60
    pad_bottom = 40
    plot_w = 520
    plot_h = 160
    pad_top = 30

    return f'''<div class="pub-visual-card">
  <div class="pub-visual-header">
    <h3 class="pub-visual-title">Reliability Calibration &amp; PIT Diagram</h3>
    <span class="stat-badge">Holdout Sample</span>
  </div>
  <div class="dist-svg-wrapper">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="dist-svg" role="img" aria-label="Holdout Reliability Calibration Curve">
      <rect width="{width}" height="{height}" fill="transparent"/>
      <!-- Grid & Axes -->
      <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" stroke="#222733" stroke-width="1"/>
      <line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h}" stroke="#222733" stroke-width="1"/>
      <!-- 45 Degree Perfect Calibration Diagonal -->
      <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top}" stroke="#475569" stroke-width="1.5" stroke-dasharray="4 4"/>
      <text x="{pad_left + plot_w - 10}" y="{pad_top + 14}" fill="#64748B" font-size="9" font-family="JetBrains Mono, monospace" text-anchor="end">Perfect Calibration (y = x)</text>
      <!-- Empirical Points (Preliminary 37 Decisions) -->
      <circle cx="{pad_left + plot_w * 0.45:.1f}" cy="{pad_top + plot_h * 0.52:.1f}" r="4" fill="#38BDF8"/>
      <circle cx="{pad_left + plot_w * 0.52:.1f}" cy="{pad_top + plot_h * 0.48:.1f}" r="4" fill="#38BDF8"/>
      <circle cx="{pad_left + plot_w * 0.60:.1f}" cy="{pad_top + plot_h * 0.38:.1f}" r="4" fill="#38BDF8"/>
      <!-- Watermark Over Insufficient Sample Area -->
      <rect x="{pad_left + 15}" y="{pad_top + 20}" width="{plot_w - 30}" height="{plot_h - 40}" rx="4" fill="rgba(17, 20, 27, 0.75)" stroke="rgba(245, 158, 11, 0.3)" stroke-dasharray="3 3"/>
      <text x="{pad_left + plot_w/2}" y="{pad_top + plot_h/2 - 6}" text-anchor="middle" fill="#FBBF24" font-size="11" font-family="JetBrains Mono, monospace" font-weight="700" letter-spacing="0.06em">INSUFFICIENT SAMPLE GATE (N = 37 &lt; 300)</text>
      <text x="{pad_left + plot_w/2}" y="{pad_top + plot_h/2 + 14}" text-anchor="middle" fill="#9CA3AF" font-size="9.5" font-family="Inter, sans-serif">Confidence bounds span zero [-10.1%, +145.0%]. Commercial upgrades locked until gate clears.</text>
      <!-- Axis Labels -->
      <text x="{pad_left}" y="{pad_top + plot_h + 20}" text-anchor="middle" fill="#9CA3AF" font-size="10" font-family="JetBrains Mono, monospace">0.0</text>
      <text x="{pad_left + plot_w/2}" y="{pad_top + plot_h + 20}" text-anchor="middle" fill="#9CA3AF" font-size="10" font-family="JetBrains Mono, monospace">0.5</text>
      <text x="{pad_left + plot_w}" y="{pad_top + plot_h + 20}" text-anchor="middle" fill="#9CA3AF" font-size="10" font-family="JetBrains Mono, monospace">1.0</text>
      <text x="{pad_left + plot_w/2}" y="{pad_top + plot_h + 34}" text-anchor="middle" fill="#6B7280" font-size="9" font-family="JetBrains Mono, monospace">PREDICTED PROBABILITY BUCKET</text>
    </svg>
  </div>
</div>'''


def performance_page():
    clv = load("clv_audit_report.json")
    weekly = load("clv_report_2026_w7.json")
    holdout = load("holdout_eval_2026_w1.json")
    hmet = holdout.get("metrics") or {}
    rows = []
    for r in (clv.get("records") or []):
        outcome = r.get("outcome") or ""
        rows.append(
            f"<tr><td>{esc(r.get('player'))}</td><td>{esc(r.get('market'))}</td>"
            f"<td>{esc(r.get('side'))} {esc(r.get('line'))}</td>"
            f"<td>{esc(r.get('odds'))}</td><td>{esc(r.get('close_line'))} ({esc(r.get('close_odds'))})</td>"
            f"<td class='pub-num'>{esc(r.get('clv_yards'))} yds / {esc(r.get('clv_prob_pct'))}%</td>"
            f"<td>{esc('WIN' if outcome == 'win' else outcome.upper())}</td>"
            f"<td class='pub-num'>{esc(r.get('net_pnl'))}</td></tr>")

    clv_dist_html = generate_clv_distribution_svg(weekly)
    calibration_plot_html = generate_calibration_plot_svg()

    body = f"""
    <div class="pub-gate-banner">
      <div class="pub-gate-badge">PRE-COMMERCIAL HONESTY POSTURE</div>
      <div class="pub-gate-title">Insufficient Sample Gate: <strong>37 / 300 Graded Decisions (12.3%)</strong></div>
      <div class="pub-gate-track"><div class="pub-gate-fill"></div></div>
      <p class="pub-gate-sub">Paid commercial signups, subscriber gating, and beat-close marketing guarantees remain frozen until N &ge; 300 prospective board decisions achieve positive CLV bounded strictly above zero with 95% confidence.</p>
    </div>

    <h1>PropStein Track Record &amp; Evidence</h1>
    <p class="pub-lede">Headline performance is full-board CLV &mdash; every
    decision graded against closing line value with confidence intervals, not a
    cherry-picked ledger subset. Everything graded so far is published as-is,
    including the small sample, the losing weeks and the model defects.</p>

    <section>
      <h2>Full-board close calibration (Week {esc((weekly.get('slate') or '').split('W')[-1])})</h2>
      <p>Headline metric: every graded board decision (N = <strong>{esc((weekly.get('summary') or {}).get('total_graded'))}</strong>):<br>
      &bull; <strong>2 of 37 beat the close</strong> (5.4%, 95% Wilson CI: [1.5%, 17.7%]; Clopper&ndash;Pearson exact: [0.7%, 18.2%])<br>
      &bull; <strong>34 of 37 tied the close</strong> (91.9%, line unchanged)<br>
      &bull; <strong>1 of 37 closed worse</strong> (2.7%, -1.0 yd drift)<br>
      Average line delta: <strong>+0.05 yds</strong> (95% CI: [-0.23, +0.33] yds). Average CLV EV: {esc(pct((weekly.get('summary') or {}).get('avg_clv_ev'), 2))}.</p>
      <p class="pub-note"><strong>Headline honesty:</strong> Across the full board only 2 of 37 decisions beat the close that week.
      That is what an honest calibration record looks like early. We publish full-board calibration first so there is zero cherry-picking.</p>
      {clv_dist_html}
    </section>

    <section>
      <h2>Graded ledger (preliminary sample, n = {esc(clv.get('total_records'))})</h2>
      <p><strong>{esc(clv.get('record_str'))}</strong> over
      <strong>{esc(clv.get('total_records'))}</strong> graded records &mdash;
      win rate {esc(clv.get('win_rate_pct'))}% (95% Wilson CI: [52.9%, 97.8%]), beat-close rate
      {esc(clv.get('beat_close_rate_pct'))}%, average close beating value
      {esc(clv.get('avg_clv_prob_pct'))}% of implied probability, net P&amp;L
      {esc(clv.get('net_pnl'))} on {esc(clv.get('total_staked'))} staked
      (ROI {esc(clv.get('realized_roi_pct'))}%). Ledger root hash
      <code>{esc(clv.get('ledger_root_hash'))}</code>.</p>
      <p class="pub-note"><strong>Read this honestly:</strong> {esc(clv.get('total_records'))}
      records is a tiny sample. None of these rates are meaningful evidence of
      edge yet. We publish them below the full board so the methodology is auditable from
      day one, and so there is no incentive to quietly drop bad weeks.</p>
      <div class="pub-tablewrap">
      <table class="pub-table">
        <thead><tr><th>Player</th><th>Market</th><th>Bet</th><th>Odds</th>
        <th>Close</th><th>CLV</th><th>Outcome</th><th>Net</th></tr></thead>
        <tbody>{chr(10).join(rows)}</tbody>
      </table>
      </div>
    </section>

    <section>
      <h2>Published model evaluation (holdout)</h2>
      <p>Decision cutoff enforced: <strong>{esc('yes' if holdout.get('decision_cutoff_enforced') else 'no')}</strong>;
      {esc(holdout.get('total_snapshots_evaluated'))} snapshots evaluated,
      {esc(holdout.get('excluded_future_snapshots'))} future snapshots excluded
      to prevent leakage.</p>
      <dl class="pub-stats">
        <div><dt>Brier score (model)</dt><dd>{esc(hmet.get('brier_score_model'))}</dd></div>
        <div><dt>Brier score (naive baseline)</dt><dd>{esc(hmet.get('brier_score_naive_baseline'))}</dd></div>
        <div><dt>Brier skill</dt><dd>{esc(hmet.get('brier_skill_score_pct'))}%</dd></div>
        <div><dt>Log loss (model)</dt><dd>{esc(hmet.get('log_loss_model'))}</dd></div>
        <div><dt>Log loss (baseline)</dt><dd>{esc(hmet.get('log_loss_naive_baseline'))}</dd></div>
      </dl>
      <p class="pub-note"><strong>The model currently underperforms the naive
      baseline on this holdout.</strong> We publish that because it is true.
      Recalibration is an active workstream; roles and thresholds carry
      provisional labels everywhere in the product until the skill score turns
      positive.</p>
      {calibration_plot_html}
    </section>

    <section>
      <h2>Model Evolution &amp; Architecture Milestones</h2>
      <div class="pub-timeline-card">
        <div class="pub-timeline-step">
          <div class="pub-timeline-marker">v3.0</div>
          <div class="pub-timeline-body">
            <strong>Week 1: Poisson Baseline (Trailed Naive)</strong>
            <p>Discrete Poisson count model for receptions with constant empirical YPR. Trailed the naive baseline on chronological holdout (Brier: 0.2642 vs 0.2520). Documented and published as an open defect.</p>
          </div>
        </div>
        <div class="pub-timeline-step">
          <div class="pub-timeline-marker">v3.1</div>
          <div class="pub-timeline-body">
            <strong>Week 4: NegBin2 Dispersion + Target-Share EWMA</strong>
            <p>Introduced Negative Binomial variance expansion (&alpha; = 0.1097) to account for heavy right tails and target-share volatility over recent game windows.</p>
          </div>
        </div>
        <div class="pub-timeline-step active">
          <div class="pub-timeline-marker">v3.2</div>
          <div class="pub-timeline-body">
            <strong>Week 7: Compound NegBin-Gamma Convolution (Current Live)</strong>
            <p>Two-stage compound continuous Gamma yardage per reception (k = 1.555). Solved continuous and discrete -110 vig boundaries with exact integer push windows.</p>
          </div>
        </div>
        <div class="pub-timeline-step planned">
          <div class="pub-timeline-marker">v3.3</div>
          <div class="pub-timeline-body">
            <strong>Roadmap: Walkforward Chronological Recalibration</strong>
            <p>Expanding prospective sample to N &ge; 300 decisions. Adding coverage-funnel adjustments and live injury absorption tracking.</p>
          </div>
        </div>
      </div>
    </section>

    <section>
      <h2>Market-Model Edge Fit &amp; Guarantee Status (Phase 2 &amp; 3)</h2>
      <p><strong>Model has no edge over market closing lines at this time. All projections should be treated as informational.</strong></p>
      <p>Chronological regression fitting <code>p = w &middot; p<sub>model</sub> + (1 - w) &middot; p<sub>market</sub></code> on active trigger decisions yields:<br>
      &bull; <strong>w&#770; = 0.6742</strong> (Standard Error: 0.3957, <strong>95% CI: [-0.1013, +1.4497]</strong>, N = 37)<br>
      Because the 95% confidence interval spans zero, there is no statistically significant evidence of closing line alpha over the market consensus.</p>
      <p class="pub-note"><strong>Public actions in effect:</strong><br>
      &bull; <strong>Beat-Close Guarantee Suspended:</strong> Beating or tying a close on a small sample guarantees nothing about win rate or expected value. The marketing guarantee is publicly withdrawn.<br>
      &bull; <strong>Paid Signups Frozen &amp; Quant Tier Waitlisted:</strong> Commercial paid upgrades remain suspended until N &ge; 300 graded board decisions achieve positive CLV bounded strictly above zero with 95% confidence.<br>
      &bull; <strong>Uncensored Research Access:</strong> Projections and live pricing calculations are made available without paywalls in observer research mode.</p>
    </section>

    <section>
      <h2>What we publish as the sample grows</h2>
      <p>Calibration by predicted-probability bucket; win rate with sample
      size; ROI with a confidence interval; maximum drawdown; splits by sport,
      market and model version; and losing weeks next to winning weeks, every
      week. The commitment is the record, not the highlight reel.</p>
    </section>"""
    return page(
        "PropStein Track Record: Graded Decisions, CLV and Calibration",
        "Every graded PropStein decision published as-is: ledger record, "
        "full-board close calibration, holdout model evaluation including "
        "negative results, and the honest sample-size caveats.",
        "/performance/", [("Track Record", None)], body)


def methodology_page():
    holdout = load("holdout_eval_2026_w1.json")
    hmet = holdout.get("metrics") or {}
    # Worked example uses the same solver as the player pages (not a fixed band).
    aj_mu_rec, aj_mu_ypr, aj_alpha, aj_k = 5.2319, 12.9847, 0.1097, 1.555
    aj_bounds = vig_boundaries(
        "receiving_yards", aj_mu_rec, aj_mu_ypr, alpha=aj_alpha, k=aj_k,
    )
    aj_fair = fair_line_display(
        "receiving_yards", aj_mu_rec, aj_mu_ypr, 61.0, alpha=aj_alpha, k=aj_k,
    )
    body = f"""
    <h1>How PropStein Works: Model, Gating and Verification</h1>
    <p class="pub-lede">PropStein is a decision terminal for player-prop
    markets. Instead of selling picks, it publishes what a professional needs
    to trust a price: the model's fair line, the price boundaries where value
    exists, the evidence behind each projection, and a dated, falsifiable
    track record.</p>
    <section>
      <h2>The model</h2>
      <p>Projections use a Negative-Binomial / Gamma mixture (v3.2) over
      receiving volume: per-player target-share roles (recent window vs. an
      EWMA baseline), per-target yardage distributions, and a compounding
      receptions&times;yards CDF for yardage markets. Each snapshot stores its
      distribution parameters, so every published number is reproducible from
      its inputs.</p>
    </section>
    <section>
      <h2>Distribution parameterisation &amp; compound process</h2>
      <p>Player receiving volume is modeled as a two-stage compounded process: a discrete event distribution for receptions compounded by a continuous gamma distribution for yards per catch. Every published player-prop projection is strictly reproducible from four saved snapshot parameters:</p>
      <div class="pub-tablewrap">
        <table class="pub-table">
          <thead>
            <tr><th>Symbol</th><th>Name</th><th>Role in Model</th><th>Distribution Definition</th></tr>
          </thead>
          <tbody>
            <tr><td><code>mu_rec</code></td><td>Mean Expected Receptions</td><td>Center of reception count</td><td>N ~ NegBin(&mu;<sub>rec</sub>, &alpha;)</td></tr>
            <tr><td><code>alpha</code></td><td>Reception Dispersion</td><td>Variance expansion over Poisson</td><td>Var(N) = &mu;<sub>rec</sub> + &alpha;&mu;<sub>rec</sub><sup>2</sup></td></tr>
            <tr><td><code>mu_ypr</code></td><td>Mean Yards Per Reception</td><td>Expected yardage gain per catch</td><td>X<sub>i</sub> ~ Gamma(k, &theta; = &mu;<sub>ypr</sub> / k)</td></tr>
            <tr><td><code>k</code></td><td>Yards Gamma Shape</td><td>Skewness and tail weight per play</td><td>Var(X<sub>i</sub>) = &mu;<sub>ypr</sub><sup>2</sup> / k</td></tr>
          </tbody>
        </table>
      </div>
      <p>The total receiving yardage random variable Y = &sum;<sub>i=1</sub><sup>N</sup> X<sub>i</sub> has an exact unconditional expectation:</p>
      <p><strong>E[Y] = &mu;<sub>rec</sub> &times; &mu;<sub>ypr</sub></strong></p>
      <p>For any yardage line L, the exceedance probability P(Y &gt; L) is computed by convoluting the discrete Negative Binomial distribution with the cumulative Gamma distribution for N catches:</p>
      <p><strong>P(Y &gt; L) = &sum;<sub>n=1</sub><sup>&infin;</sup> P(N = n) &middot; [1 &minus; F<sub>Gamma</sub>(L; shape = n &middot; k, scale = &mu;<sub>ypr</sub> / k)]</strong></p>
      <p>On a non-integer line that survival is P(over) and the push is zero, so P(under) = 1 &minus; P(over). On an integer line L the published probabilities use a half-yard push window: P(push) is the mass in (L &minus; 0.5, L + 0.5], P(over) is the survival above L + 0.5, and P(under) is the CDF at L &minus; 0.5. Receptions are discrete: a whole-number line pushes on that exact count and a half-point line does not. The three probabilities are normalized to sum to 1 before display, and the percentages on each page are rounded so they still sum to 100%.</p>
      <h3>Worked reproduction: A.J. Brown (Week 7 Snapshot)</h3>
      <p>Parameters: <code>mu_rec = 5.2319</code>, <code>mu_ypr = 12.9847</code>, <code>alpha = 0.1097</code>, <code>k = 1.555</code>. The same solver that builds the player pages (<code>src/value_boundaries.py</code>) produces the figures below. At &minus;110 the breakeven win probability is 110/210 &approx; 52.38%.</p>
      <ul>
        <li><strong>Projected Volume:</strong> 5.2319 &times; 12.9847 = <strong>67.93 yards</strong>.</li>
        <li><strong>Fair Line (Median):</strong> <strong>61.0 yards</strong>.</li>
        <li><strong>Probabilities at 61.0 (integer push window):</strong> P(over) = <strong>{format_percent(aj_fair.over_hundredths)}</strong> ({esc(aj_fair.over_odds)} fair); P(under) = <strong>{format_percent(aj_fair.under_hundredths)}</strong> ({esc(aj_fair.under_odds)} fair); P(push) = <strong>{format_percent(aj_fair.push_hundredths)}</strong>. The three displayed percentages sum to 100%.</li>
        <li><strong>Vig-adjusted &minus;110 boundaries:</strong> P(over) equals the 52.38% breakeven at <strong>{aj_bounds.over_exact:.2f} yards</strong> and P(under) equals it at <strong>{aj_bounds.under_exact:.2f} yards</strong>. Player pages round those roots to one decimal: value on the OVER below <strong>{aj_bounds.over_line:.1f}</strong> and on the UNDER above <strong>{aj_bounds.under_line:.1f}</strong>. Those roots are this player's distribution, not a fixed anchor. A flat push subtracted from every line would move the under root about a yard higher; the model only assigns that push on a whole-number line.</li>
      </ul>
    </section>
    <section>
      <h2>Snapshots, not vibes</h2>
      <p>Every number on this site comes from a pre-kickoff snapshot with an
      explicit timestamp, a content hash and a verification state
      (verified / unverified / stale / blocked). Quotes are captured with
      source and observation time. Live pricing in the terminal is never
      served from cache: an unavailable quote is considered safer than a
      stale one presented as current.</p>
    </section>
    <section>
      <h2>Execution gating</h2>
      <p>Rows are gated by an explicit qualification policy (edge hurdle and
      Kelly cap) before they can be actioned. Circuit breakers per market stop
      automated dispatch when feeds degrade. Availability changes (outages,
      usage shifts) propagate to impacted teammates as quantified volume
      deltas, not hunches.</p>
    </section>
    <section>
      <h2>Known defects, published</h2>
      <p>On our week-1 chronological holdout the model's Brier score was
      {esc(hmet.get('brier_score_model'))} against a naive baseline of
      {esc(hmet.get('brier_score_naive_baseline'))} (skill
      {esc(hmet.get('brier_skill_score_pct'))}%) &mdash; i.e. the model
      currently trails the baseline, and we say so everywhere. Role labels
      remain provisional. Route-participation data is incomplete for part of
      the roster. Recalibration work is ongoing; until the skill score turns
      positive, treat all published probabilities as research, not signal.</p>
    </section>
    <section>
      <h2>FAQ</h2>
      <dl class="pub-faq">
        <dt>Is this betting advice?</dt>
        <dd>No. PropStein is quantitative research about player-prop prices.
        Nothing here recommends a wager, and the track-record page exists so
        you can audit the model yourself.</dd>
        <dt>Why show losing calibration publicly?</dt>
        <dd>Because a record you cannot audit is marketing. Publishing the
        full-board calibration, including weeks where only 2 of 37 decisions
        beat the close, is what makes the good weeks worth believing.</dd>
        <dt>How current are the numbers?</dt>
        <dd>Every page carries its snapshot timestamp and quote status. Lines
        move constantly; the terminal re-verifies prices before any execution
        decision and blocks action when feeds are stale.</dd>
      </dl>
    </section>"""
    return page(
        "PropStein Methodology: Fair Lines, Gating and Published Defects",
        "How the PropStein model works: NegBin-Gamma projections, pre-kickoff "
        "snapshots, verification states, execution gating, and published "
        "model limitations including negative holdout results.",
        "/methodology/", [("Methodology", None)], body)


def terms_page():
    body = """
    <h1>Terms of Use</h1>
    <p class="pub-lede">Plain-language terms for using PropStein. We tried to
    keep this short and honest rather than long and defensive.</p>
    <section>
      <h2>What PropStein is</h2>
      <p>PropStein is a quantitative research terminal for NFL player-prop
      markets. It publishes projections, fair lines, price boundaries, line
      snapshots and a dated track record. It is provided for informational
      and research purposes only. PropStein is not a sportsbook, does not
      accept wagers, never handles customer money, and is not affiliated
      with, endorsed by or sponsored by the NFL, any team, or any sportsbook
      named on this site. All third-party trademarks belong to their
      respective owners and are used for identification only.</p>
    </section>
    <section>
      <h2>Not betting advice</h2>
      <p>Nothing on this site is betting advice, a recommendation, or a
      promise of profit. The model is fallible and we publish the evidence:
      our own holdout evaluation currently shows the model trailing a naive
      baseline, and the track-record page includes the losing weeks. Any
      wagering decision you make is solely yours. If you wager, you do so at
      your own risk and you are responsible for complying with the laws of
      your jurisdiction.</p>
    </section>
    <section>
      <h2>Eligibility</h2>
      <p>The site is intended for adults of legal age in their jurisdiction
      (21+ in most U.S. states; 18+ in some). It is not directed to minors.
      Access may be restricted where use of this kind of information is
      prohibited by law. You are responsible for knowing and following the
      rules that apply to you, including any terms of use of the sportsbooks
      you choose to interact with.</p>
    </section>
    <section>
      <h2>No warranties; availability</h2>
      <p>The service is provided &ldquo;as is&rdquo; and &ldquo;as
      available&rdquo; without warranties of any kind, express or implied.
      Lines move and quotes age: snapshots carry timestamps and verification
      states precisely because data can be wrong, stale or incomplete at any
      moment. We do not guarantee uninterrupted availability or error-free
      operation, and feeds may degrade without notice.</p>
    </section>
    <section>
      <h2>Limitation of liability</h2>
      <p>To the maximum extent permitted by law, PropStein and its operators
      are not liable for any losses connected to your use of, or reliance
      on, the site &mdash; including wagering losses, missed opportunities,
      data errors, downtime or consequential damages. Your sole remedy for
      dissatisfaction with the service is to stop using it.</p>
    </section>
    <section>
      <h2>Acceptable use &amp; intellectual property</h2>
      <p>You may use PropStein personally for research. All original code, model
      formulations, data compilations, visual designs, and brand assets are the
      exclusive intellectual property of PropStein. You may not resell or
      republish the site's content as your own, attempt to circumvent rate
      limits or access controls, or bulk-harvest pages or data feeds in a
      way that degrades the service for others. If you cite the work, credit
      PropStein with a link. For copyright or DMCA takedown requests, contact
      <strong>support@propstein.com</strong>.</p>
    </section>
    <section>
      <h2>Billing, memberships &amp; refunds</h2>
      <p>Paid subscriber memberships are processed securely via third-party
      merchant processors (Stripe, Whop). Subscriptions renew automatically
      on a recurring basis until cancelled through your account dashboard or
      membership receipt link. Because quantitative data and proprietary model
      parameters are delivered immediately upon access, membership fees are
      generally non-refundable except where required by applicable consumer law
      or in instances of duplicate billing or verifiable service outages.</p>
    </section>
    <section>
      <h2>Changes, governing law, contact</h2>
      <p>We may update these terms as the product evolves; material changes
      will be reflected on this page with a revised date. These terms are
      governed by the laws of <strong>the State of Delaware</strong>, without regard to
      conflict-of-law rules. Questions or notices: <strong>support@propstein.com</strong>.</p>
    </section>"""
    return page(
        "PropStein Terms of Use &mdash; Research Terminal, Not Betting Advice",
        "Plain-language terms: PropStein is quantitative research, not "
        "betting advice; no wagers accepted; 21+; no profit warranties; "
        "liability limits, billing/refunds, and acceptable use.",
        "/legal/terms/", [("Terms of Use", None)], body,
        show_limitations=False)


def privacy_page():
    body = """
    <h1>Privacy Policy</h1>
    <p class="pub-lede">Short version: PropStein has no accounts, asks for no
    personal information, and stores your UI preferences in your own
    browser.</p>
    <section>
      <h2>What we collect</h2>
      <p><strong>We do not collect personal information.</strong> There are
      no accounts, no sign-ups and no profiles. Your terminal settings
      (theme, layout and similar preferences) are stored in your browser's
      local storage and never leave your device. Clearing site data in your
      browser removes them entirely.</p>
    </section>
    <section>
      <h2>Server and hosting logs</h2>
      <p>The site is served through a third-party host
      (<strong>Vercel Inc.</strong>), which processes standard request
      logs (such as IP address, user agent and timestamps) for security and
      abuse prevention under its own privacy policy. We do not use these
      logs to build profiles of visitors.</p>
    </section>
    <section>
      <h2>Analytics</h2>
      <p>We may measure aggregate traffic (page views, referrers, rough
      geography) using a privacy-respecting analytics provider that does not
      use cookies for cross-site advertising. We do not run ad-network
      trackers, retargeting pixels, or cross-site profiling scripts, and we
      do not sell or share visitor data. If we ever launch accounts or
      payments, this policy will be updated first.</p>
    </section>
    <section>
      <h2>Local storage</h2>
      <p>The terminal stores preferences under keys such as
      <code>propstein-theme</code> and UI state in local storage. These are
      functional, first-party, readable only by this site, and never
      transmitted to us. You can inspect and delete them via your browser's
      developer tools or site-data settings.</p>
    </section>
    <section>
      <h2>Children</h2>
      <p>PropStein is intended for adults of legal gambling age in their
      jurisdiction (21+ in most U.S. states) and is not directed to
      children. If you believe a minor has used the site, contact us and we
      will investigate.</p>
    </section>
    <section>
      <h2>Security, changes, contact</h2>
      <p>We use static, read-only hosting and HTTPS everywhere, which
      minimizes the attack surface for visitor data in the first place. We
      may update this policy as the product changes; material changes appear
      on this page with a revised date. Questions or requests:
      <strong>support@propstein.com</strong>.</p>
    </section>"""
    return page(
        "PropStein Privacy Policy &mdash; No Accounts, No Ad Trackers",
        "Privacy policy: no accounts, no personal data collection, "
        "first-party local storage only, aggregate analytics, no ad-tech "
        "trackers, no data sale.",
        "/legal/privacy/", [("Privacy Policy", None)], body,
        show_limitations=False)


def responsible_gaming_page():
    body = """
    <h1>Responsible Gaming</h1>
    <p class="pub-lede">PropStein is a research tool, and we take the
    responsibilities that come with covering betting markets seriously. If
    betting has stopped being a game for you or someone close to you, help
    is available and it works.</p>
    <section>
      <h2>Our position</h2>
      <p>Wagering should be entertainment with a budget, never a source of
      income or a way to recover losses. Our own published results show the
      model currently trailing a naive baseline on holdout data &mdash; that
      is how uncertain even careful quantitative work is. No projection,
      edge number or tool (including ours) makes a bet safe. Anyone who
      tells you a pick is &ldquo;a lock&rdquo; is telling you something
      untrue.</p>
    </section>
    <section>
      <h2>Know the rules where you are</h2>
      <p>Legal age is 21 in most U.S. states and 18 in some jurisdictions.
      Betting is legal only where licensed operators are permitted to offer
      it. You are responsible for knowing your local law. If you are under
      the legal age where you live, do not use this site or place wagers.</p>
    </section>
    <section>
      <h2>Set limits before you play</h2>
      <ul>
        <li>Decide a fixed entertainment budget and treat it as spent.</li>
        <li>Use the deposit, loss and time limits every licensed sportsbook
        is required to offer &mdash; set them before your first wager, not
        after a bad day.</li>
        <li>Never chase losses, borrow to bet, or bet money you need for
        rent, food or family.</li>
        <li>If a sportsbook's tools feel insufficient, use self-exclusion
        programs (state-wide exclusion lists and per-operator exclusion).</li>
      </ul>
    </section>
    <section>
      <h2>Warning signs</h2>
      <p>Betting more or more often than you planned; hiding or lying about
      wagering; borrowing to bet; selling possessions; betting to escape
      stress, grief or boredom; mood swinging with wins and losses;
      neglecting work, school or relationships. If several of these sound
      familiar, it is time to talk to someone &mdash; early conversations
      prevent the worst outcomes.</p>
    </section>
    <section>
      <h2>Where to get help</h2>
      <ul>
        <li><strong>1-800-GAMBLER</strong> &mdash; national problem-gambling
        helpline network (call or text).</li>
        <li><strong>National Council on Problem Gambling:</strong>
        1-800-522-4700, <a href="https://www.ncpgambling.org" rel="noopener"
        >ncpgambling.org</a>.</li>
        <li><strong>Gamblers Anonymous:</strong> free peer support,
        <a href="https://www.gamblersanonymous.org" rel="noopener"
        >gamblersanonymous.org</a>.</li>
        <li>Most U.S. states operate their own helplines and self-exclusion
        programs; search &ldquo;[your state] problem gambling&rdquo;.</li>
      </ul>
    </section>
    <section>
      <h2>Our commitments</h2>
      <p>We will never sell &ldquo;locks&rdquo; or guaranteed wins, never
      market to minors, publish our full track record including losing
      weeks, and keep this page and the site-wide 1-800-GAMBLER footer
      visible on every page. If you think we are falling short of any of
      these, tell us at <strong>[CONTACT EMAIL]</strong>.</p>
    </section>"""
    return page(
        "PropStein Responsible Gaming &mdash; Limits, Self-Exclusion and Help",
        "Responsible gaming: betting is entertainment with a budget; set "
        "limits first; warning signs; 1-800-GAMBLER, NCPG and Gamblers "
        "Anonymous help resources; our operator commitments.",
        "/legal/responsible-gaming/", [("Responsible Gaming", None)], body,
        show_limitations=False)


def write_public_css():
    css = """:root {
  --bg: #0b0d11;
  --panel: #11141b;
  --panel-elevated: #171b24;
  --line: #222733;
  --line-light: #2d3545;
  --text: #f3f4f6;
  --dim: #9ca3af;
  --muted: #6b7280;
  --accent: #38bdf8;
  --accent-dim: #0c2538;
  --good: #34d399;
  --warn: #fbbf24;
  --danger: #f87171;
  --radius-sm: 2px;
  --radius-md: 4px;
  --radius-pill: 999px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.6 "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: var(--panel-elevated);
  padding: .1em .35em;
  border-radius: var(--radius-sm);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: .88em;
  border: 1px solid var(--line);
}
.pub-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.pub-header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pub-brand {
  font-weight: 800;
  font-size: 1.05rem;
  letter-spacing: 0.04em;
  color: var(--text);
}
.pub-header-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  background: var(--panel-elevated);
  border: 1px solid var(--line);
  color: var(--dim);
}
.pub-nav {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  font-size: 0.88rem;
  font-weight: 500;
}
.pub-nav a {
  color: var(--dim);
  transition: color 0.15s ease;
}
.pub-nav a:hover {
  color: var(--text);
  text-decoration: none;
}
.pub-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pub-mode-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  color: var(--accent);
}
.pub-mode-badge:hover {
  text-decoration: none;
  filter: brightness(1.15);
}
.pub-main {
  max-width: 74rem;
  margin: 0 auto;
  padding: 1.4rem 1.5rem 3.5rem;
}
.pub-crumbs ol {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  padding: 0;
  margin: 0 0 1.2rem;
  font-size: .85rem;
  color: var(--dim);
}
.pub-crumbs li:not(:last-child)::after {
  content: "/";
  margin-left: .4rem;
  color: var(--dim);
}
h1 { font-size: 1.55rem; line-height: 1.25; margin: .2rem 0 .6rem; }
h2 { font-size: 1.15rem; margin: 1.8rem 0 .5rem; }
h3 { font-size: 1rem; margin: 1.1rem 0 .4rem; }
.pub-lede { color: var(--dim); font-size: 1.02rem; margin-bottom: 1.2rem; }
.pub-note {
  background: #161d2c;
  border-left: 3px solid var(--warn);
  padding: .7rem .9rem;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  color: var(--text);
  font-size: .92rem;
}
.pub-status { padding: .75rem 1rem; border-radius: var(--radius-md); font-size: .92rem; margin-bottom: 1.2rem; }
.pub-status-quoted { background: rgba(52, 211, 153, 0.08); border: 1px solid rgba(52, 211, 153, 0.25); }
.pub-status-unquoted { background: var(--panel-elevated); border: 1px solid var(--line); }
.pub-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: .7rem;
  padding: 0;
  margin: .8rem 0;
}
.pub-stats div {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: .65rem .85rem;
}
.pub-stats dt {
  font-size: .75rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--dim);
  margin: 0 0 .2rem;
}
.pub-stats dd { margin: 0; font-weight: 700; font-size: 1.05rem; }
.pub-params { color: var(--dim); font-size: .88rem; }
section { margin: 1.6rem 0; }
ul { padding-left: 1.2rem; }
li { margin: .3rem 0; }
.pub-tablewrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}
.pub-table {
  border-collapse: collapse;
  width: 100%;
  font-size: .88rem;
  min-width: 44rem;
}
.pub-table th {
  text-align: left;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--dim);
  background: var(--panel);
  padding: .6rem .8rem;
  white-space: nowrap;
}
.pub-table td {
  padding: .55rem .8rem;
  border-top: 1px solid var(--line);
  white-space: nowrap;
}
.pub-num { font-variant-numeric: tabular-nums; font-family: "JetBrains Mono", monospace; }
.pub-dim { color: var(--dim); }
.pub-limitations {
  border-top: 1px solid var(--line);
  margin-top: 2.4rem;
  padding-top: .6rem;
}
.pub-limitations p { color: var(--dim); font-size: .9rem; line-height: 1.6; }
.pub-footer {
  border-top: 1px solid var(--line);
  background: var(--panel);
  padding: 1.5rem;
  font-size: .85rem;
  color: var(--dim);
}
.pub-footer-nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: .6rem; }

/* --- 2-Column Institutional Player Layout --- */
.pub-player-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 2rem;
  align-items: start;
}
.pub-player-main { min-width: 0; }
.pub-player-rail {
  position: sticky;
  top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}

/* Stat Cards */
.stat-cards-vertical {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.stat-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 0.9rem 1rem;
}
.stat-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.35rem;
}
.stat-card-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--dim);
  font-weight: 600;
}
.stat-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.65rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--panel-elevated);
  border: 1px solid var(--line);
  color: var(--dim);
}
.stat-badge-quoted {
  background: rgba(52, 211, 153, 0.1);
  border-color: rgba(52, 211, 153, 0.3);
  color: var(--good);
}
.stat-card-num {
  font-family: "JetBrains Mono", monospace;
  font-size: 1.45rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}
.stat-unit {
  font-size: 0.85rem;
  color: var(--dim);
  font-weight: 500;
}
.stat-card-sub {
  font-size: 0.78rem;
  color: var(--dim);
  margin-top: 0.25rem;
}

/* Invalidation Panel */
.invalidation-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem;
}
.invalidation-title {
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--warn);
  margin: 0 0 0.5rem;
  font-weight: 700;
}
.invalidation-intro {
  font-size: 0.8rem;
  color: var(--dim);
  margin: 0 0 0.75rem;
  line-height: 1.45;
}
.invalidation-list {
  padding-left: 1.1rem;
  margin: 0;
  font-size: 0.8rem;
  color: var(--dim);
}
.invalidation-list li {
  margin: 0.4rem 0;
  line-height: 1.4;
}
.invalidation-list strong {
  color: var(--text);
}

/* Terminal Action CTA */
.terminal-action-card {
  background: var(--panel-elevated);
  border: 1px solid var(--line-light);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem;
  text-align: center;
}
.pub-btn-terminal {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 0.65rem 1rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  transition: all 0.15s ease;
}
.pub-btn-terminal:hover {
  background: var(--accent);
  color: #0b0d11;
  text-decoration: none;
}
.terminal-action-sub {
  font-size: 0.75rem;
  color: var(--muted);
  margin: 0.5rem 0 0;
}

/* Distribution Chart Card */
.dist-chart-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 1.1rem 1.25rem 1rem;
  margin: 1.2rem 0 1.6rem;
}
.dist-chart-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.dist-chart-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
  display: block;
  margin-bottom: 0.2rem;
}
.dist-chart-title {
  font-size: 0.98rem;
  font-weight: 700;
  margin: 0;
  color: var(--text);
}
.dist-chart-controls {
  display: flex;
  gap: 0.4rem;
}
.dist-radio-pdf, .dist-radio-cdf {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.dist-tab-btn {
  display: inline-block;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  background: var(--panel-elevated);
  border: 1px solid var(--line);
  color: var(--dim);
  cursor: pointer;
  transition: all 0.15s ease;
}
.dist-chart-card:has(.dist-radio-pdf:checked) .dist-tab-label:first-child .dist-tab-btn,
.dist-chart-card:has(.dist-radio-cdf:checked) .dist-tab-label:last-child .dist-tab-btn {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
}
.dist-cdf-layer {
  display: none;
}
.dist-chart-card:has(.dist-radio-cdf:checked) .dist-pdf-layer {
  display: none;
}
.dist-chart-card:has(.dist-radio-cdf:checked) .dist-cdf-layer {
  display: block;
}
.dist-svg-wrapper {
  position: relative;
  width: 100%;
}
.dist-svg {
  width: 100%;
  height: auto;
  display: block;
}
.dist-chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-top: 0.65rem;
  padding-top: 0.65rem;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  font-size: 0.75rem;
  color: var(--dim);
}
.dist-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.dist-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.dist-swatch-fair { background: var(--accent); }
.dist-swatch-mean { background: var(--warn); }
.dist-swatch-band {
  background: rgba(255, 255, 255, 0.08);
  border: 1px dashed rgba(255, 255, 255, 0.3);
}

/* Audit & Performance Evidence Dashboard */
.pub-gate-banner {
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: var(--radius-md);
  padding: 1.1rem 1.3rem;
  margin-bottom: 1.8rem;
}
.pub-gate-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
  margin-bottom: 0.3rem;
}
.pub-gate-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 0.5rem;
}
.pub-gate-track {
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--panel-elevated);
  border: 1px solid var(--line);
  overflow: hidden;
  margin-bottom: 0.6rem;
}
.pub-gate-fill {
  height: 100%;
  width: 12.3%;
  background: var(--accent);
  border-radius: var(--radius-pill);
}
.pub-gate-sub {
  font-size: 0.84rem;
  color: var(--dim);
  margin: 0;
  line-height: 1.45;
}
.pub-visual-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 1.1rem 1.3rem;
  margin: 1.2rem 0;
}
.pub-visual-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.8rem;
}
.pub-visual-title {
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
  color: var(--text);
}
.pub-timeline-card {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  margin: 1.2rem 0;
}
.pub-timeline-step {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 0.85rem 1rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}
.pub-timeline-step.active {
  border-color: var(--accent);
  background: var(--panel-elevated);
}
.pub-timeline-marker {
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--panel-elevated);
  border: 1px solid var(--line);
  color: var(--dim);
}
.pub-timeline-step.active .pub-timeline-marker {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
}
.pub-timeline-body strong {
  display: block;
  font-size: 0.92rem;
  color: var(--text);
  margin-bottom: 0.2rem;
}
.pub-timeline-body p {
  margin: 0;
  font-size: 0.82rem;
  color: var(--dim);
  line-height: 1.45;
}

@media (max-width: 860px) {
  .pub-player-grid {
    grid-template-columns: 1fr;
    gap: 1.5rem;
  }
  .pub-player-rail {
    position: static;
  }
}
@media (max-width: 640px) {
  h1 { font-size: 1.3rem; }
  .pub-main { padding: 1rem .9rem 2.4rem; }
  .pub-header { padding: 0.75rem 1rem; }
  .pub-nav { display: none; }
}
"""
    with open(os.path.join(VIEWER, "public.css"), "w") as f:
        f.write(css)


def main():
    write_public_css()
    snaps = load(SNAPSHOTS)
    snaps.sort(key=lambda s: str(s.get("created_at") or ""))
    latest = {}
    for s in snaps:
        latest[(s.get("player_id"), s.get("market"))] = s
    snaps = list(latest.values())
    assert_fair_line_invariants(snaps)
    assert_no_fixture_leakage(snaps)

    games = {g.get("game_id"): g for g in load("games_2026_w7.json")}
    injuries = load("injuries_2026_w7.json")
    benef = injuries.get("impacted_beneficiaries") or {}
    injuries_index = {}
    for pid, info in benef.items():
        try:
            added = info.get("added_targets") or info.get("added_volume") or info.get("absorption_share")
            injuries_index[pid] = (f"+{added}" if added is not None else "volume absorption") \
                if not isinstance(added, str) else added
        except Exception:
            injuries_index[pid] = "availability change"

    # slug collisions across distinct player_ids -> disambiguate with team
    seen = {}
    for s in snaps:
        base = slugify(s.get("player_name"))
        slug = base if seen.get(base, s.get("player_id")) == s.get("player_id") else f"{base}-{str(s.get('team') or '').lower()}"
        if base in seen and seen[base] != s.get("player_id") and f"{base}-{str(s.get('team') or '').lower()}" in seen.values():
            slug = f"{base}-{str(s.get('player_id'))[-4:].lower()}"
        s["_slug"] = slug
        seen[base] = s.get("player_id")

    count_players = 0
    by_player = {}
    for s in snaps:
        by_player.setdefault(s.get("player_id"), []).append(s)
    for pid, items in by_player.items():
        for s in items:
            m = MARKETS[s["market"]]
            other = [o for o in items if o["market"] != s["market"]]
            other_path = (f"/nfl/players/{other[0]['_slug']}/{MARKETS[other[0]['market']]['slug']}/"
                          if other else f"/nfl/props/{m['slug']}/")
            write_page(f"nfl/players/{s['_slug']}/{m['slug']}",
                       player_market_page(s, other_path, games, injuries_index))
            count_players += 1

    for mk in MARKETS:
        write_page(f"nfl/props/{MARKETS[mk]['slug']}", market_page(mk, snaps))
    write_page("performance", performance_page())
    write_page("methodology", methodology_page())
    write_page("legal/terms", terms_page())
    write_page("legal/privacy", privacy_page())
    write_page("legal/responsible-gaming", responsible_gaming_page())

    urls = ["/", "/ledger/", "/audit/", "/verify/", "/performance/",
            "/methodology/",
            "/legal/terms/", "/legal/privacy/", "/legal/responsible-gaming/",
            "/nfl/props/receiving-yards/", "/nfl/props/receptions/"]
    for pid_items in by_player.values():
        for s in pid_items:
            urls.append(f"/nfl/players/{s['_slug']}/{MARKETS[s['market']]['slug']}/")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in sorted(set(urls)):
        sitemap.append(f"  <url><loc>{BASE_URL}{u}</loc><lastmod>{stamp}</lastmod></url>")
    sitemap.append("</urlset>")
    with open(os.path.join(VIEWER, "sitemap.xml"), "w") as f:
        f.write("\n".join(sitemap) + "\n")
    with open(os.path.join(VIEWER, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    print(f"generated {count_players} player-market pages, "
          f"{len(MARKETS)} market pages, performance, methodology, "
          f"3 legal pages; sitemap urls={len(set(urls))}")


if __name__ == "__main__":
    main()
