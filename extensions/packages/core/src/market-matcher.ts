/**
 * PropStein Live Sniper — Market Matcher
 * =====================================
 * Matches normalized visible markets against the model coverage registry.
 *
 * Rules (spec §5/§6):
 *  - A playerId + eventId + marketType (+ line) triple is required for MATCHED.
 *  - Name-based fallback is only attempted within a resolved event; a name
 *    colliding across events (or an ambiguous display form) → UNVERIFIED.
 *  - Unknown players/markets → NO COVERAGE (displayed as NO MODEL COVERAGE).
 *  - UNVERIFIED markets NEVER produce value alerts.
 */

import type {
  MatchResult,
  ModelCoverageKey,
  NormalizedMarket,
  MarketTypeCode,
} from "./market-types.ts";
import { playerNameKey } from "./market-normalizer.ts";

/** Roster entry: a player identity bound to one event. */
export interface RosterEntry {
  playerId: string;
  playerName: string;
  team: string;              // canonical abbreviation
  eventId: string;
  league: string;
  /** Optional display names seen on books, matched via playerNameKey. */
  aliases?: string[];
}

export interface CoverageEntry {
  key: ModelCoverageKey;
  /** Present when the model can price this market. */
  available: boolean;
  /** Explanation when unavailable (shown to the user honestly). */
  unavailableReason?: string;
}

export interface MatcherDeps {
  roster: Iterable<RosterEntry>;
  coverage: Iterable<CoverageEntry>;
}

export class MarketMatcher {
  private readonly byPlayerId = new Map<string, RosterEntry[]>();
  private readonly byNameAndEvent = new Map<string, RosterEntry[]>();
  private readonly coverageKeys = new Set<string>();

  constructor(deps: MatcherDeps) {
    for (const entry of deps.roster) {
      this.byPlayerId.set(entry.playerId, [...(this.byPlayerId.get(entry.playerId) ?? []), entry]);
      const nameKey = playerNameKey(entry.playerName);
      for (const nk of new Set([nameKey, ...(entry.aliases ?? []).map((a) => playerNameKey(a))])) {
        if (!nk) continue;
        const mapKey = `${entry.league}|${entry.eventId}|${nk}`;
        this.byNameAndEvent.set(mapKey, [...(this.byNameAndEvent.get(mapKey) ?? []), entry]);
      }
    }
    for (const c of deps.coverage) {
      this.coverageKeys.add(coverageKeyString(c.key));
    }
  }

  /**
   * Match a normalized market. Fail-closed at every step.
   */
  match(market: NormalizedMarket): MatchResult {
    const league = market.observed.league.toUpperCase();
    const eventId = market.observed.eventId?.trim();
    const reasons: string[] = [...market.ambiguityReasons];

    // ---- 1. Resolve the player identity --------------------------------
    let resolved: RosterEntry | undefined;
    let playerId: string | undefined;

    if (market.observed.playerId) {
      const candidates = this.byPlayerId.get(market.observed.playerId) ?? [];
      const inEvent = eventId ? candidates.filter((c) => c.eventId === eventId) : candidates;
      if (inEvent.length === 1) {
        resolved = inEvent[0]!;
        playerId = resolved.playerId;
      } else if (candidates.length > 1 && !eventId) {
        reasons.push(`playerId ${market.observed.playerId} appears in multiple events and no eventId was observed`);
      } else if (candidates.length === 0) {
        reasons.push(`playerId ${market.observed.playerId} not present in the live roster registry`);
      }
    }

    if (!resolved && market.playerNameKey) {
      // Name-based fallback ONLY inside a resolved event.
      if (!eventId) {
        reasons.push("name-only match attempted without an event binding — rejected (name alone never identifies an event)");
      } else {
        const candidates = this.byNameAndEvent.get(`${league}|${eventId}|${market.playerNameKey}`) ?? [];
        if (candidates.length === 1) {
          resolved = candidates[0]!;
          playerId = resolved.playerId;
        } else if (candidates.length > 1) {
          reasons.push(`player name key "${market.playerNameKey}" matches multiple roster entries in event ${eventId}`);
        } else {
          reasons.push(`player name key "${market.playerNameKey}" not found in event ${eventId} roster`);
        }
      }
    }

    if (!resolved) {
      // Cross-event collision check: same name active in >1 event → UNVERIFIED.
      let crossEventHits = 0;
      for (const [mapKey, entries] of this.byNameAndEvent) {
        if (mapKey.endsWith(`|${market.playerNameKey}`) && entries.length > 0) {
          crossEventHits += 1;
          if (crossEventHits > 1) break;
        }
      }
      if (crossEventHits > 1) {
        reasons.push(`player name key "${market.playerNameKey}" is active in multiple simultaneous events — refusing to guess`);
        return { status: "UNVERIFIED", reasons };
      }
      if (reasons.length === 0) reasons.push("player could not be resolved");
      return { status: "UNVERIFIED", reasons };
    }

    // ---- 2. Bind the event ---------------------------------------------
    if (!eventId) {
      reasons.push("no event binding on the observation");
      return { status: "UNVERIFIED", reasons };
    }

    // ---- 3. Build the coverage key -------------------------------------
    const key: ModelCoverageKey = {
      league,
      eventId,
      playerId: playerId!,
      marketType: market.marketTypeCode as MarketTypeCode,
      ...(market.observed.line !== undefined ? { line: market.observed.line } : {}),
    };

    if (market.marketTypeCode === "unknown") {
      return {
        status: "UNVERIFIED",
        key,
        reasons: ["market label could not be classified into a canonical market type"],
      };
    }

    // ---- 4. Coverage lookup --------------------------------------------
    if (!this.coverageKeys.has(coverageKeyString(key))) {
      return {
        status: "NO_COVERAGE",
        key,
        reasons: [
          `no model coverage for ${league} ${market.marketTypeCode} (player ${playerId}, event ${eventId}) — displays as NO MODEL COVERAGE`,
        ],
      };
    }

    return { status: "MATCHED", key, reasons };
  }
}

export function coverageKeyString(key: ModelCoverageKey): string {
  const line = key.line !== undefined ? `|${key.line}` : "";
  return `${key.league}|${key.eventId}|${key.playerId}|${key.marketType}${line}`;
}

export function signalKeyFor(
  source: string,
  eventId: string | undefined,
  playerId: string,
  marketType: string,
  selection: string,
  line?: number,
): string {
  return [
    source,
    eventId ?? "no-event",
    playerId,
    marketType,
    selection,
    line !== undefined ? String(line) : "",
  ].join("|");
}
