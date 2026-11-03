import test from 'node:test';
import assert from 'node:assert/strict';
import { createProviderQuoteId, createVerificationReceipt, sha256Hex } from '../src/odds-receipts.mjs';

const quote = {
  provider: 'the-odds-api',
  event_id: 'event-123',
  bookmaker: 'draftkings',
  market: 'player_reception_yds',
  outcome: 'Over',
  point: 54.5,
  provider_last_update: '2026-10-20T09:00:00.000Z'
};

test('provider quote IDs are deterministic across retries', () => {
  assert.equal(createProviderQuoteId(quote), createProviderQuoteId({ ...quote }));
  assert.match(createProviderQuoteId(quote), /^[a-f0-9]{64}$/);
});

test('identity changes produce a different receipt ID', () => {
  assert.notEqual(createProviderQuoteId(quote), createProviderQuoteId({ ...quote, point: 55.5 }));
});

test('receipt binds the quote to the stored raw response', () => {
  const rawPayload = JSON.stringify({ id: quote.event_id, bookmakers: [] });
  const receipt = createVerificationReceipt({
    quote,
    rawPayload,
    sourceUrl: 'https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/event-123/odds',
    fetchedAt: '2026-10-20T09:00:20.000Z'
  });
  assert.equal(receipt.status, 'VERIFIED');
  assert.equal(receipt.raw_payload_sha256, sha256Hex(rawPayload));
  assert.match(receipt.provider_quote_id, /^[a-f0-9]{64}$/);
});
