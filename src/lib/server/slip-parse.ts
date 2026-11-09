/**
 * PropStein — slip extraction.
 *
 * Two extractors feed the SAME confirmation screen:
 *   1. paste-parser-v1 — deterministic regex parser over pasted slip text.
 *   2. vlm-extract-v1  — vision extraction of screenshot fields (server-side
 *                        z-ai-web-dev-sdk). The vision model performs DATA
 *                        EXTRACTION ONLY: it never computes probabilities,
 *                        ratings, or assessments (charter rule 9 — no LLM in
 *                        the decision path; the Hurdle Router is pure code).
 *
 * Either way: OCR confidence below the threshold forces field-by-field manual
 * confirmation, and NOTHING is analyzed before explicit user confirmation.
 */

import ZAI from 'z-ai-web-dev-sdk';

export interface ExtractedSlipFields {
  sportsbook: string | null;
  sport: string | null;
  league: string | null;
  eventLabel: string | null;
  eventId: string | null;
  eventDate: string | null;
  playerId: string | null;
  playerName: string | null;
  market: string | null;
  marketLabel: string | null;
  selection: 'over' | 'under' | null;
  line: number | null;
  americanOdds: number | null;
  wagerAmount: number | null;
}

export interface ExtractionResult {
  provider: string;
  confidence: number; // 0..1 overall
  fieldConfidence: Record<string, number>;
  fields: ExtractedSlipFields;
  needsManualConfirmation: boolean;
}

export const OCR_CONFIDENCE_THRESHOLD = 0.75;

const SPORT_MAP: { re: RegExp; sport: string; league: string }[] = [
  { re: /\bNFL\b/i, sport: 'NFL', league: 'NFL' },
  { re: /\bNBA\b/i, sport: 'NBA', league: 'NBA' },
  { re: /\bUFC\b/i, sport: 'UFC', league: 'UFC' },
  { re: /\bNCAAF?B?\b/i, sport: 'NCAAF', league: 'NCAAF' },
];

const MARKET_MAP: { re: RegExp; market: string; label: string }[] = [
  { re: /receiving\s+yards/i, market: 'player_reception_yds', label: 'Receiving Yards' },
  { re: /rec\s+yds/i, market: 'player_reception_yds', label: 'Receiving Yards' },
  { re: /passing\s+yards/i, market: 'player_passing_yds', label: 'Passing Yards' },
  { re: /pass\s+yds/i, market: 'player_passing_yds', label: 'Passing Yards' },
  { re: /rushing\s+yards/i, market: 'player_rushing_yds', label: 'Rushing Yards' },
  { re: /rush\s+yds/i, market: 'player_rushing_yds', label: 'Rushing Yards' },
  { re: /\bpoints\b/i, market: 'player_points', label: 'Points' },
  { re: /\brebounds\b/i, market: 'player_rebounds', label: 'Rebounds' },
  { re: /\bassists\b/i, market: 'player_assists', label: 'Assists' },
  { re: /prize\s+money/i, market: 'fighter_prize_money', label: 'Prize Money' },
];

function emptyFields(): ExtractedSlipFields {
  return {
    sportsbook: null,
    sport: null,
    league: null,
    eventLabel: null,
    eventId: null,
    eventDate: null,
    playerId: null,
    playerName: null,
    market: null,
    marketLabel: null,
    selection: null,
    line: null,
    americanOdds: null,
    wagerAmount: null,
  };
}

/**
 * Deterministic parser for pasted slip text. Recognizes lines like:
 *   "WR X — Receiving Yards Over 52.5 (-115)"
 *   "NBA Player Points Over 27.5 @ -110"
 */
