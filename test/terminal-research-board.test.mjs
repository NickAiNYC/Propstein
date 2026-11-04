// FIXTURES live only in this test. The research board module has no sample rows.
import assert from "node:assert/strict";
import test from "node:test";

import {
  assembleResearchBoard,
  formatGateCount,
  loadResearchBoard,
  modelSd,
  renderResearchBoardText,
  UNAVAILABLE,
} from "../terminal/lib/data/research-board.ts";

const NOW = new Date("2026-11-04T12:00:00Z");

function fixtureSignal(overrides = {}) {
  return {
    eventId: "2026_10_AAA_BBB",
    eventStartAt: "2026-11-08T18:00:00+00:00",
    providerEventId: "FIXTURE-PROVIDER-EVENT",
    amendmentId: "AMEND-001",
    gameId: "2026_10_AAA_BBB",
    playerId: "fixture-player",
    market: "receptions",
    modelVersion: null,
    capturedAt: "2026-11-04T11:00:00+00:00",
    payload: {},
    ...overrides,
  };
}

test("missing sources render unavailable and omit model probability", () => {
  const board = assembleResearchBoard({
    now: NOW,
    gateCount: 0,
    signals: [fixtureSignal()],
    snapshots: [
      {
        snapshot_id: "other",
        content_hash: "other",
        created_at: "2026-11-04T10:00:00+00:00",
        projection: { fair_line: 99, proj_volume: 99, p_over: 0.4242 },
        model: { version: "should-not-join" },
      },
    ],
  });
  const text = renderResearchBoardText(board);
  assert.equal(board.gateLabel, "0 / 600");
  assert.equal(board.cards.length, 1);
  assert.equal(board.cards[0].fairLine, UNAVAILABLE);
  assert.equal(board.cards[0].projectedVolume, UNAVAILABLE);
  assert.equal(board.cards[0].modelVersion, UNAVAILABLE);
  assert.equal(board.cards[0].quotes[0].line, UNAVAILABLE);
  assert.equal(board.cards[0].quotes[0].capturedAt, UNAVAILABLE);
  assert.equal(board.cards[0].quotes[0].verification, UNAVAILABLE);
  assert.equal(board.cards[0].quotes[0].staleness, UNAVAILABLE);
  assert.equal(board.cards[0].snapshotClock, UNAVAILABLE);
  assert.equal(board.divergence[0].divergence, UNAVAILABLE);
  assert.equal(board.modelVersion, UNAVAILABLE);
  assert.equal(text.includes("0.4242"), false);
  assert.equal(text.includes("should-not-join"), false);
  assert.equal(text.includes("FIXTURE-PROVIDER-EVENT"), false);
  assert.equal(text.includes("99"), false);
  assert.equal(JSON.stringify(board).includes("model_probability"), false);
  assert.equal(JSON.stringify(board).includes("model_vs_close"), false);
  assert.match(text, /Research divergence, not a recommendation\./);
});

test("gate counter uses the supplied view count, including zero", () => {
  assert.equal(formatGateCount(0), "0 / 600");
  assert.equal(formatGateCount(null), UNAVAILABLE);
  assert.equal(formatGateCount(472), "472 / 600");
  const board = assembleResearchBoard({
    now: NOW,
    evaluableCount: 0,
    committedCount: 472,
    signals: [fixtureSignal(), fixtureSignal({ eventId: "2026_10_CCC_DDD", gameId: "2026_10_CCC_DDD" })],
    snapshots: [],
  });
  assert.equal(board.cards.length, 2);
  assert.equal(board.gateLabel, "0 / 600");
  assert.equal(board.evaluableLabel, "0 / 600");
  assert.equal(board.committedCount, 472);
  assert.equal(board.committedLabel, "472 committed forecasts");
});

