# Owner review response — messaging honesty + density pass (v145)

Implements every item from the 2026-10-27 review. Gate: **110/110** (108 + 2 new contract tests), headless-verified at 1280 + 1600 with zero console errors.

## 1. Messaging consistency (the core fix)

The actionable-empty state was claiming **"The market is efficient. Do not bet."** while the ribbon simultaneously said feeds were stale — a fail-closed board cannot also claim the market cleared itself. The panel is now **conditional on feed health**:

| Feed state | Panel |
|---|---|
| Odds/news **stale or error** (live data) | **Live qualification paused** — "Current prices cannot be verified. Model projections remain available for historical research." + **Last trusted quote: <time>** (now surfaced in the panel, not only the ribbon) |
| Fixture/demo data | unchanged honest fixture framing |
| **Fresh + verified**, genuinely zero qualified rows | "0 Qualified Plays Today — The market is efficient." (the claim is now *earned*) |

Pinned by 2 new tests in `feed-health.test.mjs` (stale → paused, fresh → efficiency). `render-robustness` tests updated to force fresh feeds — their regression target (the anti-tout gate interpolation) only executes on that branch.

## 2. Remaining refinements — all landed

- **CTA**: "Explore Full Modeled Slate (390)" → **"View 390 Research Projections"** (count is dynamic).
- **Membership chip**: "PRO · $29" → **"Upgrade"** — the static viewer is Observer-locked; the chip now reads as an action, never as an active membership.
- **Empty-panel height**: ~26% reduction (padding 44→26px, shield 38→26px, title 19→17px, tightened margins) across all three empty states.
- **Header density**: the "64/64 Verified" receipt badge — the widest chip, duplicating the polling widget's trust signal — is demoted below 1500px (visible on wide desktops); cluster separation widened, intra-cluster gaps tightened. This also retires the pre-existing 1280px topbar overflow.
- **Parity golden** re-captured via `PW_UPDATE_SNAPSHOTS=1` (announced change): chip copy, CTA label, empty-state copy under the harness's staged fresh feed. Note: the golden's stale-banner + anti-tout-panel pairing is a harness staging artifact (`authorizeSyntheticExecution` swaps in fresh health after the banner renders) — the live contract is pinned by the feed-health tests.

## 3. Data freshness — the commercial gate (not a design item)

The feeds are ~5½ days stale; no design change fixes that. The path is **B1 live ingestion** — `docs/B1-LINE-HISTORY-SPEC.md` §2 has the one-sitting decision table; the moment verified quotes flow, the terminal flips from "Live qualification paused" to actionable rows automatically (fail-closed by design, so it is also fail-open the instant data earns trust).

**Cache**: coherent **v145** (4 pages ×7 refs, SW name + precache, build-hash 2026-w7-v10; ledger subpage's stale `w7-v2` aligned).
