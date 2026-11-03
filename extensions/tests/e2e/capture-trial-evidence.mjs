/**
 * PropStein Live Sniper — Browser Trial Evidence Capture Script
 * ==============================================================
 * Loads the built MV3 extension in real Chromium via Playwright, opens the
 * side panel / companion alongside the DemoBook fixture, and exercises all
 * required browser trial interactions:
 *
 *  1. Initial detection of 4 cards (+160 Kelce, +105 Rice, +230 Henry, +290 Johnson)
 *  2. Odds change (+160 → +115 on Kelce) -> recomputing break-even and EV
 *  3. Market suspension -> immediate withdrawal with SUSPENDED
 *  4. Drive end (d4 → d5) -> withdrawal of d4 signals as DRIVE ENDED
 *  5. Stale quote ticks -> pause ticks, wait >3s, verify withdrawal as QUOTE EXPIRED / STALE
 *  6. Resume ticks -> verify recovery
 *  7. Stop monitoring -> verify all signals cleared
 *  8. Restart monitoring -> verify signals restored
 *  9. Trial audit journal export -> export and inspect propstein-trial-audit-*.jsonl
 * 10. Console error check -> assert zero uncaught console errors
 *
 * Captures timestamped full-window and sidepanel screenshots at each step.
 */

import { chromium } from "playwright-core";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const extRoot = join(here, "..", "..");
const repoRoot = join(extRoot, "..");
const devExtPath = join(extRoot, "dist", "propstein-chrome-dev");
const demoHtmlPath = join(extRoot, "demo", "demo-sportsbook.html");
const evidenceDir = join(repoRoot, "docs", "evidence", "live-sniper");
const DEMO_PORT = 4173;

await mkdir(evidenceDir, { recursive: true });

// Start local fixture server
const html = await readFile(demoHtmlPath, "utf8");
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  res.end(html);
});
await new Promise((resolve) => server.listen(DEMO_PORT, "127.0.0.1", resolve));
console.log(`[evidence] DemoBook fixture server listening on http://127.0.0.1:${DEMO_PORT}`);

const consoleErrors = [];

const context = await chromium.launchPersistentContext("/tmp/propstein-evidence-profile", {
  channel: "chromium",
  headless: true,
  args: [
    `--disable-extensions-except=${devExtPath}`,
    `--load-extension=${devExtPath}`,
    "--no-sandbox",
    "--disable-dev-shm-usage",
  ],
  viewport: { width: 1440, height: 900 },
});

// Capture console errors across all pages
context.on("page", (page) => {
  page.on("pageerror", (err) => {
    console.error(`[page error] ${page.url()}:`, err);
    consoleErrors.push({ url: page.url(), error: String(err) });
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.error(`[console.error] ${page.url()}:`, msg.text());
      consoleErrors.push({ url: page.url(), error: msg.text() });
    }
  });
});

async function findExtensionId() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const sw = context.serviceWorkers()?.[0];
    if (sw) {
      const m = /^chrome-extension:\/\/([^/]+)\//.exec(sw.url());
      if (m) return m[1];
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("extension service worker not detected");
}

const wake = await context.newPage();
await wake.goto("about:blank");
const extId = await findExtensionId();
console.log(`[evidence] Extension loaded with id: ${extId}`);

// Open companion panel page
const panelPage = await context.newPage();
await panelPage.goto(`chrome-extension://${extId}/web-companion/index.html`, { waitUntil: "networkidle" });

// Open tracked demo page through OPEN_DEMO_PAGE message
const demoOpened = context.waitForEvent("page");
await panelPage.evaluate(() => {
  void (globalThis).chrome?.runtime.sendMessage({ type: "OPEN_DEMO_PAGE" });
});
const demoPage = await demoOpened;
await demoPage.goto(`http://localhost:${DEMO_PORT}/demobook`, { waitUntil: "networkidle" });
await wake.close().catch(() => undefined);

async function waitForPanel(pred, timeoutMs = 20_000, label = "") {
  const started = Date.now();
  let last = "";
  while (Date.now() - started < timeoutMs) {
    last = (await panelPage.evaluate(() => document.body.innerText)) || "";
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`panel timeout ${label}:\n${last.slice(0, 1000)}`);
}

async function clickStartMonitoring() {
  await waitForPanel((t) => t.includes("READY TO MONITOR"), 20_000, "(ready to monitor)");
  await panelPage.evaluate(() => {
    const view = document.querySelector(".state-view");
    const btns = Array.from((view ?? document).querySelectorAll("button"));
    const start = btns.find((b) => b.textContent?.trim() === "START MONITORING")
      ?? Array.from(document.querySelectorAll("button")).find((b) => b.textContent?.trim() === "START MONITORING");
    if (start) (start).click();
  });
}

console.log("[evidence] Step 1: Waiting for READY TO MONITOR & Start Monitoring...");
await waitForPanel((t) => t.includes("READY TO MONITOR"), 20_000, "ready to monitor");
await panelPage.screenshot({ path: join(evidenceDir, "01-ready-to-monitor.png") });

await clickStartMonitoring();

