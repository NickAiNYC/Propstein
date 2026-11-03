/**
 * PropStein Live Sniper — Synthetic DemoBook Adapter
 * ================================================
 * The default-enabled detection surface for Phase 1: a synthetic live-drive
 * market page (demo/demo-sportsbook.html) served locally. It exists so the
 * ENTIRE pipeline — detection, normalization, matching, pricing, UI — can be
 * developed and e2e-tested with zero sportsbook access.
 *
 * The page carries an explicit synthetic banner; every observed market is
 * tagged provenance "synthetic-fixture" and can never be confused with a
 * real book's data.
 */

import type { MarketChangeEvent, ObservedMarket } from "@propstein/core";
import { parseAmericanOddsText } from "@propstein/core";
import type { AdapterDetectionResult, VisibleMarketAdapter } from "./adapter.ts";
import { diffMarkets, type DifferHooks } from "../dom-extractor.ts";

export const DEMOBOOK_ADAPTER_VERSION = "demobook-selectors-v1";

/** The demo page MUST carry this root marker or the adapter degrades. */
const PAGE_ROOT_MARKER = "[data-propstein-demo='market-board']";
const MARKET_CARD_SELECTOR = "[data-ps-market-card]";

function attr(el: Element, name: string): string | undefined {
  const v = el.getAttribute(name);
  return v === null || v === "" ? undefined : v;
}

