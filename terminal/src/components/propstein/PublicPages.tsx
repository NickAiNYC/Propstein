"use client";

/* ============================================================
   PropStein — public research pages (Phase 5)
   Static-style pages sharing the terminal's identity: no auth,
   no client-side data dependency for core reading, structured
   headings, and accurate inline visualizations instead of
   text-only explanations.
   ============================================================ */

import { useApp } from "@/lib/propstein/router";
import { Panel } from "./primitives";
import { BoundaryDiagram } from "./charts/BoundaryDiagram";
import { computeValueBoundaries } from "@/lib/propstein/model";
import { fmtPct, fmtSigned } from "@/lib/propstein/format";
import { GOVERNANCE } from "@/lib/propstein/types";
import { ARCHIVE_COHORT } from "@/lib/propstein/archive";
import { ArrowRight } from "lucide-react";

/* ================= Methodology ================= */

export function MethodologyPage() {
  return (
    <article className="mx-auto flex max-w-[820px] flex-col gap-6">
      <header>
        <p className="label-micro">Public research · indexable</p>
        <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight text-text">
          Methodology
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-text-muted">
          PropStein models NFL receiving markets as full probability distributions, not point
          estimates. Every published figure on a player page is derived from the exact laws below,
          with fitted parameters and provenance attached. This page documents the specification the
          way an audit would need it.
        </p>
      </header>

      <Section title="1 · Reception counts — Negative Binomial">
        <p>
          A receiver&apos;s catch count in a game is a small, overdispersed integer. PropStein models
          receptions <MathN>N</MathN> with a Negative Binomial (NB2) law: a mean{" "}
          <MathN>μ</MathN> fitted from opponent-adjusted target volume over the training window, and
          a dispersion <MathN>r</MathN> that widens or tightens the spread around that mean.
        </p>
        <Formula>{"P(N = k) = Γ(k+r) / (Γ(r) k!) · (r/(r+μ))^r · (μ/(r+μ))^k"}</Formula>
        <p>
          The variance <MathN>μ + μ²/r</MathN> exceeds the mean — real target counts are clumpier
          than a Poisson would allow. A low-dispersion volume anchor (high snap and target share)
          yields a tall, narrow distribution; a boom-bust deep threat yields a flat, fat-tailed one.
          The <strong>median</strong> of this law is the published <em>fair line</em>; the{" "}
          <strong>mean</strong> is the <em>projected volume</em>. Right skew keeps the mean above
          the median, and the two are never conflated.
        </p>
      </Section>

      <Section title="2 · Yards per reception — Gamma">
        <p>
          Each catch&apos;s yardage is modeled as a Gamma draw with shape <MathN>k</MathN> and scale{" "}
          <MathN>θ</MathN>, fitted by route-depth mix. Slot separators have high{" "}
          <MathN>k</MathN> (consistent 8–12 yard gains); boundary shot specialists have low{" "}
          <MathN>k</MathN> with a long right tail. The mean gain is <MathN>kθ</MathN>.
        </p>
      </Section>

      <Section title="3 · Total yards — the exact compound law" id="compound">
        <p>
          Receiving yards <MathN>Y</MathN> are the sum of a random number of Gamma gains:{" "}
          <MathN>Y = X₁ + … + X_N</MathN>, with <MathN>N</MathN> the NB reception count. Because the
          sum of <MathN>n</MathN> independent Gamma(k, θ) variables is exactly Gamma(nk, θ), the
          yards law is available in closed form as a mixture:
        </p>
        <Formula>{"P(Y ≤ y) = Σₙ P(N = n) · Γ-CDF(nk, y/θ)"}</Formula>
        <p>
          Since model v3.0.0 this compound is computed exactly — the earlier normal approximation
          was retired because it understated both tails, exactly where prop lines live. A receiver
          can finish with zero yards: <MathN>P(Y = 0) = P(N = 0)</MathN> is an atom at zero, visible
          on every yards chart as a marked point.
        </p>
      </Section>

      <Section title="4 · NBA markets — overdispersed count laws">
        <p>
          NBA points, rebounds, and assists are modeled as Negative Binomial (NB2) counts. Each
          market publishes its own dispersion parameter <Formula>r</Formula> alongside the mean{" "}
          <Formula>μ</Formula>: scoring events cluster (free-throw trips, hot stretches, late-game
          fouling), rebounds alternate with opponent possessions, and assists inherit shot-making
          variance from teammates — so a Poisson law would understate dispersion. The NB2 variance{" "}
          <Formula>μ + μ²/r</Formula> admits that clustering explicitly, and every fair line,
          probability, and boundary on an NBA research page is computed from the published{" "}
          <Formula>(r, μ)</Formula> pair — the same fail-closed contracts as the receiving markets.
        </p>
        <p className="mt-2">
          NBA markets launched with the Nov 6, 2026 slate; they have no settled evaluation history
          yet, and the public audit will not include them until markets settle under the same
          full-board rules.
        </p>
      </Section>

      <Section title="5 · Fair lines, value boundaries, and evidence" id="evidence">
        <p>
          The <strong>fair line</strong> is the model median — the threshold the model puts at
          50/50. It is not a prediction to bet; it is a reference point. Market comparison happens
          through <strong>value boundaries</strong>: the range of lines where neither side of a
          captured quote clears its break-even probability against the model. The{" "}
          <span className="text-sapphire">value boundaries page</span> derives this in full.
        </p>
        <p>
          Every captured quote carries a <strong>source</strong>, a{" "}
          <strong>capture timestamp</strong>, and an <strong>evidence state</strong>. The states
          fail closed:
        </p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {[
            ["VERIFIED", "captured from a primary feed and independently confirmed against a second source"],
            ["OBSERVED — UNVERIFIED", "captured from a single source; not yet independently confirmed"],
            ["STALE", "captured but old relative to kickoff — presented as archived context, never as current"],
            ["MODEL ONLY", "no quote captured; figures are model output alone"],
            ["UNAVAILABLE", "market data not present for this market in the snapshot"],
            ["ARCHIVED", "event completed; the market is preserved as a settled historical record"],
          ].map(([term, def]) => (
            <li key={term} className="text-xs leading-relaxed text-text-muted">
              <span className="font-data font-medium text-text">{term}</span> — {def}
            </li>
          ))}
        </ul>
        <p className="mt-2">
          A product-posture badge (Research mode) links here but never overrides these states: a
          stale quote reads STALE next to its numbers, regardless of the terminal&apos;s posture.
        </p>
      </Section>

      <Section title="6 · Evaluation, not marketing">
        <p>
          All evaluation is full-board: every market with a captured closing line is graded,
          exclusions are itemized, and results — favorable or not — are published on the{" "}
          <span className="text-sapphire">performance &amp; audit page</span>. The current
          evaluable cohort is <strong className="font-data">{ARCHIVE_COHORT.evaluable}</strong>{" "}
          markets. Commercial tiers remain frozen until the preregistered confirmatory gate (
          {"N"} ≥ {GOVERNANCE.confirmatoryThreshold} per sport) passes; passing the earlier
          screening threshold ({GOVERNANCE.screenedThreshold}) changes nothing by itself.
        </p>
        <p>
          No staking, bankroll, or bet-sizing output exists anywhere in the product, by design.
        </p>
      </Section>

      <Section title="7 · Provenance">
        <p>
          Each projection records its model version, training window, production timestamp, and
          snapshot lineage key, so any published figure can be traced to the exact capture that
          produced it. Weekly snapshots are retained; historical markets are never re-derived with
          later model versions.
        </p>
      </Section>

      <nav className="flex flex-wrap gap-3 border-t border-hairline pt-5">
        <InlineLink href="#/research/value-boundaries">Value boundaries explained</InlineLink>
        <InlineLink href="#/performance">Performance &amp; audit</InlineLink>
        <InlineLink href="#/players">Player index</InlineLink>
      </nav>
    </article>
  );
}

