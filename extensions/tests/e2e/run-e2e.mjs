#!/usr/bin/env node
/**
 * PropStein Live Sniper — e2e runner.
 * ===================================
 * Ensures a FRESH dev build of the extension exists (the dev manifest carries
 * the localhost:4173 host permission the tests rely on), clears the persistent
 * Chromium profile so runs are reproducible, then runs the Playwright e2e
 * suite through `node --test` (Node 24 executes TypeScript natively).
 *
 * Exit code is passed through for CI.
 */
import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const extRoot = join(here, "..", "..");
const profileDir = "/tmp/propstein-e2e-profile";

// 1. Fresh Chromium profile: leftover extension state from a previous run
//    (granted origins, storage.session) would make tests non-deterministic.
rmSync(profileDir, { recursive: true, force: true });

// 2. Rebuild the extension so dist/ always matches the current sources.
console.log("[run-e2e] building extension (dev artifacts)…");
const build = spawnSync(process.execPath, ["scripts/build.mjs"], {
  cwd: extRoot,
  stdio: "inherit",
});
if (build.status !== 0) {
  console.error("[run-e2e] build failed — aborting");
  process.exit(build.status ?? 1);
}

// 3. Run the suite.
console.log("[run-e2e] launching Playwright e2e suite…");
const suite = spawnSync(
  process.execPath,
  ["--test", "--test-timeout=120000", "tests/e2e/live-sniper.e2e.ts"],
  { cwd: extRoot, stdio: "inherit" },
);
process.exit(suite.status ?? 1);
