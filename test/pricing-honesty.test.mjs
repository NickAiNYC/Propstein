import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// Every page that renders the pricing dialog. public/ is a stale mirror of the
// pre-rebrand site and is not deployed (root vercel.json -> outputDirectory
// viewer), so it is intentionally not listed here.
const PRICING_PAGES = [
  '../viewer/index.html',
  '../viewer/ledger.html',
  '../viewer/ledger/index.html',
  '../viewer/audit.html'
];

test('pricing tiers make no ingestion-speed or unbuilt-capability claims', async () => {
  for (const page of PRICING_PAGES) {
    const html = await read(page);
    assert.doesNotMatch(html, /sub-minute/i, `${page}: "sub-minute" ingestion claim must not exist (feed refreshes every 4 hours)`);
    assert.doesNotMatch(html, /priority ingestion/i, `${page}: "priority ingestion" claim must not exist`);
    assert.doesNotMatch(html, /api\/v1\/slate/i, `${page}: must not advertise the /api/v1/slate endpoint (no such API is built)`);
    assert.doesNotMatch(html, /Custom Kelly covariance/i, `${page}: must not advertise custom Kelly covariance parameters (feature does not exist)`);
  }
});

test('pricing states the real odds refresh cadence at every tier', async () => {
  for (const page of PRICING_PAGES) {
    const html = await read(page);
    assert.match(html, /every 4 hours|four-hour/i, `${page}: the true cadence must be stated`);
    assert.match(html, /same as every tier/i, `${page}: cadence must be declared identical across tiers`);
  }
});

test('paid CTAs respect the public signup freeze', async () => {
  for (const page of PRICING_PAGES) {
    const html = await read(page);
    assert.doesNotMatch(html, /data-checkout-tier/, `${page}: pricing CTAs must not start a Stripe checkout while paid signups are frozen`);
    assert.match(html, /Paid signups frozen|Waitlisted/i, `${page}: freeze/waitlist state must be visible on the tier cards`);
    assert.match(html, /href="\/performance\/"/, `${page}: CTAs must link to the public validation status page`);
  }
});

test('homepage status line keeps receipt evidence distinct from freshness', async () => {
  const app = await read('../viewer/app.js');
  assert.match(app, /model-ranked research lines\. \$\{verifiedQuotes\} receipt-verified in snapshot\. Qualification paused: waiting on \$\{waitingOn\}/);
  assert.match(app, /fresh timestamped odds \(\$\{feedVerificationLabel\(\)\.toLowerCase\(\)\}\)/);
  assert.doesNotMatch(app, /source-unspecified\} research lines ·/, 'long detail line must stay out of the homepage status');
});
