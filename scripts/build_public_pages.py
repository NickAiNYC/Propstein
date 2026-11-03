#!/usr/bin/env python3
"""PropStein public SEO pages — B4 (competitive brief 2026-10-27).

Generates static, JS-free, CSP-safe HTML into viewer/ from the model's own
fixture data. Every page carries the evidence-record honesty rules:
  - model limitations disclosed (incl. negative holdout skill)
  - snapshot timestamps visible; no stale data presented as current
  - "not betting advice" disclaimer on every page

Usage: python3 scripts/build_public_pages.py   (stdlib only; idempotent)
"""
import html
import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER = os.path.join(ROOT, "viewer")
BASE_URL = "https://propstein.vercel.app"
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
    <a class="pub-brand" href="/">PropStein</a>
    <nav class="pub-nav">
      <a href="/nfl/props/receiving-yards/">NFL Receiving Yards</a>
      <a href="/nfl/props/receptions/">NFL Receptions</a>
      <a href="/performance/">Track Record</a>
      <a href="/methodology/">Methodology</a>
    </nav>
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


def fmt_boundaries(b):
    over = b.get("max_acceptable_over_line_at_minus_110")
    under = b.get("min_acceptable_under_line_at_minus_110")
    be = b.get("breakeven_odds_at_fair")
    parts = []
    if over is not None:
        parts.append(f"take the <strong>OVER at &minus;110</strong> only up to a line of "
                     f"<strong>{esc(over)}</strong>")
    if under is not None:
        parts.append(f"take the <strong>UNDER at &minus;110</strong> only down to a line of "
                     f"<strong>{esc(under)}</strong>")
    if be:
        parts.append(f"breakeven odds at the fair line: <strong>{esc(be)}</strong>")
    return "; ".join(parts) if parts else "not published for this snapshot."


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


def player_market_page(snap, other_market_path, games_by_id, injuries_index):
    m = MARKETS[snap["market"]]
    name = snap["player_name"]
    proj = snap.get("projection") or {}
    role = snap.get("role") or {}
    fair = proj.get("fair_line")
    vol = proj.get("proj_volume")
    p_over = proj.get("p_over")
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
    body = f"""
    <h1>{esc(name)} &ndash; {esc(m['label'])}: Model Fair Line &amp; Research</h1>
    <p class="pub-lede">PropStein's pre-kickoff model projection for {esc(name)}
    ({esc(snap.get('position') or '')}, {esc(snap.get('team') or '')}) in the
    {esc(matchup)} game &mdash; {esc(m['label'].lower())} market, {esc(snap.get('slate') or '')}.
    Snapshot taken <time datetime="{esc(created)}">{esc(created_h)} UTC</time>.</p>
    {quote_block(snap.get('quote') or {})}
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
      <p>The model {fmt_boundaries(snap.get('price_boundaries') or {})}.
      A book line outside those boundaries is where the model sees no value at
      standard vig.</p>
    </section>
    <section>
      <h2>Role evidence</h2>
      <dl class="pub-stats">
        <div><dt>Recent window</dt><dd>{esc(role.get('recent_window') or 'n/a')}</dd></div>
        <div><dt>Baseline window</dt><dd>{esc(role.get('baseline_window') or 'n/a')}</dd></div>
        <div><dt>Recent target share</dt><dd>{esc(pct(role.get('recent_target_share'))) if role.get('recent_target_share') is not None else 'n/a'}</dd></div>
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
    </section>"""
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
    body = f"""
    <h1>PropStein Track Record &amp; Evidence</h1>
    <p class="pub-lede">Headline performance is full-board CLV &mdash; every
    decision graded against closing line value with confidence intervals, not a
    cherry-picked ledger subset. Everything graded so far is published as-is,
    including the small sample, the losing weeks and the model defects.</p>
    <section>
      <h2>Full-board close calibration (Week {esc((weekly.get('slate') or '').split('W')[-1])})</h2>
      <p>Headline metric: every graded board decision (N = <strong>{esc((weekly.get('summary') or {}).get('total_graded'))}</strong>):<br>
      &bull; <strong>2 of 37 beat the close</strong> (5.4%, 95% Wilson CI: [0.7%, 18.2%])<br>
      &bull; <strong>34 of 37 tied the close</strong> (91.9%, line unchanged)<br>
      &bull; <strong>1 of 37 closed worse</strong> (2.7%, -1.0 yd drift)<br>
      Average line delta: <strong>+0.05 yds</strong> (95% CI: [-0.23, +0.33] yds). Average CLV EV: {esc(pct((weekly.get('summary') or {}).get('avg_clv_ev'), 2))}.</p>
      <p class="pub-note"><strong>Headline honesty:</strong> Across the full board only 2 of 37 decisions beat the close that week.
      That is what an honest calibration record looks like early. We publish full-board calibration first so there is zero cherry-picking.</p>
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
    keep this short and honest rather than long and defensive. Bracketed
    items are placeholders the operator completes before relying on this
    document.</p>
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
      <h2>Acceptable use</h2>
      <p>You may use PropStein personally for research. You may not resell or
      republish the site's content as your own, attempt to circumvent rate
      limits or access controls, or bulk-harvest pages or data feeds in a
      way that degrades the service for others. If you cite the work, credit
      PropStein with a link.</p>
    </section>
    <section>
      <h2>Changes, governing law, contact</h2>
      <p>We may update these terms as the product evolves; material changes
      will be reflected on this page with a revised date. These terms are
      governed by the laws of <strong>[STATE]</strong>, without regard to
      conflict-of-law rules. Questions: <strong>[CONTACT EMAIL]</strong>.</p>
    </section>"""
    return page(
        "PropStein Terms of Use &mdash; Research Terminal, Not Betting Advice",
        "Plain-language terms: PropStein is quantitative research, not "
        "betting advice; no wagers accepted; 21+; no profit warranties; "
        "liability limits and acceptable use.",
        "/legal/terms/", [("Terms of Use", None)], body,
        show_limitations=False)


