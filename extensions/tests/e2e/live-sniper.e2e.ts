/**
 * PropStein Live Sniper — End-to-end tests (real Chromium via Playwright).
 * ==========================================================================
 * Loads the DEV build of the Chrome extension (localhost host permission
 * pre-granted via manifest.dev.json), serves the DemoBook fixture locally,
 * and drives the ENTIRE stack:
 *
 *   demo page DOM → content bridge → MutationObserver batching →
 *   background validation → normalization → matching → DRIVE-REC-V1 →
 *   signal state machine → companion panel UI
 *
 * Covers the four CRITICAL tests from spec §15 that require a real browser:
 *   1. +160 → +115 odds change forces re-evaluation on the NEW price
 *   2. drive end invalidates every signal on that drive
 *   3. suspension withdraws the signal
 *   4. viewport/observer wiring works in a real layout engine
 *
 * NOTE: The Chrome side panel itself is not scriptable by Playwright; the
 * companion page (chrome-extension://…/web-companion/index.html) runs the
 * IDENTICAL panel bundle and bridges to the same background service worker,
 * so the panel code path is fully exercised.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { Browser, BrowserContext, Page } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const extRoot = join(here, "..", "..");
const devExtPath = join(extRoot, "dist", "propstein-chrome-dev");
const demoHtmlPath = join(extRoot, "demo", "demo-sportsbook.html");
const DEMO_PORT = 4173;

let browser: Browser | undefined;
let context: BrowserContext | undefined;
let demoPage: Page | undefined;
let panelPage: Page | undefined;
let server: import("node:http").Server | undefined;

async function startDemoServer(): Promise<void> {
  const html = await readFile(demoHtmlPath, "utf8");
  const srv = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    res.end(html);
  });
  server = srv;
  await new Promise<void>((resolve) => srv.listen(DEMO_PORT, "127.0.0.1", resolve));
}

async function extensionId(): Promise<string> {
  // Extension service workers are exposed via context.serviceWorkers(),
  // not through pages(). Wait for the worker to register (it starts on load
  // via the onInstalled event).
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const sw = context?.serviceWorkers()?.[0];
    if (sw) {
      const url = sw.url();
      const m = /^chrome-extension:\/\/([^/]+)\//.exec(url);
      if (m) return m[1]!;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("extension service worker never started");
}

test.before(async () => {
  await startDemoServer();
  context = await chromium.launchPersistentContext("/tmp/propstein-e2e-profile", {
    ...(process.env.PROPSTEIN_E2E_CHROME ? { executablePath: process.env.PROPSTEIN_E2E_CHROME } : {}),
    // channel "chromium" = full browser binary in NEW headless mode, which
    // is required for extension loading (the headless shell has no
    // extension support).
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${devExtPath}`,
      `--load-extension=${devExtPath}`,
      "--no-sandbox",
      "--disable-dev-shm-usage",
    ],
    viewport: { width: 1280, height: 800 },
  });
  browser = context.browser()!;
  // Wake the service worker with a throwaway tab FIRST, so every tabs
  // listener is registered before the monitored page loads (deterministic
  // lastContentTab capture — no startup race).
  const wake = await context.newPage();
  await wake.goto("about:blank");
  const extId = await extensionId();
  assert.ok(extId, "extension service worker did not start");
  // Open the demo fixture through the extension itself: OPEN_DEMO_PAGE both
  // creates the tab and records it as the tracked content tab in the
  // background worker, eliminating any dependence on tab-event timing.
  panelPage = await context.newPage();
  await panelPage.goto(`chrome-extension://${extId}/web-companion/index.html`, { waitUntil: "networkidle" });
  const demoOpened = context.waitForEvent("page");
  await panelPage.evaluate(() => {
    void (globalThis as { chrome?: { runtime: { sendMessage(m: unknown): Promise<unknown> } } }).chrome?.runtime.sendMessage({ type: "OPEN_DEMO_PAGE" });
  });
  demoPage = await demoOpened;
  await demoPage.goto(`http://localhost:${DEMO_PORT}/demobook`, { waitUntil: "networkidle" });
  await wake.close().catch(() => undefined);
});

test.after(async () => {
  await context?.close().catch(() => undefined);
  await browser?.close().catch(() => undefined);
  await new Promise<void>((resolve) => server?.close(() => resolve()));
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function clickStartMonitoring(): Promise<void> {
  // The panel state refreshes on a 2s poll; wait until the panel has actually
  // observed the tracked content tab (READY TO MONITOR) before clicking, so
  // the click never routes through the openDemoPage fallback.
  await waitForPanel((t) => t.includes("READY TO MONITOR"), 20_000, "(ready to monitor)");
  await panelPage!.evaluate(() => {
    const view = document.querySelector(".state-view");
    const btns = Array.from((view ?? document).querySelectorAll("button"));
    const start = btns.find((b) => b.textContent?.trim() === "START MONITORING")
      ?? Array.from(document.querySelectorAll("button")).find((b) => b.textContent?.trim() === "START MONITORING");
    if (start) (start as HTMLElement).click();
  });
}

async function panelTexts(): Promise<string> {
  return panelPage!.evaluate(() => document.body.innerText);
}

async function waitForPanel(pred: (text: string) => boolean, timeoutMs = 15_000, label = ""): Promise<string> {
  const started = Date.now();
  let last = "";
  while (Date.now() - started < timeoutMs) {
    last = (await panelTexts()) || "";
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`panel condition not met within ${timeoutMs}ms ${label}\n--- last text ---\n${last.slice(0, 2000)}`);
}

// ---------------------------------------------------------------------------
// The critical e2e scenarios
// ---------------------------------------------------------------------------

test("e2e: manifest loads, service worker runs, panel renders the terminal UI", async () => {
  const text = await waitForPanel((t) => t.includes("PROPSTEIN") && t.includes("LIVE SNIPER"), 20_000, "(brand header)");
  assert.ok(text.includes("SIGN IN REQUIRED") || text.includes("PRO") || text.includes("NO SUPPORTED TAB"), "entitlement state visible");
});

test("e2e: monitoring the demo page produces four priced signal cards with exact spec values", async () => {
  await clickStartMonitoring();
  const text = await waitForPanel(
    (t) => t.includes("Travis Kelce") && t.includes("+160") && t.includes("38.46%") && t.includes("44.0%") && t.includes("+14.4%"),
    20_000,
    "(Kelce card with spec example values)",
  );
  assert.ok(text.includes("MONITORING"), "status shows MONITORING");
  assert.ok(text.includes("Rashee Rice"), "Rice card present");
  assert.ok(text.includes("Hunter Henry"), "Henry card present");
  assert.ok(text.includes("Juwan Johnson"), "Johnson card present");
  assert.ok(text.includes("DRIVE-REC-V1"), "model version shown");
  assert.ok(text.includes("UNCALIBRATED"), "honest confidence label shown");
  assert.ok(text.includes("SYNTHETIC DEMO PAGE"), "source shown honestly as synthetic");
  assert.ok(text.includes("SYNTHETIC") || text.includes("DEMO"), "synthetic provenance visible");
  // Kelce must be the alertable one; Henry/Johnson negative EV.
  assert.ok(text.includes("ALERTABLE"), "at least one alertable signal");
});

test("e2e CRITICAL: odds change +160 → +115 recomputes break-even and EV on the NEW price", async () => {
  await demoPage!.click("#btn-move");
  const text = await waitForPanel(
    (t) => {
      const kelceRegion = extractKelceRegion(t);
      return kelceRegion.includes("+115") && kelceRegion.includes("46.51%");
    },
    20_000,
    "(Kelce re-priced at +115)",
  );
  const kelce = extractKelceRegion(text);
  // +115 → decimal 2.15 → break-even 46.51%; EV = .44*1.15-.56 = -5.4%
  assert.ok(kelce.includes("-5.4%"), `EV recomputed negative on +115 — got region:\n${kelce}`);
  assert.ok(!kelceRegionIsAlertable(kelce), "Kelce no longer alertable after the price move");
});

test("e2e CRITICAL: market suspension withdraws the Kelce signal", async () => {
  await demoPage!.click("#btn-suspend");
  await waitForPanel(
    (t) => {
      const k = extractKelceRegion(t);
      return k.includes("SUSPENDED");
    },
    20_000,
    "(Kelce suspended)",
  );
});

test("e2e CRITICAL: drive end invalidates every signal tied to the old drive", async () => {
  // Reset the fixture to restore OPEN markets first. Waiting for a FRESH
  // ALERTABLE +160 evaluation (break-even 38.46%) — not the suspended card's
  // cached display — proves re-detection ran after the reload.
  await demoPage!.reload({ waitUntil: "networkidle" });
  await waitForPanel(
    (t) => {
      const k = extractKelceRegion(t);
      return k.includes("+160") && k.includes("38.46%") && k.includes("ALERTABLE");
    },
    20_000,
    "(fixture reset to a fresh +160 evaluation)",
  );
  await demoPage!.click("#btn-drive-end");
  // Every signal bound to d4 must be withdrawn AND rendered as DRIVE ENDED —
  // the panel keeps withdrawn cards visible so the invalidation is auditable,
  // never silent — while the fixture's re-bound d5 market set starts a fresh
  // signal set on the new drive.
  const text = await waitForPanel(
    (t) => (t.match(/DRIVE ENDED/g) ?? []).length >= 4,
    20_000,
    "(all four d4 signals invalidated)",
  );
  assert.ok(text.includes("drive d4 ended"), "withdrawal reason names the ended drive");
  // The new drive's Kelce market re-binds as a LIVE signal (rendered before
  // the withdrawn section, so the first Kelce card is the fresh one).
  const kelce = extractKelceRegion(text);
  assert.ok(kelce.includes("+160"), `new-drive Kelce signal is live — got region:\n${kelce}`);
  assert.ok(!kelce.includes("DRIVE ENDED"), "the live Kelce card is not the withdrawn d4 card");
});

test("e2e: stopping monitoring withdraws all signals", async () => {
  await panelPage!.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("button"));
    const stop = btns.find((b) => b.textContent?.trim() === "PAUSE MONITORING");
    if (stop) (stop as HTMLElement).click();
  });
  const text = await waitForPanel((t) => !t.includes("PAUSE MONITORING"), 15_000, "(monitoring stopped)");
  assert.ok(!text.includes("Travis Kelce"), "signals cleared after stop");
});

test("e2e: trial journal exports observed, repriced, and suspended decisions", async () => {
  const result = await panelPage!.evaluate(async () => {
    return (globalThis as { chrome: { runtime: { sendMessage(m: unknown): Promise<unknown> } } })
      .chrome.runtime.sendMessage({ type: "GET_AUDIT" });
  }) as { records?: Array<{ kind: string; reasonCodes: string[]; mode: string }>; error?: string };
  assert.equal(result.error, undefined);
  assert.ok((result.records?.length ?? 0) >= 4, "journal has the observation history");
  assert.ok(result.records?.some((r) => r.kind === "ODDS_CHANGED"), "price move recorded");
  assert.ok(result.records?.some((r) => r.reasonCodes.includes("SUSPENDED")), "suspension reason recorded");
  assert.ok(result.records?.every((r) => r.mode === "synthetic-demo"), "fixture records cannot masquerade as live trial data");
});

// ---------------------------------------------------------------------------
// Helpers for region extraction
// ---------------------------------------------------------------------------

function extractKelceRegion(text: string): string {
  const idx = text.indexOf("Travis Kelce");
  if (idx === -1) return "";
  return text.slice(Math.max(0, idx - 80), idx + 700);
}

function kelceRegionIsAlertable(region: string): boolean {
  return region.includes("ALERTABLE");
}
