#!/usr/bin/env node
// scripts/verify_slate_failure_modes.mjs
//
// Slate Overview failure-mode verification WITHOUT a browser: boots the
// production server (PLAYWRIGHT=1 enables the __mock fixtures in the data
// layer) and asserts the rendered HTML. Mirrors the six cases in
// tests/slate-overview-failure-modes.spec.ts for environments where Playwright
// browsers cannot be installed. Exits non-zero on any failure.
//
// Requires a prior `npm run build`.

import { spawn } from "node:child_process";

const PORT = 3101;
const BASE = `http://127.0.0.1:${PORT}`;

function startServer() {
  return spawn("npx", ["next", "start", "-p", String(PORT)], {
    env: { ...process.env, PLAYWRIGHT: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function waitReady(timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE}/slate`);
      if (res.ok) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

const CASES = [
  {
    name: "CONFLICT blocks action with persistent banner",
    url: "/slate?__mock=conflict",
    assert: (html) =>
      html.includes('role="alert"') &&
      html.includes("FEED CONFLICT") &&
      /action locked/i.test(html) &&
      html.includes(">BLOCKED<"),
  },
  {
    name: "mixed VERIFIED and OBSERVED render distinct badges",
    url: "/slate?__mock=mixed_verification",
    assert: (html) =>
      html.includes('aria-label="Quote verified by hash audit"') &&
      html.includes('aria-label="Quote observed but not verified"'),
  },
  {
    name: "edge-positive OBSERVED renders BLOCKED, not QUALIFIED",
    url: "/slate?__mock=edge_positive_observed",
    assert: (html) =>
      html.includes(">BLOCKED<") &&
      html.includes("Quote not verified") &&
      !html.includes("watch only"),
  },
  {
    name: "hard gate clause failure names the clause",
    url: "/slate?__mock=hard_gate_fail",
    assert: (html) =>
      html.includes(">BLOCKED<") && html.includes("Gate failed: Edge"),
  },
  {
    name: "soft clause failure renders WATCH, not BLOCKED",
    url: "/slate?__mock=soft_gate_fail",
    assert: (html) => html.includes("watch only") && !html.includes(">BLOCKED<"),
  },
  {
    name: "primary vs secondary feed hierarchy (real artifacts)",
    url: "/slate",
    assert: (html) =>
      html.includes("Primary source") &&
      /secondary source/i.test(html) &&
      html.includes("not used for action"),
  },
  {
    name: "real route excludes synthetic quotes and never promotes legacy verification",
    url: "/slate",
    assert: (html) =>
      !html.includes("Synthetic Book") &&
      !html.includes('aria-label="Quote verified by hash audit"') &&
      html.includes("all execution is locked"),
  },
];

const child = startServer();
let exitCode = 0;

try {
  const ready = await waitReady();
  if (!ready) {
    console.error("FAIL: production server did not become ready");
    exitCode = 1;
  } else {
    console.log(`server up at ${BASE}\n`);
    for (const c of CASES) {
      let ok = false;
      let detail = "";
      try {
        const res = await fetch(`${BASE}${c.url}`);
        const html = await res.text();
        ok = res.ok && c.assert(html);
        if (!ok && !res.ok) detail = ` (HTTP ${res.status})`;
      } catch (err) {
        ok = false;
        detail = ` (${err.message})`;
      }
      console.log(`${ok ? "PASS" : "FAIL"}  ${c.name}${detail}`);
      if (!ok) exitCode = 1;
    }
  }
} finally {
  child.kill("SIGTERM");
  await new Promise((r) => setTimeout(r, 300));
  process.exit(exitCode);
}
