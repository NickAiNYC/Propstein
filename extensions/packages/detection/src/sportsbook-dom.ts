/**
 * PropStein Live Sniper — Sportsbook DOM Extraction
 * =================================================
 * Extracts visible market cards from arbitrary sportsbook page DOMs:
 * DraftKings, FanDuel, BetMGM, Polymarket, and DemoBook fixtures.
 *
 * Scans visible text and attributes without depending on brittle class names.
 */

import { parseAmericanOddsText } from "@propstein/core";
import type { ExtractedMarketNode } from "@propstein/core";

export function detectBookFromHost(hostname: string): string {
  const host = hostname.toLowerCase();
  if (host.includes("draftkings")) return "draftkings";
  if (host.includes("fanduel")) return "fanduel";
  if (host.includes("betmgm")) return "betmgm";
  if (host.includes("polymarket")) return "polymarket";
  if (host.includes("localhost") || host.includes("127.0.0.1") || host.includes("demobook")) {
    return "demobook";
  }
  return "unknown_book";
}

/**
 * Extracts market entity information from a market row / card element.
 */
export function extractMarketNodeFromElement(
  el: Element,
  bookName: string = "unknown_book",
  contextMarket: string = ""
): ExtractedMarketNode | null {
  // 1. Player Name
  const playerEl =
    el.querySelector('[data-testid*="player"], [class*="player-name"], [class*="playerName"], .player-name, h3, h4');
  const rawPlayer = playerEl?.textContent?.trim() || "";
  if (!rawPlayer) return null;

  // 2. Market Name
  const marketEl =
    el.querySelector('[data-testid*="market"], [class*="market-type"], [class*="marketTitle"], .market-title');
  const rawMarket = marketEl?.textContent?.trim() || contextMarket || "Points";

  // 3. Line value
  const lineEl = el.querySelector('[data-testid*="line"], [class*="prop-line"], [class*="line"], [class*="handicap"]');
  let line: number | null = null;
  if (lineEl?.textContent) {
    const parsed = parseFloat(lineEl.textContent.replace(/[^0-9.]/g, ""));
    if (!Number.isNaN(parsed)) line = parsed;
  }

  // 4. Odds / Price
  const priceEl =
    el.querySelector('button[data-testid*="outcome-button"], [data-testid*="price"], [data-testid*="odds"], button, [class*="odds"]');
  let price: number | null = null;
  if (priceEl?.textContent) {
    const parsed = parseAmericanOddsText(priceEl.textContent);
    price = parsed !== undefined ? parsed : null;
  }

  // 5. Selection Over / Under
  let selection: "OVER" | "UNDER" | undefined;
  const fullText = el.textContent?.toUpperCase() || "";
  if (/\bOVER\b|\bO\s*\d/.test(fullText)) selection = "OVER";
  else if (/\bUNDER\b|\bU\s*\d/.test(fullText)) selection = "UNDER";

  return {
    rawPlayer,
    rawMarket,
    line,
    price,
    selection,
    book: bookName,
    element: el,
  };
}
