# PropStein Runbook — decisions and operations

Decisions are recorded here with their rationale and, where applicable, their
executable procedure. "Recorded" is not "done": each section states its own
status.

## Production safety defaults

- **Fail closed.** Missing authentication, entitlement, provenance, or
  verification configuration disables the protected operation. Local bypasses
  must be explicit, narrowly scoped, and off by default. Never place fallback
  credentials in source.
- **A green build is not a freshness check.** Unit tests validate application
  behavior; scheduled workflows, deployment targeting, live endpoint auth, and
  feed freshness require their own recorded verification.

## Vercel project topology (merge gate active)

- `propwire` is the production project and publishes `viewer/` from repository
  root using the root `vercel.json`.
- `propwire-github` is currently an unintended duplicate Git integration. Its
  PR check is advisory and does **not** validate the production project.
- Do not merge a Vercel-affecting PR until the duplicate Git integration is
  disconnected/archived in Vercel and the `propwire` project has produced the
  required preview/check. Do not promote or copy deployments between these two
  projects; they have independent settings and rollback histories.
- After merge, production deployment must originate from `propwire` and be
  verified against the merged Git SHA before the change is called live.

---

## D1 — `.venv` history rewrite (status: PROCEDURE WRITTEN, awaiting merge + authorization)

**Problem.** `.venv/` (10,817 files) is tracked in `main`'s history (measured:
`git ls-tree -r 421dda9 --name-only | grep -c '^\.venv/'` → 10817; pack
`git count-objects -vH` → size-pack 98.96 MiB). It merged into shared history
with PR #2. Every additional merge raises the eventual rewrite cost.

**Sequencing decision — Option A: hotfix merge → rewrite → freeze.**

Chosen over "rewrite first → hotfix rebases" because:

1. The hotfix content is production-urgent and already audited; rebasing it
   only adds risk and a one-cycle delay.
2. The rewrite is a single atomic operation over ALL history — it captures
   the hotfix commits at zero extra cost (hotfix files are small).
3. The freeze window (merge → rewrite) is hours, not weeks, and is governed
   by the rule below.

**FREEZE RULE (binding):** between the hotfix merge and the completed rewrite
+ force-push, NO new PRs open and NO new branches are pushed. Any work started
in that window rebases afterwards at its author's cost.

### Prerequisites (hard gates — do not skip)

- [ ] Hotfix PR merged; `origin/main` contains it.
- [ ] **Secrets scan of full history is CLEAN** (if it is not, this operation
  becomes URGENT and additionally requires a GitHub Support ticket for
  server-side purge — see "Limits" below):
  ```bash
  # from a fresh full clone; requires gitleaks or trufflehog, or use the
  # grep fallback below for the known patterns
  git clone https://github.com/NickAiNYC/propwire.git d1-scratch && cd d1-scratch
  git log --all -p | grep -nE 'github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}' | head
  # expected: no output
  ```
- [ ] **EXPLICIT force-push authorization from the repo owner is posted in
  writing** (issue/PR comment or chat log: "D1 force-push authorized").
  The standing "never force-push main" rule is suspended ONLY for this
  operation and ONLY by that written authorization.
- [ ] Capture the rollback SHA immediately before the rewrite push; scheduled
  automation can advance `main` after authorization:
  ```bash
  ROLLBACK_SHA=$(git ls-remote origin refs/heads/main | cut -f1)
  test -n "$ROLLBACK_SHA" && printf 'rollback main: %s\n' "$ROLLBACK_SHA"
  ```

### Procedure

