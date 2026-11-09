/**
 * PropStein — deterministic demo seed.
 *
 * Creates the demo pseudonymous user with a realistic, honest record:
 *   - NFL entries with calibrated model coverage (REC-V4) and an
 *     INCONCLUSIVE record (interval includes zero — the honest verdict).
 *   - NBA entries with market comparison but no model coverage.
 *   - Exclusion fixtures: pushes, void, canceled, DNP, stale close,
 *     conflicting close, missing close, duplicate pair, correlated pair,
 *     one UNVERIFIED CONTEXT entry.
 *   - Gate history: NFL attempt 1 FAIL (descriptive interim included),
 *     attempt 2 accumulating; NBA IN_PROGRESS; UFC PENDING.
 *     Compliance: all sports denied/pending. Commercial flags: DENIED.
 *   - Alert preferences + a small feed.
 *
 * Run: bunx bun scripts/seed.ts   (or: bun scripts/seed.ts)
 */

import { PrismaClient } from '@prisma/client';
import { createLedgerEntry } from '../src/lib/domain/ledger';
import { canonicalJson, gauss, mulberry32, seedFrom, sha256hex } from '../src/lib/domain/determinism';
import { americanFromImplied, devigTwoWay, fairProbabilityForSide, impliedProbability } from '../src/lib/domain/odds';
import { evaluateGateAttempt } from '../src/lib/domain/gate';
import { assessModelCoverage } from '../src/lib/domain/model-registry';

const db = new PrismaClient();

const DEMO_PSEUDONYM = 'PS-DEMO1';

interface SeedSpec {
  ledgerId: string;
  daysAgo: number;
  sport: 'NFL' | 'NBA';
  eventLabel: string;
  playerName: string;
  market: string;
  marketLabel: string;
  selection: 'over' | 'under';
  line: number;
  enteredOdds: number;
  counterpartOdds: number;
  /** target CLV in pp for the close construction */
  clvPp?: number;
  closeQuality?: 'fresh' | 'stale' | 'missing' | 'conflicting';
  settle?: 'settled-win' | 'settled-loss' | 'push' | 'void' | 'canceled' | 'dnp' | 'pending';
  duplicateOf?: string;
  correlatedWith?: string;
  unverifiedContext?: boolean;
  sourceType?: 'manual_entry' | 'screenshot_upload' | 'extension_observation';
}

const NFL_PLAYERS = [
  'J. Chase', 'T. Hill', 'C. Lamb', 'A. St. Brown', 'D. Adams', 'G. Wilson',
  'D. London', 'M. Evans', 'C. Olave', 'J. Jefferson', 'P. Nacua', 'K. Allen',
  'T. Higgins', 'D. Smith', 'R. Rice', 'Z. Flowers', 'X. Worthy', 'B. Nico',
];

const NBA_PLAYERS = ['J. Doncic', 'S. Curry', 'G. Antetokounmpo', 'K. Durant', 'L. James', 'N. Jokic'];

