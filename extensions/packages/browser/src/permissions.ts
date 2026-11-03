/**
 * PropStein Live Sniper — Per-Site Permissions
 * ==========================================
 * Site-level access management (spec §3, §12):
 *  - No broad wildcard host access.
 *  - Each supported site origin is a distinct, revocable user grant.
 *  - Injection into a tab happens ONLY when the user has granted that
 *    origin AND monitoring is active AND an adapter supports the page.
 *
 * The manifest declares these as optional_host_permissions so nothing is
 * granted at install time — the user grants per site through the panel.
 */

/** Explicit supported-site origins (matched against the manifest's optional set). */
export const SUPPORTED_SITE_ORIGINS: ReadonlyArray<{ origin: string; platform: string; label: string }> = [
  { origin: "http://localhost:4173", platform: "demobook", label: "DemoBook (synthetic fixture)" },
  { origin: "http://127.0.0.1:4173", platform: "demobook", label: "DemoBook (synthetic fixture)" },
  { origin: "https://sportsbook.draftkings.com", platform: "draftkings", label: "DraftKings (requires authorization)" },
  { origin: "https://sportsbook.fanduel.com", platform: "fanduel", label: "FanDuel (requires authorization)" },
  { origin: "https://polymarket.com", platform: "polymarket", label: "Polymarket" },
];

export function originFor(url: string): string | undefined {
  try {
    return new URL(url).origin;
  } catch {
    return undefined;
  }
}

export function isSupportedOrigin(origin: string | undefined): boolean {
  return SUPPORTED_SITE_ORIGINS.some((s) => s.origin === origin);
}

export function platformForOrigin(origin: string | undefined): string | undefined {
  return SUPPORTED_SITE_ORIGINS.find((s) => s.origin === origin)?.platform;
}

/** Browser-adapter boundary so the permission logic is unit-testable. */
export interface PermissionsApi {
  contains(origins: string[]): Promise<boolean>;
  request(origins: string[]): Promise<boolean>;
  remove(origins: string[]): Promise<boolean>;
}

/**
 * Ensure the per-site grant exists. `request` requires a user gesture in
 * Chrome; callers must invoke it from a panel click handler.
 */
export async function ensureSitePermission(
  api: PermissionsApi,
  origin: string,
): Promise<{ granted: boolean; reason: string }> {
  if (!isSupportedOrigin(origin)) {
    return { granted: false, reason: `${origin ?? "(unknown)"} is not a supported site` };
  }
  try {
    if (await api.contains([`${origin}/*`])) {
      return { granted: true, reason: "already granted" };
    }
    const granted = await api.request([`${origin}/*`]);
    return granted
      ? { granted: true, reason: "granted by user" }
      : { granted: false, reason: "the user declined the site permission prompt" };
  } catch (err) {
    return { granted: false, reason: `permission API error: ${String(err)}` };
  }
}

/** Revoke a site grant (user control per spec §12). */
export async function revokeSitePermission(api: PermissionsApi, origin: string): Promise<boolean> {
  try {
    await api.remove([`${origin}/*`]);
    return true;
  } catch {
    return false;
  }
}