```bash
# 0. Backup bundle (rollback anchor; keep 30 days)
git bundle create ../propwire-pre-d1-backup.bundle --all

# 1. Fresh clone (git-filter-repo requires one; it refuses dirty/non-fresh trees)
cd .. && git clone https://github.com/NickAiNYC/propwire.git propwire-d1 && cd propwire-d1

# 2. Rewrite .venv out of all history
pip install git-filter-repo
git filter-repo --path .venv --invert-paths
#    (filter-repo strips the origin remote by design)

# 3. Verify locally BEFORE pushing
git log --all --oneline -- .venv | wc -l                 # expected: 0
git ls-tree -r main --name-only | grep -c '^\.venv/' || echo 0   # expected: 0
git count-objects -vH | grep size-pack                   # expected: single-digit MiB
node --test 2>&1 | grep -E '^ℹ (tests|pass|fail)'        # expected: 83 / 83 / 0
python3 -m pytest tests/ -q                              # expected: all pass

# 4. Re-add origin and force-push main (REQUIRES the authorization gate above)
git remote add origin https://github.com/NickAiNYC/propwire.git
git push --force origin main

# 5. Delete stale remote branches whose histories embed .venv (merged already):
git push origin --delete phase/1-adapter phase/2-nba propwire-ui-redesign 2>/dev/null || true

# 6. ALL local clones are now invalid — both Nick's and the agent's:
#    rm -rf the old clone, fresh clone from origin. No exceptions, no
#    "I'll just reset --hard" — old SHAs are divergent by construction.
```

### Post-operation state and limits (read before claiming anything)

- **Post-rewrite deploy:** after the D1 force-push and green CI on the rewritten
  SHA, create and verify a new Vercel production deployment from repository
  root. D1 does not redeploy the site; until this step finishes, GitHub `main`
  and the live product intentionally point at different trees. Record both the
  rewritten Git SHA and resulting Vercel deployment URL in the operation log.

- `refs/pull/*` on GitHub are **not rewritten** by a force-push; GitHub keeps
  pre-rewrite objects reachable via PR refs until its own GC. Consequences:
  - New clones of `main` are small (clone fetches `refs/heads/*`, not
    `refs/pull/*`) — the bloat problem IS solved for everyone cloning.
  - The old blobs are not "gone from GitHub's servers"; if a future secrets
    purge ever requires true erasure, that is a GitHub Support request.
- Open PRs: none may exist during the operation (FREEZE RULE). The first PR
  after the rewrite (Q1 api-hardening) opens from the fresh clone against
  the new `main`.
- Tags: `production-2026-10-20`, `v1.2.0` point at pre-rewrite history. They
  are historical markers; decide explicitly: either delete/re-tag them to
  post-rewrite SHAs in the same operation (preferred), or leave them and
  accept that fetching tags pulls the old pack:
  ```bash
  git tag -l | xargs -n1 git push --delete origin   # then re-tag from new main
  ```
- Rollback: force-push the backup bundle's `main` back (requires the same
  authorization), or simply restore from the bundle locally.

### In-flight work at operation time

| Branch | State | Action |
|---|---|---|
| `hotfix/provenance-and-demo-ledger` | merged pre-rewrite | delete remote branch post-rewrite |
| `phase/1-adapter` | merged (PR #1) | delete remote branch post-rewrite |
| `phase/2-nba` | merged (PR #2) | delete remote branch post-rewrite |
| `propwire-ui-redesign` | historical | delete (superseded) |
| Q1 api-hardening | not yet opened | open AFTER rewrite from fresh clone |

---

## D2 — `tests/` vs `test/` consolidation (status: DEFERRED with trigger)

Python tests live in `tests/`, node tests in `test/`. Consolidation into one
directory was considered and deferred: node's `--test` discovery and the
parity snapshot paths (`test/snapshots/nfl/*`) are wired to `test/`, and
pytest config to `tests/`. **Trigger to revisit:** the first time a CI
misconfiguration (wrong glob, missed directory) causes a suite to be silently
skipped. Until then the split is documented, not accidental.

---

## D3 — demo ingest endpoint fail-visible behavior change (status: ACCEPTED)

The demo ingest endpoint's behavior change (fail-visible instead of silent
success) is recorded and accepted. No further action.

---

## Q1 — paywall fail-closed + CORS scoping (status: CONFIRMED next hotfix)

`api/main.py` currently fails OPEN on paywall checks when `WHOP_API_KEY` is
absent (returns active). Confirmed as the next hotfix: fail-closed, with an
explicit `ALLOW_UNAUTHED_DEV=1` dev opt-in. CORS `allow_origins=["*"]` is
scoped to explicit origins in the same PR. Both land together in one
api-hardening PR, opened after the D1 rewrite completes.
