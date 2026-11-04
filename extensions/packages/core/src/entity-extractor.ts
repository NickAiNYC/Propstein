/**
 * PropStein Live Sniper — Fuzzy Entity Resolution
 * ===============================================
 * Resolves sportsbook DOM extractions to backend active signals via:
 *   (player_last_name + market_scope + line_bucket)
 *
 * Fail-closed:
 * If there is no clear match within tolerance or if names collide,
 * returns null. A false match is worse than no match.
 */

import type { BackendLiveSignal, ExtractedMarketNode, NormalizedEntityKey } from "./sniper-protocol.ts";
import { playerNameKey } from "./market-normalizer.ts";

const SUFFIXES = new Set(["JR", "SR", "II", "III", "IV", "V"]);

/**
 * Extracts normalized last name from arbitrary player name strings.
 * e.g. "Tyrese Maxey" -> "maxey", "Patrick Mahomes II" -> "mahomes"
 */
export function extractLastName(rawName: string): string {
  const clean = playerNameKey(rawName).trim();
  if (!clean) return "";

  const tokens = clean.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return "";

  let lastIdx = tokens.length - 1;
  while (lastIdx > 0) {
    const tok = tokens[lastIdx];
    if (tok && SUFFIXES.has(tok)) {
      lastIdx--;
    } else {
      break;
    }
  }
  const result = tokens[lastIdx];
  return result ? result.toLowerCase() : "";
}

/**
 * Maps raw market title/label into canonical market scope token.
 */
export function normalizeMarketScope(rawMarket: string): string {
  const norm = rawMarket.toLowerCase().replace(/[^a-z0-9]/g, " ").trim();

  if (/\b(points|pts)\b/.test(norm)) return "pts";
  if (/\b(receiving\s*yards?|rec\s*yds?)\b/.test(norm)) return "rec_yds";
  if (/\b(receptions?|catches|recs?)\b/.test(norm)) return "receptions";
  if (/\b(assists?|asts?)\b/.test(norm)) return "ast";
  if (/\b(rebounds?|rebs?)\b/.test(norm)) return "reb";
  if (/\b(rushing\s*yards?|rush\s*yds?)\b/.test(norm)) return "rush_yds";
  if (/\b(threes?|3\s*pt|three\s*pointers?)\b/.test(norm)) return "threes";

  return norm.replace(/\s+/g, "_");
}

/**
 * Builds the canonical normalized entity key for fast table lookups.
 */
export function buildNormalizedEntityKey(
  playerName: string,
  rawMarket: string,
  line: number
): NormalizedEntityKey {
  const lastName = extractLastName(playerName);
  const marketScope = normalizeMarketScope(rawMarket);
  const lineBucket = Math.floor(line);
  const canonicalKey = `${lastName}:${marketScope}:${lineBucket}`;

  return {
    lastName,
    marketScope,
    lineBucket,
    canonicalKey,
  };
}

/**
 * Matches an extracted DOM market node against active backend signals.
 * Max line tolerance defaults to 1.5 units.
 */
export function matchExtractedNodeToSignal(
  node: ExtractedMarketNode,
  signals: Iterable<BackendLiveSignal>,
  lineTolerance: number = 1.5
): BackendLiveSignal | null {
  if (!node.rawPlayer || node.line === null || Number.isNaN(node.line)) {
    return null;
  }

  const extractedLastName = extractLastName(node.rawPlayer);
  if (!extractedLastName) return null;

  const extractedScope = normalizeMarketScope(node.rawMarket);
  const extractedLine = node.line;

  const matches: Array<{ signal: BackendLiveSignal; diff: number }> = [];

  for (const sig of signals) {
    const sigLastName = extractLastName(sig.playerName);
    if (sigLastName !== extractedLastName) continue;

    const sigScope = normalizeMarketScope(sig.marketType);
    if (sigScope !== extractedScope && !sigScope.includes(extractedScope) && !extractedScope.includes(sigScope)) {
      continue;
    }

    if (node.selection && sig.selection && node.selection !== sig.selection) {
      continue;
    }

    const diff = Math.abs(sig.line - extractedLine);
    if (diff <= lineTolerance) {
      matches.push({ signal: sig, diff });
    }
  }

  if (matches.length === 0) {
    return null;
  }

  // If multiple distinct players matched (e.g. ambiguous last name in different games), fail closed!
  const distinctPlayers = new Set(matches.map((m) => m.signal.playerId));
  if (distinctPlayers.size > 1) {
    return null;
  }

  // Sort by smallest line difference
  matches.sort((a, b) => a.diff - b.diff);
  return matches[0]?.signal ?? null;
}
