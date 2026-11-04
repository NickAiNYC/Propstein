# PropStein Reproducible Audit Specification

> **Thesis**: Any operator, researcher, or auditor can clone the repository, run `make verify`, and deterministically reproduce the exact cryptographic hashes, pre-kickoff snapshot constraints, and out-of-sample calibration metrics published on [propstein.com/performance/](https://propstein.com/performance/).

---

## 1. The Verification Command

```bash
make verify
```

Runs [scripts/verify_audit.py](file:///Users/nick/Desktop/Projects/PropStein/scripts/verify_audit.py) against committed artifacts without network calls or token requirements.

---

## 2. The Four Verification Checks

### Check 1: Cryptographic Ledger Root Hash
- **Anchor**: Published Root `#178e29974bf8748c` in `viewer/clv_audit_report.json` and on the live track-record page.
- **Verification**: Recomputes the SHA-256 digest of the canonical records array. Confirms that the prefix matches `178e29974bf8748c` without hash divergence.

### Check 2: Pre-Kickoff Prospective Timing & Snapshot Integrity
- **Anchor**: `snapshots/full_board_2026_w8_early_1300.jsonl` (472 candidate props).
- **Verification**:
  1. Validates that every candidate row contains an offset-aware ISO UTC timestamp (`captured_at`).
  2. Asserts that `captured_at < kickoff_at` strictly holds for every game. Post-kickoff records fail closed.
  3. Verifies that `record_sha256` exactly matches `canonical_json_sha256(payload)`.

### Check 3: Zero-Leakage Holdout & Negative Defect Transparency
- **Anchor**: `viewer/holdout_eval_2026_w1.json` (862 pre-kickoff snapshots).
- **Verification**:
  1. Asserts `decision_cutoff_enforced: true` and `excluded_future_snapshots: 0`.
  2. Re-asserts the raw model Brier score ($0.2813$) against the naive baseline ($0.2500$).
  3. Validates that Brier skill score is honestly published as **-12.51%** (published open defect, no cherry-picking).

### Check 4: Market-Model Blend & Commercial Freeze Gate
- **Anchor**: `viewer/edge_report.json`.
- **Verification**:
  1. Confirms full-board quoted sample size $N = 320$ ($\hat{w} = 0.7597$, 95% CI $[0.4001, 1.1193]$).
  2. Confirms trigger decision sample size $N = 37$ ($\hat{w} = 0.6742$, 95% CI $[-0.1013, +1.4497]$).
  3. Asserts that because the 95% CI spans zero, `ci_includes_zero: true` holds, paid features remain frozen, and beat-close guarantees are publicly withdrawn.

---

## 3. Independent External Anchoring

- **Sigstore / GPG Tags**: Releases and slate checkpoints carry cryptographic git signatures matching the author identity.
- **Third-Party Timestamping**: Future pre-kickoff snapshots are stamped via OpenTimestamps (`ots stamp`) before kickoff in the ingestion workflow, creating Bitcoin blockchain-anchored existence proofs.