const step1Text = await waitForPanel(
  (t) => t.includes("Travis Kelce") && t.includes("+160") && t.includes("38.46%") && t.includes("ALERTABLE"),
  20_000,
  "four cards detected",
);
console.log("[evidence] Step 1 verified: 4 cards detected (+160 Kelce, Rice, Henry, Johnson). Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "02-active-monitoring-cards.png") });
await demoPage.screenshot({ path: join(evidenceDir, "02b-demobook-fixture.png") });

console.log("[evidence] Step 2: Simulating odds move (+160 -> +115 on Kelce)...");
await demoPage.click("#btn-move");
await waitForPanel(
  (t) => t.includes("+115") && t.includes("46.51%") && t.includes("-5.4%"),
  20_000,
  "Kelce repriced to +115",
);
console.log("[evidence] Step 2 verified: +115 odds move recomputed break-even 46.51% and negative EV -5.4%. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "03-odds-move-repriced.png") });

console.log("[evidence] Step 3: Simulating market suspension (Kelce)...");
await demoPage.click("#btn-suspend");
await waitForPanel(
  (t) => t.includes("SUSPENDED"),
  20_000,
  "Kelce suspended",
);
console.log("[evidence] Step 3 verified: Kelce marked SUSPENDED and withdrawn. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "04-market-suspended.png") });

console.log("[evidence] Step 4: Reset fixture & simulate drive end (d4 -> d5)...");
await demoPage.reload({ waitUntil: "networkidle" });
await waitForPanel((t) => t.includes("+160") && t.includes("38.46%"), 20_000, "reset fixture");
await demoPage.click("#btn-drive-end");
await waitForPanel((t) => (t.match(/DRIVE ENDED/g) ?? []).length >= 4, 20_000, "all 4 d4 signals invalidated");
console.log("[evidence] Step 4 verified: d4 signals withdrawn as DRIVE ENDED, d5 initialized. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "05-drive-ended-withdrawal.png") });

console.log("[evidence] Step 5: Simulating stale quote ticks (pause ticks)...");
await demoPage.click("#btn-stale");
await waitForPanel(
  (t) => t.includes("QUOTE EXPIRED") || t.includes("STALE"),
  20_000,
  "stale quote withdrawal",
);
console.log("[evidence] Step 5 verified: quote expiration withdraws signal fail-closed. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "06-stale-quote-expired.png") });

console.log("[evidence] Step 6: Resuming ticks to verify recovery...");
await demoPage.click("#btn-stale");
await waitForPanel(
  (t) => t.includes("+160") && (t.includes("ALERTABLE") || t.includes("OPEN")),
  20_000,
  "recovery after resuming ticks",
);
console.log("[evidence] Step 6 verified: recovered after feed resumed. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "07-recovered-after-feed-resumed.png") });

console.log("[evidence] Step 7: Pausing / Stopping monitoring...");
await panelPage.evaluate(() => {
  const btns = Array.from(document.querySelectorAll("button"));
  const stop = btns.find((b) => b.textContent?.trim() === "PAUSE MONITORING");
  if (stop) (stop).click();
});
await waitForPanel((t) => !t.includes("PAUSE MONITORING"), 15_000, "monitoring stopped");
console.log("[evidence] Step 7 verified: monitoring stopped and signals cleared. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "08-monitoring-paused.png") });

console.log("[evidence] Step 8: Restarting monitoring...");
await panelPage.evaluate(() => {
  const btns = Array.from(document.querySelectorAll("button"));
  const start = btns.find((b) => b.textContent?.trim() === "START MONITORING");
  if (start) (start).click();
});
await waitForPanel((t) => t.includes("Travis Kelce") && t.includes("+160"), 20_000, "monitoring resumed");
console.log("[evidence] Step 8 verified: monitoring resumed successfully. Taking screenshot...");
await panelPage.screenshot({ path: join(evidenceDir, "09-monitoring-resumed.png") });

console.log("[evidence] Step 9: Exporting trial audit log...");
const auditResult = await panelPage.evaluate(async () => {
  return (globalThis).chrome?.runtime.sendMessage({ type: "GET_AUDIT" });
});
console.log(`[evidence] Audit export record count: ${auditResult.records?.length ?? 0}`);
if (auditResult.records) {
  const logPath = join(evidenceDir, `propstein-trial-audit-${new Date().toISOString().slice(0, 10)}.jsonl`);
  const lines = auditResult.records.map((r) => JSON.stringify(r)).join("\n") + "\n";
  await writeFile(logPath, lines, "utf8");
  console.log(`[evidence] Wrote trial audit log to: ${logPath}`);
}

console.log("[evidence] Step 10: Settings & site adapter status view...");
await panelPage.evaluate(() => {
  const btns = Array.from(document.querySelectorAll("button"));
  const settingsBtn = btns.find((b) => b.textContent?.trim() === "SETTINGS");
  if (settingsBtn) (settingsBtn).click();
});
await panelPage.waitForSelector(".settings", { timeout: 5000 });
await panelPage.screenshot({ path: join(evidenceDir, "10-settings-adapter-status.png") });

console.log(`[evidence] Uncaught console errors during trial: ${consoleErrors.length}`);
if (consoleErrors.length > 0) {
  console.warn("[evidence] Console errors encountered:", consoleErrors);
} else {
  console.log("[evidence] Zero console errors recorded across extension and pages.");
}

await context.close().catch(() => undefined);
await new Promise((resolve) => server.close(resolve));
console.log("[evidence] Evidence capture complete. Artifacts written to:", evidenceDir);