/* ================= Value boundaries ================= */

export function ValueBoundariesPage() {
  // worked example with the exact math shown live
  const example = {
    name: "Worked example — receptions",
    law: { kind: "negbin" as const, nb: { r: 6.0, mu: 5.6 } },
    overOdds: -110,
    underOdds: -110,
  };
  const boundaries = computeValueBoundaries(example.law, example.overOdds, example.underOdds, 4.5);

  return (
    <article className="mx-auto flex max-w-[820px] flex-col gap-6">
      <header>
        <p className="label-micro">Public research · indexable</p>
        <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight text-text">
          Value boundaries
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-text-muted">
          A prop price is not a probability. This page shows exactly how PropStein converts captured
          prices into break-even probabilities, and how the model distribution defines the band of
          lines where neither side of a quote clears break-even — the no-value band.
        </p>
      </header>

      <Section title="1 · From odds to break-even probability">
        <p>
          American odds imply the win probability at which a bet exactly breaks even. At{" "}
          <MathN>−110</MathN>, you risk 110 to win 100, so the break-even probability is{" "}
          <MathN>110/210 = 52.38%</MathN>. At <MathN>+150</MathN> it is{" "}
          <MathN>100/250 = 40%</MathN>.
        </p>
        <Formula>{"p_be(odds<0) = |odds| / (|odds| + 100)     p_be(odds>0) = 100 / (odds + 100)"}</Formula>
        <p>
          A two-sided quote at <MathN>−110 / −110</MathN> sums to{" "}
          <MathN>104.76%</MathN> — the bookmaker&apos;s hold. Removing the vig by normalization
          gives the fair market probability: 50/50 for a symmetric quote.
        </p>
      </Section>

      <Section title="2 · Where each side clears">
        <p>
          Against the model, the over at line <MathN>L</MathN> clears break-even when{" "}
          <MathN>P(X ≥ L) &gt; p_be(over)</MathN>. Because the survival function decreases in{" "}
          <MathN>L</MathN>, that holds for every line below a single boundary point{" "}
          <MathN>L_over</MathN> where survival crosses the over threshold. Symmetrically, the under
          clears for every line above <MathN>L_under</MathN>.
        </p>
        <Formula>{"no-value band = [ S⁻¹(p_be(over)), F⁻¹(p_be(under)) ]"}</Formula>
      </Section>

      <Section title="3 · The band, visualized">
        <p>
          Below is a live worked example: receptions with NB2 parameters{" "}
          <MathN>r = 6.0, μ = 5.6</MathN>, quoted at <MathN>−110</MathN> both sides. The curve is
          the model survival function; the dashed thresholds are the two break-even probabilities;
          the shaded interval is the no-value band.
        </p>
        <div className="mt-3 rounded-[4px] border border-hairline bg-workspace p-4">
          <BoundaryDiagram
            law={example.law}
            boundaries={boundaries}
            quoteLine={4.5}
            market="receptions"
            height={200}
          />
          <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-hairline pt-3 text-xs sm:grid-cols-4">
            <div>
              <dt className="label-micro">Over break-even</dt>
              <dd className="mt-1 font-data text-text">{fmtPct(boundaries.breakEvenOver, 2)}</dd>
            </div>
            <div>
              <dt className="label-micro">Under break-even</dt>
              <dd className="mt-1 font-data text-text">{fmtPct(boundaries.breakEvenUnder, 2)}</dd>
            </div>
            <div>
              <dt className="label-micro">Band lower</dt>
              <dd className="mt-1 font-data text-text">{boundaries.lower.toFixed(2)}</dd>
            </div>
            <div>
              <dt className="label-micro">Band upper</dt>
              <dd className="mt-1 font-data text-text">{boundaries.upper.toFixed(2)}</dd>
            </div>
          </dl>
        </div>
        <p className="mt-3">
          For discrete markets the band can collapse to a point or contain no tradable half-step
          line — at <MathN>−110</MathN> both sides, one side of every line often clears. The player
          page states this plainly when it happens rather than shading a decorative band.
        </p>
      </Section>

      <Section title="4 · What the band is not">
        <p>
          The band is a <strong>measurement</strong>, not a recommendation. A captured line outside
          the band means the model probability diverges from the price-implied probability by more
          than the vig — it does not mean the model is right. Prices move for information the model
          does not have; that is why every player page lists invalidation factors next to the
          distribution, and why the terminal publishes its full calibration record instead of
          selected wins.
        </p>
      </Section>

      <nav className="flex flex-wrap gap-3 border-t border-hairline pt-5">
        <InlineLink href="#/research/methodology">Methodology</InlineLink>
        <InlineLink href="#/performance">Performance &amp; audit</InlineLink>
      </nav>
    </article>
  );
}

/* ================= shared bits ================= */

function Section({
  title,
  id,
  children,
}: {
  title: string;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="hairline-t border-hairline pt-5 first:border-0 first:pt-0">
      <h2 className="font-display text-lg font-semibold tracking-tight text-text">{title}</h2>
      <div className="mt-2.5 flex flex-col gap-3 text-sm leading-relaxed text-text-muted [&_strong]:text-text [&_strong]:font-medium">
        {children}
      </div>
    </section>
  );
}

function Formula({ children }: { children: string }) {
  return (
    <p className="overflow-x-auto rounded-[4px] border border-hairline bg-workspace px-4 py-3 font-data text-[13px] text-text">
      {children}
    </p>
  );
}

function MathN({ children }: { children: React.ReactNode }) {
  return <span className="font-data text-[0.92em] text-text">{children}</span>;
}

function InlineLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => (window.location.hash = href.slice(1))}
      className="flex items-center gap-1 text-xs text-sapphire transition-colors hover:text-sapphire-hover"
    >
      {children}
      <ArrowRight className="h-3 w-3" aria-hidden />
    </button>
  );
}
