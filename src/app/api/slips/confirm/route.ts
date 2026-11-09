/**
 * POST /api/slips/confirm
 *
 * Body: {
 *   slipUploadId?: string,       // for upload flows
 *   confirm: true,               // REQUIRED — never analyze unconfirmed data
 *   retainScreenshot?: boolean,
 *   wagerAmount?: number | null,  // user record only
 *   scenario?: string,            // demo fail-closed injection (reference build)
 *   fields: { sport, league, eventLabel, playerName, market, marketLabel,
 *             selection, line, enteredAmericanOdds, enteredCounterpartOdds,
 *             book, capturedAtUtc }
 * }
 *
 * Runs the assessment pipeline (provenance -> entitlement-gated comparison ->
 * model coverage -> Hurdle Router) and persists an Assessment. The ledger
 * entry is created only by an explicit POST /api/ledger/entries.
 */

import { db } from '@/lib/db';
import { getSessionUser, audit, newRequestId, hasEntitlement } from '@/lib/server/session';
import { runAssessment } from '@/lib/server/assessment-service';
import { fail, ok, rateLimited, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

interface ConfirmBody {
  slipUploadId?: string | null;
  confirm?: boolean;
  retainScreenshot?: boolean;
  wagerAmount?: number | null;
  scenario?: string;
  mode?: 'market' | 'model';
  fields?: Record<string, unknown>;
}

const VALID_SCENARIOS = ['none', 'no_market_data', 'entitlement_failure', 'stale_quote', 'unverified_context', 'model_outage'];

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();

  const rl = rateLimited(req, 'slips:confirm', 20, 60);
  if (rl.limited) {
    return fail(429, 'RATE_LIMITED', 'Too many confirmation attempts. Try again shortly.', { retryAfterSeconds: rl.retryAfterSeconds });
  }

  const body = await readJson<ConfirmBody>(req);
  if (!body) return fail(400, 'BAD_JSON', 'Expected a JSON body.');

  // The explicit confirmation gate — analysis of unconfirmed data is impossible.
  if (body.confirm !== true) {
    return fail(400, 'CONFIRMATION_REQUIRED', 'Extractions must be explicitly confirmed before analysis. Send confirm: true.');
  }
  const f = body.fields ?? {};
  const sport = String(f.sport ?? '').toUpperCase();
  const playerName = String(f.playerName ?? '').trim();
  const market = String(f.market ?? '').trim();
  const selection = String(f.selection ?? '').toLowerCase() === 'under' ? 'under' : 'over';
  const line = Number(f.line);
  const odds = Number(f.enteredAmericanOdds);
  const counterpart = Number(f.enteredCounterpartOdds ?? -110);

  const problems: string[] = [];
  if (!['NFL', 'NBA', 'UFC'].includes(sport)) problems.push('sport (NFL/NBA/UFC)');
  if (!playerName) problems.push('playerName');
  if (!market) problems.push('market');
  if (!Number.isFinite(line) || line <= 0) problems.push('line');
  if (!Number.isFinite(odds) || Math.abs(odds) < 100) problems.push('enteredAmericanOdds');
  if (!Number.isFinite(counterpart) || Math.abs(counterpart) < 100) problems.push('enteredCounterpartOdds');
  if (problems.length > 0) {
    return fail(400, 'FIELDS_INVALID', `Missing or invalid fields: ${problems.join(', ')}.`);
  }

  const eventLabel = String(f.eventLabel ?? 'Event TBD').trim() || 'Event TBD';
  const eventId =
    typeof f.eventId === 'string' && f.eventId
      ? f.eventId
      : `event:${eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  const playerId =
    typeof f.playerId === 'string' && f.playerId
      ? f.playerId
      : `player:${playerName.toLowerCase().replace(/[^a-z]+/g, '-')}`;
  const capturedAtUtc =
    typeof f.capturedAtUtc === 'string' && !Number.isNaN(Date.parse(f.capturedAtUtc))
      ? new Date(f.capturedAtUtc).toISOString().replace(/\.\d{3}Z$/, 'Z')
      : new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const book = String(f.book ?? 'user_entered').trim() || 'user_entered';
  const scenario = VALID_SCENARIOS.includes(body.scenario ?? 'none') ? (body.scenario ?? 'none') : 'none';
  const mode = body.mode === 'model' ? 'model' : 'market';

  // Server-side entitlement verification for the comparison surface.
  const entitled = await hasEntitlement(user.id, 'market_comparison', sport);

  const bundle = await runAssessment(
    user.id,
    {
      sport,
      league: String(f.league ?? sport).toUpperCase(),
      eventId,
      eventLabel,
      eventStartsAtUtc: capturedAtUtc,
      playerId,
      playerName,
      market,
      marketLabel: String(f.marketLabel ?? market),
      selection,
      line,
      enteredAmericanOdds: Math.round(odds),
      enteredCounterpartOdds: Math.round(counterpart),
      book,
      capturedAtUtc,
      wagerAmount: body.wagerAmount ?? null,
    },
    scenario as never,
    entitled,
    mode,
  );

  // Bind the assessment to the slip upload, mark confirmed.
  if (body.slipUploadId) {
    await db.slipUpload.update({
      where: { id: body.slipUploadId },
      data: { confirmedAtUtc: new Date(), retained: body.retainScreenshot ?? false },
    });
    await db.assessment.update({ where: { id: bundle.assessmentId }, data: { slipUploadId: body.slipUploadId } });
  }

  await audit(requestId, user.id, 'SLIP_CONFIRM', 'Assessment', bundle.assessmentId, {
    scenario,
    assessment: bundle.hurdle.assessment,
    modelVersion: bundle.model.modelVersion,
    entitlementOk: entitled,
  });

  return ok({ bundle });
}
