/**
 * PropStein Live Sniper — Remote API Model Provider (Phase 2+ production path).
 * Calls the protected FastAPI endpoints with the scoped session token and
 * fails closed on any entitlement or transport error. The Phase 1 demo
 * provider lives in @propstein/detection (createSyntheticDemoModelProvider).
 */

import type {
  MatchResult,
  ModelEvaluation,
  NormalizedMarket,
  RosterEntry,
} from "@propstein/core";
import { MarketMatcher } from "@propstein/core";

export interface RemoteProviderConfig {
  apiBaseUrl: string;
  /** Fetches the scoped session token (never a URL query parameter). */
  getSessionToken: () => Promise<string | null>;
  fetchImpl: typeof fetch;
}

export class RemoteApiModelProvider {
  readonly label = "DRIVE-REC-V1 · PROPSTEIN API";
  private rosterCache: RosterEntry[] = [];
  private rosterFetchedAt = 0;
  private readonly config: RemoteProviderConfig;
  private readonly matcherCache = new Map<string, MarketMatcher>();

  constructor(config: RemoteProviderConfig) {
    this.config = config;
  }

  roster(): RosterEntry[] {
    return this.rosterCache;
  }

  async refreshRoster(): Promise<{ ok: boolean; error?: string }> {
    const token = await this.config.getSessionToken();
    if (!token) return { ok: false, error: "no active session" };
    try {
      const res = await this.config.fetchImpl(`${this.config.apiBaseUrl}/api/v1/markets/model-coverage`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401 || res.status === 403) return { ok: false, error: "entitlement denied (fail closed)" };
      if (!res.ok) return { ok: false, error: `coverage endpoint returned ${res.status}` };
      const data = (await res.json()) as { roster?: RosterEntry[] };
      this.rosterCache = Array.isArray(data.roster) ? data.roster : [];
      this.rosterFetchedAt = Date.now();
      this.matcherCache.clear();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err) };
    }
  }

  private matcherFor(league: string): MarketMatcher {
    const cached = this.matcherCache.get(league);
    if (cached) return cached;
    const m = new MarketMatcher({
      roster: this.rosterCache.filter((r) => r.league === league),
      coverage: [], // Coverage verdicts come from evaluateRemote() against the API.
    });
    this.matcherCache.set(league, m);
    return m;
  }

  match(normalized: NormalizedMarket): MatchResult {
    // Identity resolution is local (fast); coverage verdicts come from the API.
    return this.matcherFor(normalized.observed.league.toUpperCase()).match(normalized);
  }

  async evaluateRemote(normalized: NormalizedMarket): Promise<ModelEvaluation | undefined> {
    const token = await this.config.getSessionToken();
    if (!token) return undefined; // Fail closed — no session, no model.
    try {
      const res = await this.config.fetchImpl(`${this.config.apiBaseUrl}/api/v1/markets/evaluate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          source: normalized.observed.source,
          eventId: normalized.observed.eventId,
          playerId: normalized.observed.playerId,
          playerName: normalized.observed.playerName,
          marketType: normalized.marketTypeCode,
          selection: normalized.selectionKey,
          americanOdds: normalized.americanOdds,
          line: normalized.observed.line,
          driveId: normalized.observed.driveId,
        }),
      });
      if (!res.ok) return undefined;
      const data = (await res.json()) as { model?: ModelEvaluation };
      return data.model;
    } catch {
      return undefined; // Fail closed on transport errors.
    }
  }

  get rosterAgeMs(): number {
    return this.rosterFetchedAt === 0 ? Number.POSITIVE_INFINITY : Date.now() - this.rosterFetchedAt;
  }
}