function dayIso(daysAgo: number, hourUtc = 18, minute = 0): string {
  const d = new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000);
  d.setUTCHours(hourUtc, minute, 0, 0);
  return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function buildSpecs(): SeedSpec[] {
  const specs: SeedSpec[] = [];
  const rand = mulberry32(seedFrom('ledger-seed-v1'));

  // --- 38 settled, evaluable NFL entries across 20 games -----------------
  const games: { label: string; id: string }[] = [];
  for (let g = 0; g < 20; g++) {
    const home = ['KC', 'BUF', 'DAL', 'PHI', 'SF', 'MIA', 'BAL', 'DET', 'GB', 'TB',
      'CIN', 'HOU', 'LAR', 'PIT', 'MIN', 'ATL', 'NYJ', 'DEN', 'LV', 'CHI'][g];
    const away = ['DEN', 'MIA', 'NYJ', 'WAS', 'SEA', 'NE', 'CIN', 'GB', 'MIN', 'ATL',
      'LAR', 'JAX', 'ARI', 'CLE', 'CHI', 'CAR', 'HOU', 'LV', 'NO', 'PIT'][(g + 7) % 20];
    games.push({ label: `${away} @ ${home}`, id: `event:${away.toLowerCase()}-at-${home.toLowerCase()}-w${g}` });
  }

  let n = 0;
  for (let i = 0; i < 38; i++) {
    const game = games[i % 20];
    const player = NFL_PLAYERS[i % NFL_PLAYERS.length];
    // Two entries share a game+player on game 3 for the correlation fixture.
    const line = 32.5 + Math.round(rand() * 4) * 0.5 + (i % 5);
    const juice = -105 - Math.round(rand() * 25); // -105..-130
    specs.push({
      ledgerId: `seed-nfl-${String(++n).padStart(3, '0')}`,
      daysAgo: 3 + Math.floor(i / 20) * 4 + (i % 3),
      sport: 'NFL',
      eventLabel: game.label,
      playerName: player,
      market: 'player_reception_yds',
      marketLabel: 'Receiving Yards',
      selection: i % 4 === 0 ? 'under' : 'over',
      line,
      enteredOdds: juice,
      counterpartOdds: -105 - Math.round(rand() * 20),
      clvPp: Number((gauss(rand) * 2.4 + 0.32).toFixed(3)),
      closeQuality: 'fresh',
      settle: rand() < 0.5 ? 'settled-win' : 'settled-loss',
      sourceType: i % 3 === 0 ? 'screenshot_upload' : 'manual_entry',
    });
  }

  // --- Correlated pair: same game, same player, different market ----------
  const corrGame = games[3];
  specs.push({
    ledgerId: 'seed-nfl-corr-a',
    daysAgo: 6,
    sport: 'NFL',
    eventLabel: corrGame.label,
    playerName: NFL_PLAYERS[3],
    market: 'player_reception_yds',
    marketLabel: 'Receiving Yards',
    selection: 'over',
    line: 64.5,
    enteredOdds: -110,
    counterpartOdds: -110,
    clvPp: 1.4,
    closeQuality: 'fresh',
    settle: 'settled-win',
  });
  specs.push({
    ledgerId: 'seed-nfl-corr-b',
    daysAgo: 6,
    sport: 'NFL',
    eventLabel: corrGame.label,
    playerName: NFL_PLAYERS[3],
    market: 'player_reception_yds',
    marketLabel: 'Receiving Yards',
    selection: 'over',
    line: 64.5,
    enteredOdds: -115,
    counterpartOdds: -105,
    clvPp: 0.9,
    closeQuality: 'fresh',
    settle: 'settled-loss',
    correlatedWith: 'seed-nfl-corr-a',
  });

  // --- Exclusion fixtures ---------------------------------------------------
  specs.push({
    ledgerId: 'seed-nfl-push-1', daysAgo: 8, sport: 'NFL', eventLabel: games[7].label,
    playerName: NFL_PLAYERS[7], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 75, enteredOdds: -110, counterpartOdds: -110,
    clvPp: 0.8, closeQuality: 'fresh', settle: 'push',
  });
  specs.push({
    ledgerId: 'seed-nfl-push-2', daysAgo: 12, sport: 'NFL', eventLabel: games[11].label,
    playerName: NFL_PLAYERS[11], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'under', line: 22, enteredOdds: -115, counterpartOdds: -105,
    clvPp: -0.6, closeQuality: 'fresh', settle: 'push',
  });
  specs.push({
    ledgerId: 'seed-nfl-void-1', daysAgo: 10, sport: 'NFL', eventLabel: games[9].label,
    playerName: NFL_PLAYERS[9], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 58.5, enteredOdds: -110, counterpartOdds: -110,
    clvPp: 0, closeQuality: 'fresh', settle: 'void',
  });
  specs.push({
    ledgerId: 'seed-nfl-canceled-1', daysAgo: 9, sport: 'NFL', eventLabel: games[13].label,
    playerName: NFL_PLAYERS[13], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 61.5, enteredOdds: -120, counterpartOdds: -100,
    closeQuality: 'missing', settle: 'canceled',
  });
  specs.push({
    ledgerId: 'seed-nfl-dnp-1', daysAgo: 7, sport: 'NFL', eventLabel: games[15].label,
    playerName: NFL_PLAYERS[15], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 54.5, enteredOdds: -115, counterpartOdds: -105,
    clvPp: 0.3, closeQuality: 'fresh', settle: 'dnp',
  });
  specs.push({
    ledgerId: 'seed-nfl-staleclose-1', daysAgo: 11, sport: 'NFL', eventLabel: games[5].label,
    playerName: NFL_PLAYERS[5], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 66.5, enteredOdds: -110, counterpartOdds: -110,
    clvPp: 1.1, closeQuality: 'stale', settle: 'settled-win',
  });
  specs.push({
    ledgerId: 'seed-nfl-staleclose-2', daysAgo: 14, sport: 'NFL', eventLabel: games[17].label,
    playerName: NFL_PLAYERS[17], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'under', line: 48.5, enteredOdds: -108, counterpartOdds: -112,
    clvPp: -1.2, closeQuality: 'stale', settle: 'settled-loss',
  });
  specs.push({
    ledgerId: 'seed-nfl-conflict-1', daysAgo: 13, sport: 'NFL', eventLabel: games[2].label,
    playerName: NFL_PLAYERS[2], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 72.5, enteredOdds: -105, counterpartOdds: -115,
    clvPp: 0.6, closeQuality: 'conflicting', settle: 'settled-win',
  });
  specs.push({
    ledgerId: 'seed-nfl-missingclose-1', daysAgo: 5, sport: 'NFL', eventLabel: games[6].label,
    playerName: NFL_PLAYERS[6], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 59.5, enteredOdds: -112, counterpartOdds: -108,
    closeQuality: 'missing', settle: 'settled-loss',
  });

  // --- Duplicate pair --------------------------------------------------------
  specs.push({
    ledgerId: 'seed-nfl-dup-1', daysAgo: 4, sport: 'NFL', eventLabel: games[1].label,
    playerName: NFL_PLAYERS[1], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 88.5, enteredOdds: -115, counterpartOdds: -105,
    clvPp: 2.1, closeQuality: 'fresh', settle: 'settled-win',
  });

  // --- Uncalibrated model market (passing yards) ----------------------------
  specs.push({
    ledgerId: 'seed-nfl-pass-1', daysAgo: 6, sport: 'NFL', eventLabel: games[8].label,
    playerName: 'P. Mahomes', market: 'player_passing_yds', marketLabel: 'Passing Yards',
    selection: 'over', line: 262.5, enteredOdds: -110, counterpartOdds: -110,
    clvPp: 0.7, closeQuality: 'fresh', settle: 'settled-win',
  });

  // --- Unverified context fixture -------------------------------------------
  specs.push({
    ledgerId: 'seed-nfl-unverified-1', daysAgo: 2, sport: 'NFL', eventLabel: games[19].label,
    playerName: NFL_PLAYERS[16], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 51.5, enteredOdds: -110, counterpartOdds: -110,
    closeQuality: 'missing', settle: 'pending', unverifiedContext: true,
  });

  // --- Pending entries (alert + close/settle demo) ---------------------------
  specs.push({
    ledgerId: 'seed-nfl-pending-1', daysAgo: 0, sport: 'NFL', eventLabel: 'DEN @ KC',
    playerName: NFL_PLAYERS[0], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 62.5, enteredOdds: -115, counterpartOdds: -105,
    closeQuality: 'missing', settle: 'pending', sourceType: 'screenshot_upload',
  });
  specs.push({
    ledgerId: 'seed-nfl-pending-2', daysAgo: 0, sport: 'NFL', eventLabel: 'MIA @ BUF',
    playerName: NFL_PLAYERS[1], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'under', line: 54.5, enteredOdds: -108, counterpartOdds: -112,
    closeQuality: 'missing', settle: 'pending',
  });
  specs.push({
    ledgerId: 'seed-nfl-pending-3', daysAgo: 1, sport: 'NFL', eventLabel: 'SF @ SEA',
    playerName: NFL_PLAYERS[4], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 69.5, enteredOdds: -120, counterpartOdds: -100,
    closeQuality: 'missing', settle: 'pending', sourceType: 'extension_observation',
  });

  // --- NBA entries (no model coverage) --------------------------------------
  for (let i = 0; i < 11; i++) {
    const game = [`LAL @ BOS`, `GSW @ PHX`, `MIL @ NYK`, `DAL @ DEN`, `BKN @ MIA`,
      'OKC @ MIN', 'CLE @ ORL', 'SAC @ POR', 'PHI @ TOR', 'ATL @ CHA', 'HOU @ SAS'][i];
    specs.push({
      ledgerId: `seed-nba-${String(i + 1).padStart(3, '0')}`,
      daysAgo: 2 + (i % 6),
      sport: 'NBA',
      eventLabel: game,
      playerName: NBA_PLAYERS[i % NBA_PLAYERS.length],
      market: 'player_points',
      marketLabel: 'Points',
      selection: i % 3 === 0 ? 'under' : 'over',
      line: 24.5 + Math.round(rand() * 6),
      enteredOdds: -110 - Math.round(rand() * 20),
      counterpartOdds: -110 - Math.round(rand() * 15),
      clvPp: Number((gauss(rand) * 2.8 - 0.4).toFixed(3)),
      closeQuality: i === 9 ? 'stale' : 'fresh',
      settle: i === 9 ? 'pending' : rand() < 0.55 ? 'settled-win' : 'settled-loss',
      sourceType: i % 4 === 0 ? 'screenshot_upload' : 'manual_entry',
    });
  }

  // Duplicate of seed-nfl-dup-1 (identical dedupe key)
  specs.push({
    ledgerId: 'seed-nfl-dup-2', daysAgo: 4, sport: 'NFL', eventLabel: games[1].label,
    playerName: NFL_PLAYERS[1], market: 'player_reception_yds', marketLabel: 'Receiving Yards',
    selection: 'over', line: 88.5, enteredOdds: -115, counterpartOdds: -105,
    clvPp: 2.1, closeQuality: 'fresh', settle: 'settled-win',
    duplicateOf: 'seed-nfl-dup-1',
  });

  return specs;
}