test("model version and divergence come from captured snapshot fields", () => {
  const board = assembleResearchBoard({
    now: NOW,
    gateCount: 3,
    signals: [
      fixtureSignal({
        modelVersion: "from-ledger-row",
        payload: {
          slate: "2026-W10",
          player_name: "Fixture Player",
          model_snapshot_id: "snap-1",
          model_snapshot_hash: "hash-1",
          observations: [
            {
              book: "fixture-book",
              line: 5,
              observed_at: "2026-11-04T11:00:00+00:00",
              receipt_status: "NO_INDEPENDENT_SOURCE_RECEIPT",
            },
          ],
        },
      }),
    ],
    snapshots: [
      {
        snapshot_id: "snap-1",
        content_hash: "hash-1",
        created_at: "2026-11-04T10:00:00+00:00",
        market: "receptions",
        model: { version: "fixture-model-9" },
        projection: {
          fair_line: 10,
          proj_volume: 8.5,
          distribution_params: { mu_rec: 4, alpha: 0.25 },
          p_over: 0.4242,
        },
      },
    ],
  });
  const text = renderResearchBoardText(board);
  assert.equal(board.modelVersion, "fixture-model-9");
  assert.equal(board.cards[0].fairLine, "10");
  assert.equal(board.cards[0].projectedVolume, "8.5");
  assert.equal(board.weekLabel, "2026-W10");
  assert.equal(board.games[0].eventId, "2026_10_AAA_BBB");
  assert.equal(board.cards[0].quotes[0].line, "5");
  assert.equal(board.cards[0].quotes[0].verification, "NO_INDEPENDENT_SOURCE_RECEIPT");
  assert.equal(board.cards[0].quotes[0].staleness, "captured");
  assert.equal(board.divergence[0].divergence, "1.77σ");
  assert.equal(board.gateLabel, "3 / 600");
  assert.equal(text.includes("0.4242"), false);
  assert.equal(text.includes("from-ledger-row"), false);
  assert.equal(modelSd("receptions", { mu_rec: 4, alpha: 0.25 }), Math.sqrt(8));
  assert.equal(modelSd("receptions", { mu_rec: 4 }), null);
});

test("naive or future snapshot timestamps are labeled and not used as numbers", () => {
  const future = assembleResearchBoard({
    now: NOW,
    gateCount: 0,
    signals: [
      fixtureSignal({
        payload: { model_snapshot_id: "snap-f", model_snapshot_hash: "hash-f" },
      }),
    ],
    snapshots: [
      {
        snapshot_id: "snap-f",
        content_hash: "hash-f",
        created_at: "2026-11-05T00:00:00+00:00",
        model: { version: "future-model" },
        projection: { fair_line: 88.5, proj_volume: 70, distribution_params: { mu_rec: 4, alpha: 0.25 } },
      },
    ],
  });
  assert.equal(future.cards[0].snapshotClock, "rejected_future_timestamp");
  assert.equal(future.cards[0].fairLine, UNAVAILABLE);
  assert.equal(future.modelVersion, UNAVAILABLE);
  assert.equal(renderResearchBoardText(future).includes("88.5"), false);

  const naive = assembleResearchBoard({
    now: NOW,
    gateCount: 0,
    signals: [
      fixtureSignal({
        payload: {
          model_snapshot_id: "snap-n",
          model_snapshot_hash: "hash-n",
          observations: [{ book: "fixture-book", line: 6, observed_at: "2026-11-04T11:00:00" }],
        },
      }),
    ],
    snapshots: [
      {
        snapshot_id: "snap-n",
        content_hash: "hash-n",
        created_at: "2026-11-04T10:00:00",
        model: { version: "naive-model" },
        projection: { fair_line: 77, proj_volume: 70 },
      },
    ],
  });
  assert.equal(naive.cards[0].snapshotClock, "rejected_naive_timestamp");
  assert.equal(naive.cards[0].quotes[0].staleness, "rejected_naive_timestamp");
  assert.equal(naive.cards[0].quotes[0].capturedAt, "rejected_naive_timestamp");
  assert.equal(renderResearchBoardText(naive).includes("naive-model"), false);
  assert.equal(naive.cards[0].fairLine, UNAVAILABLE);
});

test("an empty ledger query is unavailable rather than a stand-in count", async () => {
  const previous = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  try {
    const board = await loadResearchBoard({ snapshots: [], now: NOW });
    assert.equal(board.gateLabel, UNAVAILABLE);
    assert.equal(board.cards.length, 0);
    assert.equal(board.modelVersion, UNAVAILABLE);
  } finally {
    if (previous === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = previous;
  }
});