export function parsePastedSlipText(text: string): ExtractionResult {
  const fields = emptyFields();
  const conf: Record<string, number> = {};

  const sports = SPORT_MAP.filter((s) => s.re.test(text));
  if (sports.length === 1) {
    fields.sport = sports[0].sport;
    fields.league = sports[0].league;
    conf.sport = 0.97;
  } else if (sports.length > 1) {
    conf.sport = 0.4;
  }

  const bookMatch = text.match(/(?:at|book|sportsbook)\s*[:\-]?\s*([A-Z][A-Za-z0-9 &'.-]{2,24})/);
  if (bookMatch) {
    fields.sportsbook = bookMatch[1].trim();
    conf.sportsbook = 0.85;
  }

  const marketHit = MARKET_MAP.find((m) => m.re.test(text));
  if (marketHit) {
    fields.market = marketHit.market;
    fields.marketLabel = marketHit.label;
    conf.market = 0.95;
  }

  const selMatch = text.match(/\b(over|under)\b/i);
  if (selMatch) {
    fields.selection = selMatch[1].toLowerCase() as 'over' | 'under';
    conf.selection = 0.98;
  }

  // Line: a half or whole number right after over/under, e.g. "Over 52.5"
  const lineMatch = text.match(/\b(?:over|under)\s+(\d+(?:\.\d+)?)/i);
  if (lineMatch) {
    fields.line = Number(lineMatch[1]);
    conf.line = 0.95;
  }

  // American odds: (-115) or @ -110 or +150
  const oddsMatch =
    text.match(/\(([-+]?\d{3,})\)/) ??
    text.match(/@\s*([-+]?\d{3,})/) ??
    text.match(/\b([-+]\d{3,})\b/);
  if (oddsMatch) {
    const odds = Number(oddsMatch[1]);
    if (Math.abs(odds) >= 100) {
      fields.americanOdds = odds;
      conf.americanOdds = 0.95;
    }
  }

  // Player name: text before the em-dash or before the market keyword.
  // Name parts are joined by spaces on the SAME line only (newlines belong
  // to other slip fields).
  const nameMatch =
    text.match(/([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]*){0,2})\s*[—–-]\s*(?:player\s+)?(?:[A-Za-z\s]+)?(?:receiving|passing|rushing|points|rebounds|assists|Rec|Rec\.|Pass|Rush)/i) ??
    text.match(/([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]*){0,2})\s+(?:to\s+)?(?:record\s+)?(?:over|under)/i);
  if (nameMatch) {
    fields.playerName = nameMatch[1].trim();
    conf.playerName = 0.9;
    fields.playerId = `player:${fields.playerName.toLowerCase().replace(/[^a-z]+/g, '-')}`;
  }

  // Event: team @ team pattern.
  const eventMatch = text.match(/([A-Z]{2,3}(?:\s+[A-Z][a-z]+)?)\s+(?:@|vs\.?|at)\s+([A-Z]{2,3}(?:\s+[A-Z][a-z]+)?)/);
  if (eventMatch) {
    fields.eventLabel = `${eventMatch[1]} @ ${eventMatch[2]}`;
    fields.eventId = `event:${fields.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
    conf.eventLabel = 0.9;
  }

  const dateMatch = text.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?/i);
  if (dateMatch) {
    fields.eventDate = dateMatch[0];
    conf.eventDate = 0.85;
  }

  const wagerMatch = text.match(/\$\s*([\d,]+(?:\.\d{2})?)/);
  if (wagerMatch) {
    fields.wagerAmount = Number(wagerMatch[1].replace(/,/g, ''));
    conf.wagerAmount = 0.9;
  }

  const scores = Object.values(conf);
  const overall = scores.length === 0 ? 0 : scores.reduce((a, b) => a + b, 0) / 12;
  return {
    provider: 'paste-parser-v1',
    confidence: Number(Math.min(0.98, overall).toFixed(2)),
    fieldConfidence: conf,
    fields,
    needsManualConfirmation: overall < OCR_CONFIDENCE_THRESHOLD || !fields.playerName || !fields.americanOdds || !fields.market,
  };
}

const VLM_PROMPT = `You extract data fields from sportsbook slip screenshots. EXTRACTION ONLY.
Return ONLY a JSON object with these keys (null when not visible):
"sportsbook" (string), "sport" (one of NFL/NBA/UFC or null), "league", "eventLabel" (e.g. "TB @ KC"),
"eventDate" (string as shown), "playerName", "market" (market name as shown, e.g. "Receiving Yards"),
"selection" ("over" or "under"), "line" (number), "americanOdds" (integer, negative for favorite-style juice), "wagerAmount" (number or null).
Do NOT compute or suggest probabilities, ratings, or advice. Do NOT include any commentary. JSON only.`;

/**
 * Vision extraction of slip fields from a screenshot (base64). Returns a
 * low-confidence result on any failure — the confirmation screen then
 * requires manual entry. Never throws into the request path.
 */
export async function extractSlipFromImage(
  base64Image: string,
  mimeType: string,
): Promise<ExtractionResult> {
  try {
    const zai = await ZAI.create();
    const response = await zai.chat.completions.createVision({
      model: 'glm-4.5v',
      messages: [
        {
          role: 'user',
          content: [
            { type: 'text', text: VLM_PROMPT },
            { type: 'image_url', image_url: { url: `data:${mimeType};base64,${base64Image}` } },
          ],
        },
      ],
      thinking: { type: 'disabled' },
    });
    const content = response.choices[0]?.message?.content ?? '';
    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('no JSON in extraction response');
    const raw = JSON.parse(jsonMatch[0]) as Record<string, unknown>;

    const fields = emptyFields();
    const conf: Record<string, number> = {};
    const assign = (key: keyof ExtractedSlipFields, value: unknown, base: number) => {
      if (value === null || value === undefined || value === '') return;
      (fields as unknown as Record<string, unknown>)[key] = typeof value === 'number' ? value : String(value);
      conf[key] = base;
    };
    assign('sportsbook', raw.sportsbook, 0.9);
    assign('sport', raw.sport, 0.92);
    if (fields.sport) assign('league', raw.sport, 0.92);
    assign('eventLabel', raw.eventLabel, 0.88);
    assign('eventDate', raw.eventDate, 0.85);
    assign('playerName', raw.playerName, 0.9);
    assign('market', raw.market, 0.9);
    assign('selection', String(raw.selection ?? '').toLowerCase() === 'under' ? 'under' : raw.selection ? 'over' : null, 0.95);
    if (raw.line !== undefined && raw.line !== null && Number.isFinite(Number(raw.line))) {
      fields.line = Number(raw.line);
      conf.line = 0.92;
    }
    if (raw.americanOdds !== undefined && raw.americanOdds !== null && Number.isFinite(Number(raw.americanOdds))) {
      const odds = Math.round(Number(raw.americanOdds));
      if (Math.abs(odds) >= 100) {
        fields.americanOdds = odds;
        conf.americanOdds = 0.93;
      }
    }
    if (raw.wagerAmount !== undefined && raw.wagerAmount !== null && Number.isFinite(Number(raw.wagerAmount))) {
      fields.wagerAmount = Number(raw.wagerAmount);
      conf.wagerAmount = 0.88;
    }
    if (fields.sport && fields.playerName) {
      fields.playerId = `player:${fields.playerName.toLowerCase().replace(/[^a-z]+/g, '-')}`;
      conf.playerId = 0.9;
    }
    if (fields.eventLabel) {
      fields.eventId = `event:${fields.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
    }

    const scores = Object.values(conf);
    const overall = scores.length === 0 ? 0 : scores.reduce((a, b) => a + b, 0) / 12;
    return {
      provider: 'vlm-extract-v1',
      confidence: Number(Math.min(0.97, overall).toFixed(2)),
      fieldConfidence: conf,
      fields,
      needsManualConfirmation: overall < OCR_CONFIDENCE_THRESHOLD || !fields.playerName || !fields.americanOdds || !fields.market,
    };
  } catch {
    return {
      provider: 'vlm-extract-v1',
      confidence: 0,
      fieldConfidence: {},
      fields: emptyFields(),
      needsManualConfirmation: true,
    };
  }
}