async function main() {
  console.log('Seeding PropStein demo data…');

  // Reset (order respects FK-less SQLite; explicit).
  await db.alertEvent.deleteMany();
  await db.alertPreference.deleteMany();
  await db.auditEvent.deleteMany();
  await db.settlement.deleteMany();
  await db.closingReference.deleteMany();
  await db.marketSnapshot.deleteMany();
  await db.ledgerRevision.deleteMany();
  await db.ledgerEntry.deleteMany();
  await db.assessment.deleteMany();
  await db.slipUpload.deleteMany();
  await db.gateSignal.deleteMany();
  await db.gateAttempt.deleteMany();
  await db.complianceApproval.deleteMany();
  await db.entitlement.deleteMany();
  await db.sessionToken.deleteMany();
  await db.user.deleteMany();

  const user = await db.user.create({
    data: { pseudonym: DEMO_PSEUDONYM, plan: 'pro' },
  });

  // Entitlements (server-side verification data).
  for (const surface of ['market_comparison', 'closing_reference', 'model_panel', 'alerts']) {
    for (const scope of ['NFL', 'NBA', '*']) {
      await db.entitlement.create({
        data: { userId: user.id, surface, scope, status: 'active', source: 'plan:pro' },
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Ledger entries
  // ---------------------------------------------------------------------------
  const specs = buildSpecs();
  const rand = mulberry32(seedFrom('settle-seed-v1'));

  for (const spec of specs) {
    const capturedAt = dayIso(spec.daysAgo, 18, 4);
    const eventId = `event:${spec.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
    const eventKey = `${spec.sport}:${eventId}:player:${spec.playerName.toLowerCase().replace(/[^a-z]+/g, '-')}:${spec.market}:${spec.line}`;
    const model = assessModelCoverage(spec.sport, spec.market, spec.selection, spec.line, eventKey);

    // Price assessment label for the seed record (market-hurdle verdict from
    // the seeded CLV direction; unverified-context fixture overrides).
    const assessment =
      spec.unverifiedContext
        ? 'UNVERIFIED CONTEXT'
        : (spec.clvPp ?? 0) > 0.25
          ? 'PRICE ABOVE MARKET HURDLE'
          : (spec.clvPp ?? 0) < -0.25
            ? 'PRICE BELOW MARKET HURDLE'
            : 'PRICE AT MARKET HURDLE';

    const provenanceInputs = [
      { key: 'spread', label: 'Game spread', sourceId: 'CTX-ODDS-1 (simulated)', observedAtUtc: dayIso(spec.daysAgo, 17, 55), value: 'HOME -3' },
      { key: 'total', label: 'Game total', sourceId: 'CTX-ODDS-1 (simulated)', observedAtUtc: dayIso(spec.daysAgo, 17, 55), value: '47.5' },
      {
        key: 'weather',
        label: 'Weather (kickoff forecast)',
        sourceId: 'CTX-WX-1 (simulated)',
        observedAtUtc: spec.unverifiedContext ? null : dayIso(spec.daysAgo, 17, 30),
        value: spec.sport === 'NFL' ? 'Clear, wind 7 mph' : 'n/a (indoor)',
      },
      { key: 'injury_status', label: 'Injury / status report', sourceId: 'CTX-INJ-1 (simulated)', observedAtUtc: dayIso(spec.daysAgo + 1, 16, 0), value: 'Questionable (limited)' },
      { key: 'player_form', label: 'Player form', sourceId: 'CTX-FORM-1 (simulated)', observedAtUtc: dayIso(spec.daysAgo + 1, 15, 0), value: 'Within season baseline' },
      { key: 'opponent_coverage', label: 'Opponent coverage profile', sourceId: 'CTX-COV-1 (simulated)', observedAtUtc: dayIso(spec.daysAgo + 1, 15, 0), value: 'Zone-heavy' },
      { key: 'market_quote', label: 'Market quote', sourceId: 'BOOK-USER', observedAtUtc: capturedAt, value: `${spec.selection === 'over' ? 'Over' : 'Under'} ${spec.line} at ${spec.enteredOdds}` },
    ];
    const provenancePayload = {
      provenance: {
        inputs: provenanceInputs,
        pricingCutoffUtc: capturedAt,
        snapshotHash: sha256hex(canonicalJson(provenanceInputs)),
      },
      scenario: spec.unverifiedContext ? 'unverified_context' : 'none',
    };

    const { entry, initialRevision } = createLedgerEntry(
      {
        userId: user.id,
        sourceType: spec.sourceType ?? 'manual_entry',
        sport: spec.sport,
        league: spec.sport,
        eventId,
        gameClusterId: `${spec.sport}:${eventId}`,
        playerId: `player:${spec.playerName.toLowerCase().replace(/[^a-z]+/g, '-')}`,
        playerName: spec.playerName,
        market: spec.market,
        selection: spec.selection,
        line: spec.line,
        enteredAmericanOdds: spec.enteredOdds,
        enteredCounterpartOdds: spec.counterpartOdds,
        enteredImpliedProbability: Number(impliedProbability(spec.enteredOdds).toFixed(4)),
        breakEvenProbability: Number(impliedProbability(spec.enteredOdds).toFixed(4)),
        book: spec.sourceType === 'extension_observation' ? 'observed-book-a' : 'user_entered',
        capturedAtUtc: capturedAt,
        snapshotHash: sha256hex(canonicalJson(provenancePayload)),
        modelVersion: model.coverage === 'calibrated' ? model.modelVersion : model.coverage === 'uncalibrated' ? model.modelVersion : null,
        modelCoverage: model.coverage === 'unavailable' ? 'none' : model.coverage,
        modelProbability: model.probability,
        modelUncertaintyLower: model.uncertainty?.lower ?? null,
        modelUncertaintyUpper: model.uncertainty?.upper ?? null,
        priceAssessment: assessment,
        provenanceJson: canonicalJson(provenancePayload),
        duplicateOfLedgerId: spec.duplicateOf ?? null,
        correlationGroup: spec.correlatedWith ? `corr:${spec.sport}:${eventId}:player:${spec.playerName.toLowerCase().replace(/[^a-z]+/g, '-')}` : null,
        correlationReason: spec.correlatedWith ? 'Same game cluster and player as an existing record' : null,
      },
      dayIso(spec.daysAgo, 18, 6),
    );

    await db.ledgerEntry.create({
      data: {
        ...entry,
        ledgerId: spec.ledgerId, // stable ids for the demo fixtures
        capturedAtUtc: new Date(entry.capturedAtUtc),
        revisions: {
          create: {
            revisionNo: 0,
            reasonCode: 'ENTRY_CREATED',
            reasonText: 'Ledger entry created from a confirmed assessment. Append-only record starts here.',
            actor: user.id,
            changedFieldsJson: '[]',
            priorHash: 'GENESIS',
            newHash: entry.entryHash,
            createdAtUtc: new Date(entry.createdAtUtc),
          },
        },
      },
    });

    // Closing reference with the target CLV.
    if (spec.closeQuality && spec.closeQuality !== 'missing') {
      const entryFair = fairProbabilityForSide(spec.enteredOdds, spec.counterpartOdds, spec.selection);
      const closeFair = Math.min(0.95, Math.max(0.05, entryFair + (spec.clvPp ?? 0) / 100));
      const vig = 0.05;
      const closeOverFair = spec.selection === 'over' ? closeFair : 1 - closeFair;
      const overOdds = americanFromImplied(Math.min(0.97, closeOverFair * (1 + vig)));
      const underOdds = americanFromImplied(Math.min(0.97, (1 - closeOverFair) * (1 + vig)));
      const sideImplied = impliedProbability(spec.selection === 'over' ? overOdds : underOdds);
      const capturedCloseAt = dayIso(spec.daysAgo, 23, 30);
      const secondSource =
        spec.closeQuality === 'conflicting'
          ? { provider: 'DEMO-CLOSE-2 (simulated)', impliedProbability: Number((sideImplied + 0.028).toFixed(4)) }
          : { provider: 'DEMO-CLOSE-2 (simulated)', impliedProbability: Number((sideImplied + (rand() - 0.5) * 0.012).toFixed(4)) };
      await db.closingReference.create({
        data: {
          ledgerEntryId: spec.ledgerId,
          provider: 'DEMO-CLOSE-1 (simulated)',
          capturedAtUtc: new Date(capturedCloseAt),
          overAmericanOdds: overOdds,
          underAmericanOdds: underOdds,
          americanOdds: spec.selection === 'over' ? overOdds : underOdds,
          impliedProbability: Number(sideImplied.toFixed(4)),
          fairProbability: Number(closeFair.toFixed(4)),
          quality: spec.closeQuality,
          secondSourceJson: JSON.stringify(secondSource),
          independenceVerified: true,
          integrityHash: sha256hex(canonicalJson({ ledgerId: spec.ledgerId, closeFair, capturedCloseAt })),
        },
      });
    }

    // Settlement.
    if (spec.settle && spec.settle !== 'pending') {
      const map: Record<string, { status: string; result: string | null; reason: string | null; actual: number | null }> = {
        'settled-win': { status: 'settled', result: 'win', reason: null, actual: spec.line + 8 },
        'settled-loss': { status: 'settled', result: 'loss', reason: null, actual: spec.line - 7 },
        push: { status: 'push', result: 'push', reason: 'PUSH', actual: spec.line },
        void: { status: 'void', result: 'void', reason: 'VOID', actual: null },
        canceled: { status: 'canceled', result: null, reason: 'CANCELED', actual: null },
        dnp: { status: 'dnp', result: null, reason: 'DNP', actual: null },
      };
      const s = map[spec.settle];
      await db.settlement.create({
        data: {
          ledgerEntryId: spec.ledgerId,
          status: s.status,
          result: s.result,
          reasonCode: s.reason,
          actualValue: s.actual,
          source: 'DEMO-SETTLE-1 (simulated)',
          settledAtUtc: new Date(dayIso(Math.max(0, spec.daysAgo - 1), 3, 0)),
        },
      });
    }
  }

  // One correction revision on a settled entry (append-only demo).
  const rev = await db.ledgerRevision.findFirst({ where: { ledgerEntryId: 'seed-nfl-001' }, orderBy: { revisionNo: 'desc' } });
  if (rev) {
    await db.ledgerRevision.create({
      data: {
        ledgerEntryId: 'seed-nfl-001',
        revisionNo: 1,
        reasonCode: 'PLAYER_NAME_TYPO',
        reasonText: 'Player name spelling corrected from the source slip after review.',
        actor: user.id,
        changedFieldsJson: JSON.stringify({ playerName: NFL_PLAYERS[0] }),
        priorHash: rev.newHash,
        newHash: sha256hex(canonicalJson({ priorHash: rev.newHash, reasonCode: 'PLAYER_NAME_TYPO' })),
        createdAtUtc: new Date(dayIso(2, 12, 0)),
      },
    });
  }

  // ---------------------------------------------------------------------------
  // Gate signals: NFL attempt 1 (600 evaluable + excluded fixtures) -> FAIL;
  // attempt 2 accumulating (140). NBA 12 signals. UFC 0.
  // ---------------------------------------------------------------------------
  const gateRand = mulberry32(seedFrom('gate-seed-v1'));
  const sportsToSeed: { sport: 'NFL' | 'NBA'; attempt: number; evaluableCount: number; meanPp: number; sdPp: number; clusters: number }[] = [
    { sport: 'NFL', attempt: 1, evaluableCount: 600, meanPp: 0.42, sdPp: 2.6, clusters: 64 },
    { sport: 'NFL', attempt: 2, evaluableCount: 140, meanPp: 0.55, sdPp: 2.6, clusters: 24 },
    { sport: 'NBA', attempt: 1, evaluableCount: 12, meanPp: -0.3, sdPp: 2.8, clusters: 8 },
  ];

  for (const cfg of sportsToSeed) {
    const rows: {
      sport: string; signalId: string; gameClusterId: string; playerId: string;
      clvPp: number; evaluable: boolean; reasonCode: string | null;
      modelVersion: string | null; recordedAtUtc: Date; attemptScope: number;
    }[] = [];
    let dupBase: string | null = null;
    for (let i = 0; i < cfg.evaluableCount; i++) {
      const cluster = `${cfg.sport}:G${Math.floor(i / Math.ceil(cfg.evaluableCount / cfg.clusters))}`;
      const player = `P${(i * 7) % 97}`;
      const signalId = `${cfg.sport}|A${cfg.attempt}|${cluster}|${player}|mkt${i % 9}|${(i % 13) * 0.5}`;
      const clvPp = Number((gauss(gateRand) * cfg.sdPp + cfg.meanPp).toFixed(3));
      rows.push({
        sport: cfg.sport,
        signalId: `${signalId}#a`,
        gameClusterId: cluster,
        playerId: player,
        clvPp,
        evaluable: true,
        reasonCode: null,
        modelVersion: cfg.sport === 'NFL' ? 'REC-V4' : null,
        recordedAtUtc: new Date(Date.now() - (60 - i / 20) * 24 * 60 * 60 * 1000),
        attemptScope: cfg.attempt,
      });
      // Every 97th signal also exists as an exact duplicate and every 89th
      // adds a correlated sibling (same cluster+player, different market).
      if (i % 97 === 13 && i > 0) {
        rows[rows.length - 1].signalId = `${signalId}#a`;
        dupBase = signalId;
        rows.push({
          sport: cfg.sport,
          signalId: `${dupBase}#b`,
          gameClusterId: cluster,
          playerId: player,
          clvPp,
          evaluable: true,
          reasonCode: null,
          modelVersion: cfg.sport === 'NFL' ? 'REC-V4' : null,
          recordedAtUtc: new Date(Date.now() - (60 - i / 20) * 24 * 60 * 60 * 1000 + 5000),
          attemptScope: cfg.attempt,
        });
      }
      if (i % 89 === 31 && i > 0) {
        rows.push({
          sport: cfg.sport,
          signalId: `${cfg.sport}|A${cfg.attempt}|${cluster}|${player}|corr${i}|0.5#a`,
          gameClusterId: cluster,
          playerId: player,
          clvPp: Number((clvPp + 0.8).toFixed(3)),
          evaluable: true,
          reasonCode: null,
          modelVersion: cfg.sport === 'NFL' ? 'REC-V4' : null,
          recordedAtUtc: new Date(Date.now() - (60 - i / 20) * 24 * 60 * 60 * 1000 + 10000),
          attemptScope: cfg.attempt,
        });
      }
    }
    // Excluded fixtures with reason codes (retained, never silent).
    const excludedFixtures: { reason: string; count: number }[] = [
      { reason: 'PUSH', count: 8 },
      { reason: 'VOID', count: 2 },
      { reason: 'CANCELED', count: 1 },
      { reason: 'DNP', count: 3 },
      { reason: 'MISSING_CLOSE', count: 4 },
      { reason: 'STALE_CLOSE', count: 5 },
    ];
    let exIdx = 0;
    for (const fx of excludedFixtures) {
      for (let k = 0; k < fx.count; k++) {
        rows.push({
          sport: cfg.sport,
          signalId: `${cfg.sport}|A${cfg.attempt}|EX-${fx.reason}-${exIdx}`,
          gameClusterId: `${cfg.sport}:G${(exIdx * 3) % 60}`,
          playerId: `P${exIdx % 90}`,
          clvPp: 0,
          evaluable: false,
          reasonCode: fx.reason,
          modelVersion: cfg.sport === 'NFL' ? 'REC-V4' : null,
          recordedAtUtc: new Date(Date.now() - (55 - exIdx / 10) * 24 * 60 * 60 * 1000),
          attemptScope: cfg.attempt,
        });
        exIdx++;
      }
    }
    await db.gateSignal.createMany({ data: rows });
  }

  // Evaluate + persist attempt records (deterministic: fixed seed).
  for (const sport of ['NFL', 'NBA']) {
    for (const attemptNo of [1, 2]) {
      const signals = (
        await db.gateSignal.findMany({ where: { sport, attemptScope: attemptNo } })
      ).map((r) => ({
        signalId: r.signalId,
        sport: r.sport,
        gameClusterId: r.gameClusterId,
        playerId: r.playerId,
        clvPp: r.clvPp,
        evaluable: r.evaluable,
        reasonCode: (r.reasonCode ?? null) as never,
        modelVersion: r.modelVersion,
        recordedAtUtc: r.recordedAtUtc.toISOString(),
      }));
      if (signals.length === 0) continue;
      if (sport === 'NBA' && attemptNo === 2) continue;
      const result = evaluateGateAttempt(sport, attemptNo, signals, new Date().toISOString());
      await db.gateAttempt.create({
        data: {
          sport,
          attemptNo,
          nEvaluable: result.nEvaluable,
          distinctClusters: result.distinctClusters,
          meanClvPp: result.meanClvPp,
          bootstrapLbPp: result.bootstrapLbPp,
          verdict: result.verdict,
          seed: result.seed,
          replicates: result.replicates,
          modelVersionsJson: JSON.stringify(result.modelVersions),
          notesJson: JSON.stringify(result.notes),
          evaluatedAtUtc: new Date(),
        },
      });
      console.log(`Gate ${sport} attempt ${attemptNo}: ${result.verdict} (N=${result.nEvaluable}, mean=${result.meanClvPp}pp, LB=${result.bootstrapLbPp}pp)`);
    }
  }

  // Compliance approvals: all denied/pending (default deny).
  await db.complianceApproval.create({ data: { sport: 'NFL', status: 'denied', approver: 'compliance@propstein.demo', note: 'Gate attempt 1 FAIL; no approval possible.' } });
  await db.complianceApproval.create({ data: { sport: 'NBA', status: 'pending', approver: 'compliance@propstein.demo', note: 'No confirmatory evaluation yet.' } });
  await db.complianceApproval.create({ data: { sport: 'UFC', status: 'pending', approver: 'compliance@propstein.demo', note: 'No signals recorded.' } });

  // ---------------------------------------------------------------------------
  // Alert preferences + feed
  // ---------------------------------------------------------------------------
  for (const t of ['quote_changed', 'quote_aged', 'player_status', 'market_suspended', 'closing_available', 'entry_settled', 'entry_unevaluable']) {
    await db.alertPreference.create({ data: { userId: user.id, alertType: t, enabled: true } });
  }
  await db.alertEvent.createMany({
    data: [
      {
        userId: user.id, ledgerEntryId: 'seed-nfl-pending-1', type: 'quote_changed',
        message: 'Saved quote changed from -115 to -135.',
        snapshotTimeUtc: new Date(dayIso(0, 19, 2)), sourceProvider: 'DEMO-CMP-A (simulated)', delivered: true,
      },
      {
        userId: user.id, ledgerEntryId: 'seed-nfl-pending-2', type: 'quote_aged',
        message: 'Saved quote is now 9 minutes old.',
        snapshotTimeUtc: new Date(dayIso(0, 19, 5)), sourceProvider: 'DEMO-CMP-A (simulated)', delivered: true,
      },
      {
        userId: user.id, ledgerEntryId: 'seed-nfl-pending-3', type: 'player_status',
        message: 'Player status changed from Questionable to Out.',
        snapshotTimeUtc: new Date(dayIso(1, 20, 0)), sourceProvider: 'DEMO-STATUS-FEED (simulated)', delivered: true,
      },
      {
        userId: user.id, ledgerEntryId: 'seed-nfl-missingclose-1', type: 'entry_unevaluable',
        message: 'Saved entry is unevaluable because the closing reference is stale.',
        snapshotTimeUtc: new Date(dayIso(4, 2, 0)), sourceProvider: 'DEMO-CLOSE-1 (simulated)', delivered: true,
      },
    ],
  });

  // Audit events sample.
  for (let i = 0; i < 6; i++) {
    await db.auditEvent.create({
      data: {
        actorId: user.id,
        action: ['SLIP_UPLOAD', 'SLIP_CONFIRM', 'ASSESSMENT_RUN', 'LEDGER_APPEND', 'CLOSE_CAPTURE', 'SETTLE_GRADE'][i],
        targetType: i < 2 ? 'SlipUpload' : i < 4 ? 'Assessment' : 'LedgerEntry',
        targetId: `seed-nfl-${String(i + 1).padStart(3, '0')}`,
        requestId: `req-${(1000 + i).toString(16)}`,
        metadataJson: JSON.stringify({ modelVersion: 'REC-V4', provenanceIds: ['CTX-ODDS-1', 'CTX-WX-1'] }),
      },
    });
  }

  // System flags: kill switches off (surfaces healthy).
  await db.systemFlag.createMany({
    data: [
      { key: 'killswitch.extension', value: 'off' },
      { key: 'killswitch.market_intelligence', value: 'off' },
    ],
  });

  const counts = {
    users: await db.user.count(),
    ledgerEntries: await db.ledgerEntry.count(),
    revisions: await db.ledgerRevision.count(),
    closingRefs: await db.closingReference.count(),
    settlements: await db.settlement.count(),
    gateSignals: await db.gateSignal.count(),
    gateAttempts: await db.gateAttempt.count(),
    alerts: await db.alertEvent.count(),
  };
  console.log('Seed complete:', JSON.stringify(counts, null, 2));
  await db.$disconnect();
}

main().catch(async (e) => {
  console.error(e);
  await db.$disconnect();
  process.exit(1);
});
