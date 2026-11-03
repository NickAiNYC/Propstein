const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function loadAppHarness() {
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    document: { addEventListener() {}, getElementById() { return null; }, documentElement: { getAttribute() { return 'light'; }, setAttribute() {} }, body: { classList: { toggle() {} } } },
    window: { addEventListener() {}, scrollTo() {}, open() {} },
    navigator: {},
    localStorage: { getItem() { return null; }, setItem() {} },
    fetch: async () => ({ ok: false }),
  };
  vm.createContext(sandbox);
  const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8') + `
    globalThis.__test = {
      evaluateLineAndOdds,
      getQuoteValidation,
      getEvaluatedPlayerRow,
      setEvaluationState(next) {
        currentFilterMarket = next.market || 'yards';
        currentViewMode = next.viewMode || 'verified_quotes';
        currentLiveOddsData = next.liveOdds || null;
        currentInjuriesData = next.injuries || null;
        inlinePlayerLines = {};
        isHistoricalSlate = false;
        evaluationCache.clear();
      }
    };
  `;
  vm.runInContext(source, sandbox, { filename: 'app.js' });
  return sandbox.__test;
}

function makeQuote(player, nowMs) {
  const providerTime = new Date(nowMs - 60_000).toISOString();
  return {
    quote_id: 'test-quote',
    book: 'TestBook',
    player_id: player.player_id,
    player_name: player.player_display_name,
    team: player.team,
    opponent: player.opponent_team,
    game_id: player.game_id,
    market: 'receiving_yards',
    line: 10.5,
    over_odds: -110,
    under_odds: -110,
    observed_at: providerTime,
    verification: {
      status: 'VERIFIED',
      provider_quote_id: 'a'.repeat(64),
      source_url: 'https://api.provider.example/v1/odds/events/test',
      raw_payload_sha256: 'b'.repeat(64),
      provider_last_update: providerTime,
      fetched_at: new Date(nowMs - 30_000).toISOString()
    }
  };
}

const slate = JSON.parse(fs.readFileSync(path.join(root, 'slate_2026_w7.json'), 'utf8'));
const mack = slate.find((row) => row.player_display_name === 'Mack Hollins');

test('Mack Hollins fair-line probabilities are complementary and push-aware', () => {
  const app = loadAppHarness();
  assert.equal(mack.fair_line_yards, 30);

  const halfYard = app.evaluateLineAndOdds(mack.mu_rec, mack.mu_ypr, 'yards', 29.5, -110, 0);
  assert.ok(Math.abs(halfYard.pOver - 0.5073520298) < 1e-6);
  assert.ok(Math.abs(halfYard.pUnder - 0.4926479702) < 1e-6);
  assert.ok(Math.abs(halfYard.pOver + halfYard.pUnder - 1) < 1e-10);

  const wholeYard = app.evaluateLineAndOdds(mack.mu_rec, mack.mu_ypr, 'yards', 30, -110, 0);
  assert.ok(wholeYard.pPush > 0);
  assert.ok(Math.abs(wholeYard.pOver + wholeYard.pUnder + wholeYard.pPush - 1) < 1e-10);
  const overDecision = wholeYard.pOver / (wholeYard.pOver + wholeYard.pUnder);
  const underDecision = wholeYard.pUnder / (wholeYard.pOver + wholeYard.pUnder);
  assert.ok(Math.abs(overDecision + underDecision - 1) < 1e-10);
});

test('complete, fresh provider receipt is accepted', () => {
  const app = loadAppHarness();
  const now = Date.now();
  const quote = makeQuote(mack, now);
  const result = app.getQuoteValidation(quote, mack, 'receiving_yards', now);
  assert.equal(result.isValid, true, result.reasons.join(', '));
});

for (const scenario of [
  ['missing source URL', (quote) => { delete quote.verification.source_url; }],
  ['malformed source URL', (quote) => { quote.verification.source_url = 'provider.example/quote'; }],
  ['malformed provider receipt', (quote) => { quote.verification.provider_quote_id = 'not-a-sha256'; }],
  ['missing raw payload hash', (quote) => { delete quote.verification.raw_payload_sha256; }],
  ['stale provider timestamp', (quote, now) => {
    quote.observed_at = new Date(now - 11 * 60_000).toISOString();
    quote.verification.provider_last_update = quote.observed_at;
    quote.verification.fetched_at = new Date(now - 10.5 * 60_000).toISOString();
  }]
]) {
  test(`${scenario[0]} fails closed with zero qualification and zero stake`, () => {
    const app = loadAppHarness();
    const now = Date.now();
    const quote = makeQuote(mack, now);
    scenario[1](quote, now);
    const validation = app.getQuoteValidation(quote, mack, 'receiving_yards', now);
    assert.equal(validation.isValid, false);

    app.setEvaluationState({ liveOdds: { updated_at: new Date(now).toISOString(), quotes: [quote] } });
    const row = app.getEvaluatedPlayerRow(mack);
    assert.equal(row.isVerifiedQuote, false);
    assert.equal(row.isQualified, false);
    assert.equal(row.status, 'DATA CHECK');
    assert.equal(row.actionableStake, 0);
  });
}

test('bundled demonstration feed has no verified or staked quotes', () => {
  const feed = JSON.parse(fs.readFileSync(path.join(root, 'live_odds_feed.json'), 'utf8'));
  assert.equal(feed.feed_origin, 'bundled_demonstration_fixture');
  assert.equal(feed.verified_books_count, 0);
  assert.equal(feed.qualified_count, 0);
  assert.equal(feed.quotes.length, 10);
  for (const quote of feed.quotes) {
    assert.equal(quote.evaluation.is_qualified, false);
    assert.equal(quote.evaluation.actionable_stake, 0);
  }
});
