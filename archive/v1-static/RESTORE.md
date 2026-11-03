# v1 Static Site — Archived (hidden, not routed, not deployed)

This is the **complete v1 public site** (PropStein / PropWire static viewer),
preserved in-repo when the 2.0 terminal replaced the v1 root — nothing was
deleted. It is "hidden" in the sense that:

- it is **not routed** by the Next.js app (lives outside `src/app`),
- it is **not deployed** by the 2.0 Vercel build (Next only ships build output),
- it is **excluded** from lint / typecheck / build tooling.

## What's in here

| path | contents |
| --- | --- |
| `index.html`, `app.js`, `style.css`, `sw.js`, `manifest.json` | v1 landing page + PWA shell |
| `viewer/` | the full static viewer: NFL player prop pages (per-player, per-market), NBA/UFC boards, legal, methodology, ledger, verify, audit pages |
| `public/` | ledger, audit, verify, public performance pages, book logos, league logos |
| `assets/` | seasonal artwork |
| `docs/` | v1 documentation (PAYMENTS, RUNBOOK, VERIFICATION_LAYER, EDGE_GATE, …) |
| `data/`, `snapshots/`, `evaluation/`, root `*.json` | the v1 data files the site fetches (picks, slates, snapshots, holdout evals) |
| `vercel.json`, `.vercelignore` | v1 deploy config, kept for reference |

## What is NOT in here (and where it lives)

The v1 **backend** (Python odds/grading/agents, `api/`, `app/`, `src/`,
`scripts/`, `tests/`, workflows) is not copied — it stays fully preserved in
git:

```
git fetch origin
git checkout v1-static-archive     # branch: exact pre-2.0 tree
git checkout v1.0.0                 # tag: same commit, frozen
git show v1.0.0:api/extension_router.py   # any single file, without checkout
```

`research/` (quant research) is **not archived** — it was kept live at the
repo root through the 2.0 migration.

## Using it later

Serve it locally (it's plain static files):

```bash
cd archive/v1-static
python3 -m http.server 8080        # http://localhost:8080
# or: npx serve .
```

Redeploy it as its own site (Vercel):

1. Vercel → Add New Project → point it at this repo.
2. Root Directory: `archive/v1-static`.
3. Framework preset: **Other** (no build step — output dir = repo root of that folder).

Or restore it as the main site: `git checkout v1-static-archive -- .` from
the repo root, or merge `v1-static-archive` back into `main`.

## Provenance

- Extracted verbatim from commit `25327c48` (`v1.0.0` / `v1-static-archive`)
  during the 2.0 migration on 2026-11-03.
- `main` continues to serve v1 until PR #99 (the 2.0 terminal) is reviewed,
  tested against a real database, and deliberately merged.
