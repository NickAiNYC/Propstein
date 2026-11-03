import { test } from "node:test";
import assert from "node:assert/strict";
import { auditRecord } from "../../apps/chrome/src/trial-audit.ts";

test("trial journal distinguishes displayed demo from suppressed real observation", () => {
  const at = "2026-10-31T12:00:00.000Z";
  const demo = auditRecord("ADDED", at, undefined, {
    signalKey: "demo", state: "ALERTABLE", withdrawn: false,
    observed: { source: "demobook", sport: "football", league: "NFL", playerName: "Test Player",
      marketType: "drive", marketLabel: "drive", selection: "YES", marketStatus: "OPEN",
      observedAt: at, adapterVersion: "fixture", detectionConfidence: 1, provenance: "synthetic-fixture" },
    quoteAgeMs: 0, evaluatedAt: at, reasons: [],
  });
  assert.equal(demo.mode, "synthetic-demo");
  assert.equal(demo.displayed, true);
  const blocked = auditRecord("STATE_CHANGED", at, undefined, {
    ...demo.snapshot!, signalKey: "real", observed: { ...demo.snapshot!.observed, source: "fanduel", provenance: "visible-page" },
    state: "STALE", withdrawn: true, withdrawalReason: "NO_DRIVE_CONTEXT",
  });
  assert.equal(blocked.mode, "read-only-trial");
  assert.equal(blocked.displayed, false);
  assert.deepEqual(blocked.reasonCodes, ["NO_DRIVE_CONTEXT"]);
});