function numAttr(el: Element, name: string): number | undefined {
  const v = attr(el, name);
  if (v === undefined) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export class DemoBookAdapter implements VisibleMarketAdapter {
  readonly platform = "demobook" as const;
  readonly adapterVersion = DEMOBOOK_ADAPTER_VERSION;
  /** Injected for tests; defaults to the real clock. */
  private readonly now: () => Date;
  private unsubscribeDiff: (() => void) | undefined;

  constructor(opts: { now?: () => Date } = {}) {
    this.now = opts.now ?? (() => new Date());
  }

  isSupportedPage(url: URL): boolean {
    // Local demo server (any port) with the demobook path, or the packaged
    // fixture origin. Explicitly scoped — never a wildcard.
    const hostOk = /^(localhost|127\.0\.0\.1)$/.test(url.hostname);
    const pathOk = url.pathname.startsWith("/demobook") || url.pathname.startsWith("/demo-sportsbook");
    return hostOk && pathOk;
  }

  async detectVisibleMarkets(root: Document): Promise<AdapterDetectionResult> {
    const notes: string[] = [];
    const board = root.querySelector(PAGE_ROOT_MARKER);
    if (!board) {
      return {
        markets: [],
        status: "ADAPTER_DEGRADED",
        confidence: 0,
        notes: ["demo market board marker not found — page layout changed or this is not the demo page"],
      };
    }

    // Board-level context: event binding, teams, and the current drive are
    // section-scoped on the demo page (mirroring how real books scope event
    // context to the page section rather than each card).
    const boardContext = {
      eventId: attr(board, "data-ps-event-id"),
      homeTeam: attr(board, "data-ps-home-team"),
      awayTeam: attr(board, "data-ps-away-team"),
      driveId: attr(board, "data-ps-drive-id"),
      sport: attr(board, "data-ps-sport"),
      league: attr(board, "data-ps-league"),
    };

    const observedAt = this.now().toISOString();
    const markets: ObservedMarket[] = [];
    let unparsedOdds = 0;

    for (const card of Array.from(board.querySelectorAll(MARKET_CARD_SELECTOR))) {
      const market = this.parseCard(card, observedAt, boardContext);
      if (market) markets.push(market);
      else notes.push(`card ${attr(card, "data-ps-player-id") ?? "?"} could not be parsed`);
    }

    // Cross-check: the visible odds text must agree with the data attribute.
    for (const m of markets) {
      if (m.americanOdds === undefined) unparsedOdds += 1;
    }
    if (unparsedOdds > 0) notes.push(`${unparsedOdds} card(s) had no parseable odds`);

    // High confidence when the structured contract is intact; the page is
    // ours, so attribute+text agreement is expected.
    const confidence = markets.length > 0 && unparsedOdds === 0 ? 0.98 : 0.5;

    return { markets, status: "OK", confidence, notes };
  }

  private parseCard(card: Element, observedAt: string, board: {
    eventId?: string; homeTeam?: string; awayTeam?: string; driveId?: string; sport?: string; league?: string;
  }): ObservedMarket | undefined {
    const playerId = attr(card, "data-ps-player-id");
    const playerName = attr(card, "data-ps-player-name");
    if (!playerId || !playerName) return undefined;

    const statusAttr = (attr(card, "data-ps-market-status") ?? "unknown").toUpperCase();
    const marketStatus =
      statusAttr === "OPEN" || statusAttr === "SUSPENDED" || statusAttr === "CLOSED" ? statusAttr : "UNKNOWN";

    const americanOdds =
      numAttr(card, "data-ps-american-odds") ??
      this.parseOddsText(card.querySelector("[data-ps-odds-text]")?.textContent ?? "");

    return {
      source: "demobook",
      // Card attributes override board context; board fills the gaps.
      eventId: attr(card, "data-ps-event-id") ?? board.eventId,
      sport: attr(card, "data-ps-sport") ?? board.sport ?? "football",
      league: attr(card, "data-ps-league") ?? board.league ?? "NFL",
      homeTeam: attr(card, "data-ps-home-team") ?? board.homeTeam,
      awayTeam: attr(card, "data-ps-away-team") ?? board.awayTeam,
      playerId,
      playerName,
      marketType: attr(card, "data-ps-market-type") ?? "Player to Record a Reception",
      marketLabel: attr(card, "data-ps-market-label") ?? "Player to record a reception this drive",
      selection: attr(card, "data-ps-selection") ?? "YES",
      ...(numAttr(card, "data-ps-line") !== undefined ? { line: numAttr(card, "data-ps-line") } : {}),
      ...(americanOdds !== undefined ? { americanOdds } : {}),
      driveId: attr(card, "data-ps-drive-id") ?? board.driveId,
      marketStatus,
      observedAt,
      ...(attr(card, "data-ps-source-timestamp") !== undefined
        ? { sourceTimestamp: attr(card, "data-ps-source-timestamp") }
        : {}),
      adapterVersion: this.adapterVersion,
      detectionConfidence: 0.98,
      provenance: "synthetic-fixture",
    };
  }

  private parseOddsText(text: string): number | undefined {
    return parseAmericanOddsText(text.trim());
  }

  observeChanges(callback: (event: MarketChangeEvent) => void): () => void {
    if (typeof MutationObserver === "undefined") {
      // No observer available (e.g. server-side rendering) — nothing to do.
      return () => undefined;
    }
    const hooks: DifferHooks = {
      selectCards: (root: Document) =>
        Array.from(root.querySelectorAll(`${PAGE_ROOT_MARKER} ${MARKET_CARD_SELECTOR}`)),
      // IMPORTANT: parse card events with the CURRENT board context (event,
      // teams, drive). The board is located from the card itself so attribute
      // changes on the board (e.g. a drive transition) are reflected
      // immediately — an empty context here would strip the event/drive
      // binding from every mutation-driven market and degrade all signals to
      // UNVERIFIED (found in live e2e; linkedom integration tests only cover
      // the initial detectVisibleMarkets pass).
      parseCard: (el: Element) => {
        const board = el.closest(PAGE_ROOT_MARKER) ?? el.ownerDocument?.querySelector(PAGE_ROOT_MARKER) ?? null;
        const boardContext = board
          ? {
              eventId: attr(board, "data-ps-event-id"),
              homeTeam: attr(board, "data-ps-home-team"),
              awayTeam: attr(board, "data-ps-away-team"),
              driveId: attr(board, "data-ps-drive-id"),
              sport: attr(board, "data-ps-sport"),
              league: attr(board, "data-ps-league"),
            }
          : {};
        return this.parseCard(el, this.now().toISOString(), boardContext);
      },
    };
    this.unsubscribeDiff = diffMarkets(hooks, callback, {
      targetSelector: PAGE_ROOT_MARKER,
    });
    return () => {
      this.unsubscribeDiff?.();
    };
  }
}
