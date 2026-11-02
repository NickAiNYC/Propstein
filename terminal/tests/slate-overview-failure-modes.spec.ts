// tests/slate-overview-failure-modes.spec.ts
import { test, expect } from "@playwright/test";

test("CONFLICT state blocks action with persistent banner", async ({ page }) => {
  await page.goto("/slate?__mock=conflict");
  // Next injects its own role="alert" route announcer — filter to OUR banner.
  const banner = page.getByRole("alert").filter({ hasText: /FEED CONFLICT/ });
  await expect(banner).toHaveCount(1);
  await expect(banner).toContainText(/action locked/i);
  // Card must be BLOCKED, not QUALIFIED
  await expect(page.getByText(/^BLOCKED$/)).toBeVisible();
});

test("mixed VERIFIED and OBSERVED sources render distinct badges", async ({ page }) => {
  await page.goto("/slate?__mock=mixed_verification");
  const verified = page.getByLabel(/Quote verified by hash audit/i).first();
  const observed = page.getByLabel(/Quote observed but not verified/i).first();
  await expect(verified).toBeVisible();
  await expect(observed).toBeVisible();
  // aria-labels must be distinct — never just "unverified"
  const vLabel = await verified.getAttribute("aria-label");
  const oLabel = await observed.getAttribute("aria-label");
  expect(vLabel).not.toEqual(oLabel);
});

test("edge-positive but OBSERVED play renders BLOCKED, not QUALIFIED", async ({ page }) => {
  await page.goto("/slate?__mock=edge_positive_observed");
  // Even with a +12% edge, the card must show BLOCKED
  await expect(page.getByText(/^BLOCKED$/)).toBeVisible();
  await expect(page.getByText(/Quote not verified/i)).toBeVisible();
  await expect(page.getByText(/watch only/i)).toHaveCount(0);
});

test("hard gate clause failure flips card to BLOCKED_GATE with clause named", async ({ page }) => {
  await page.goto("/slate?__mock=hard_gate_fail");
  await expect(page.getByText(/^BLOCKED$/)).toBeVisible();
  await expect(page.getByText(/Gate failed:/i)).toBeVisible();
  // The specific failing clause must be named in the subtitle
  await expect(page.getByText(/Gate failed:.*edge/i)).toBeVisible();
});

test("soft clause failure renders WATCH, not BLOCKED", async ({ page }) => {
  await page.goto("/slate?__mock=soft_gate_fail");
  await expect(page.getByText(/watch only/i)).toBeVisible();
  await expect(page.getByText(/^BLOCKED$/)).toHaveCount(0);
});

test("primary vs secondary feed hierarchy", async ({ page }) => {
  await page.goto("/slate");
  await expect(page.getByRole("columnheader", { name: /primary source/i })).toBeVisible();
  await expect(page.getByText(/secondary source/i)).toBeVisible();
  await expect(page.getByText(/not used for action/i)).toBeVisible();
});
