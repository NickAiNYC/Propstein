# Ship-readiness: legal pack + B1 line-history spec

Two of the three announced ship-blockers, executed. (The third — repo settings — needs GitHub Administration permission the current PAT lacks; see owner checklist below.)

## 1. Legal pack (generated pages, not hand-written HTML)

`/legal/terms/`, `/legal/privacy/`, `/legal/responsible-gaming/` — built by the existing B4 generator (`scripts/build_public_pages.py`), so they inherit the whole page system: canonical + OG + JSON-LD, `/public.css`, CSP-safe, sitemap'd.

- **Terms**: research-not-advice framing, no-wager/no-money-handled, 21+/jurisdiction, no-warranty + liability limits, acceptable use, trademark non-affiliation.
- **Privacy**: no accounts / no personal data, localStorage-only preferences, hosting logs, aggregate-only analytics, no ad-tech, children, security.
- **Responsible Gaming**: budget-first guidance, limits + self-exclusion, warning signs, 1-800-GAMBLER / NCPG / Gamblers Anonymous, explicit operator commitments ("no locks, ever").

Site-wide: every one of the 787 public pages now carries Terms/Privacy/RG links in its footer. Sitemap 788 → **791**. Test suite co-evolved (+1 test: legal CSP/disclaimer/footer-link/RG assertions; sitemap-parity includes `legal/`). **Gate: 108/108.**

⚠️ **Not legal advice.** Bracketed placeholders (`[STATE]`, `[CONTACT EMAIL]`, `[HOSTING PROVIDER]`) are deliberate — fill them and have counsel review before relying on the documents.

**No cache bump**: terminal assets untouched (public pages sit outside the SW-versioned surface — same class as B4's 784-page PR).

## 2. B1 line-history spec (`docs/B1-LINE-HISTORY-SPEC.md`)

The "secret sauce" operationalized so the owner decision can happen in one sitting: provider decision table (§2), SQLite DDL with Postgres escape hatch (§3), adaptive capture cadence incl. pre-kickoff + news sprints (§4), the four unlocked surfaces — continuous CLV, public-page sparklines, best-line board, steam alerts (§5), static JSON API contract (§6), P1–P4 rollout (§7), open items (§8).

Forward-only reality: **every week uncaptured is history that can never be backfilled.**

## Owner checklist (unchanged PAT-less items)

1. **Vercel: Deployment Protection OFF for production** — the site currently 302s behind Vercel auth; nothing is publicly reachable (verified 2026-10-27).
2. PAT revoke (admin scope, crossed chats).
3. Repo settings via UI (403 via API): description + topics + homepage; branch protection on `main` (require `regression-tests`); secret-scanning push protection + Dependabot.
4. Search Console + Bing **after** #1 is fixed; custom domain before SEO accrues to `propwire.vercel.app`.