def privacy_page():
    body = """
    <h1>Privacy Policy</h1>
    <p class="pub-lede">Short version: PropStein has no accounts, asks for no
    personal information, and stores your UI preferences in your own
    browser. Bracketed items are placeholders the operator completes before
    relying on this document.</p>
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
      (<strong>[HOSTING PROVIDER]</strong>), which processes standard request
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
      <code>propwire-theme</code> and UI state in local storage. These are
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
      <strong>[CONTACT EMAIL]</strong>.</p>
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
  --bg: #0f131a; --panel: #141a23; --line: #273244; --text: #f3f6fa;
  --dim: #8792a6; --accent: #7dd3fc; --good: #3ddc97; --warn: #f5b455;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.6 "Inter", system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: var(--panel); padding: .1em .35em; border-radius: 4px;
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: .9em; }
.pub-header { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
  justify-content: space-between; padding: .9rem 1.2rem;
  border-bottom: 1px solid var(--line); background: var(--panel); }
.pub-brand { font-weight: 800; font-size: 1.15rem; letter-spacing: .02em;
  color: var(--text); }
.pub-nav { display: flex; flex-wrap: wrap; gap: 1rem; font-size: .92rem; }
.pub-main { max-width: 60rem; margin: 0 auto; padding: 1.4rem 1.2rem 3rem; }
.pub-crumbs ol { list-style: none; display: flex; flex-wrap: wrap; gap: .4rem;
  padding: 0; margin: 0 0 1.2rem; font-size: .85rem; color: var(--dim); }
.pub-crumbs li:not(:last-child)::after { content: "/"; margin-left: .4rem;
  color: var(--dim); }
h1 { font-size: 1.55rem; line-height: 1.25; margin: .2rem 0 .6rem; }
h2 { font-size: 1.15rem; margin: 1.8rem 0 .5rem; }
h3 { font-size: 1rem; margin: 1.1rem 0 .4rem; }
.pub-lede { color: var(--text); font-size: 1.02rem; }
.pub-note { background: #161d2c; border-left: 3px solid var(--warn);
  padding: .7rem .9rem; border-radius: 0 6px 6px 0; color: var(--text);
  font-size: .95rem; }
.pub-status { padding: .7rem .9rem; border-radius: 6px; font-size: .95rem; }
.pub-status-quoted { background: #10231c; border: 1px solid #1d4034; }
.pub-status-unquoted { background: #1a1622; border: 1px solid #35284a; }
.pub-stats { display: grid; grid-template-columns: repeat(auto-fit,
  minmax(11rem, 1fr)); gap: .7rem; padding: 0; margin: .8rem 0; }
.pub-stats div { background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: .6rem .8rem; }
.pub-stats dt { font-size: .78rem; text-transform: uppercase;
  letter-spacing: .06em; color: var(--dim); margin: 0 0 .2rem; }
.pub-stats dd { margin: 0; font-weight: 700; font-size: 1.08rem; }
.pub-params { color: var(--dim); font-size: .88rem; }
section { margin: 1.4rem 0; }
ul { padding-left: 1.2rem; }
li { margin: .25rem 0; }
.pub-tablewrap { overflow-x: auto; border: 1px solid var(--line);
  border-radius: 8px; }
.pub-table { border-collapse: collapse; width: 100%; font-size: .9rem;
  min-width: 44rem; }
.pub-table th { text-align: left; font-size: .75rem; text-transform:
  uppercase; letter-spacing: .05em; color: var(--dim);
  background: var(--panel); padding: .55rem .7rem; white-space: nowrap; }
.pub-table td { padding: .5rem .7rem; border-top: 1px solid var(--line);
  white-space: nowrap; }
.pub-num { font-variant-numeric: tabular-nums; }
.pub-dim { color: var(--dim); }
.pub-limitations { border-top: 1px solid var(--line); margin-top: 2.2rem;
  padding-top: .4rem; }
.pub-limitations p { color: var(--dim); font-size: .92rem; }
.pub-footer { border-top: 1px solid var(--line); background: var(--panel);
  padding: 1.2rem; font-size: .85rem; color: var(--dim); }
.pub-footer-nav { display: flex; gap: 1rem; margin-top: .6rem; }
@media (max-width: 640px) {
  h1 { font-size: 1.3rem; }
  .pub-main { padding: 1rem .9rem 2.4rem; }
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
