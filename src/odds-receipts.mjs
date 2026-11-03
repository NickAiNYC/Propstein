import { createHash } from 'node:crypto';

const REQUIRED_QUOTE_ID_FIELDS = [
  'provider',
  'event_id',
  'bookmaker',
  'market',
  'outcome',
  'point',
  'provider_last_update'
];

export function sha256Hex(value) {
  const input = typeof value === 'string' ? value : JSON.stringify(value);
  return createHash('sha256').update(input).digest('hex');
}

export function createProviderQuoteId(quote) {
  for (const field of REQUIRED_QUOTE_ID_FIELDS) {
    if (quote[field] === undefined || quote[field] === null || String(quote[field]).trim() === '') {
      throw new TypeError(`Missing provider quote identity field: ${field}`);
    }
  }

  const canonicalIdentity = REQUIRED_QUOTE_ID_FIELDS
    .map((field) => `${field}=${String(quote[field]).trim()}`)
    .join('\n');
  return sha256Hex(canonicalIdentity);
}

export function createVerificationReceipt({ quote, rawPayload, sourceUrl, fetchedAt }) {
  if (!/^https:\/\//i.test(String(sourceUrl || ''))) {
    throw new TypeError('sourceUrl must be an HTTPS provider endpoint.');
  }
  if (Number.isNaN(Date.parse(fetchedAt))) {
    throw new TypeError('fetchedAt must be an ISO timestamp.');
  }

  return {
    status: 'VERIFIED',
    provider_quote_id: createProviderQuoteId(quote),
    source_url: sourceUrl,
    raw_payload_sha256: sha256Hex(rawPayload),
    provider_last_update: quote.provider_last_update,
    fetched_at: fetchedAt
  };
}
