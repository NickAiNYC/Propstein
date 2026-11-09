/**
 * PropStein — in-app specification documents.
 *
 * These render inside the product (Docs view) and are therefore part of the
 * lint-scanned copy surface: they are written without the prohibited
 * vocabulary. The full prohibited-vocabulary enumeration lives in the
 * exported specification PDF (compliance appendix), not in product UI.
 */

export interface DocSection {
  id: string;
  title: string;
  markdown: string;
}

const productSpec = `
## Purpose

PropStein is an evidence-first research and record-keeping product. It helps a
user understand **price, uncertainty, provenance, and their own historical
record**. It is not a betting recommendation product: it contains no picks, no
sizing guidance, no urgency language, and no actionable-signal claims before
preregistered evidence exists.

## Core loop

1. Upload or enter a slip.
2. Confirm parsed selections (explicit confirmation, always).
3. Compare price/line to available market and model distribution.
4. Save an immutable ledger entry.
5. Capture closing reference when available.
6. Settle and grade.
7. Show calibrated record and uncertainty.

## Information architecture

| Surface | Purpose |
|---|---|
| Slip | Upload / paste / manual entry, confirmation, price assessment, save to ledger |
| Ledger | Append-only record list, entry detail, Evidence DNA, revisions, close, settle, corrections |
| Record | Luck Meter: descriptive statistics, exclusions, verdict ladder |
| Alerts | Opt-in factual tracked-entry updates with snapshot time and source |
| Gate Monitor | Preregistered commercialization gate per sport; compliance approval; default deny |
| Docs | This specification, copy compliance, launch checklist |

## User flows

### Flow A — screenshot slip
Upload image → vision extraction (fields only, confidence per field) → editable
confirmation screen (below-threshold fields highlighted) → confirm → price
assessment → save immutable ledger entry. Screenshots retained only on opt-in;
deletion available. No sportsbook credentials, cookies, balances, or account
data are ever requested or stored; nothing is submitted anywhere.

### Flow B — pasted text
Paste slip text → deterministic parser → same confirmation and assessment path.

### Flow C — manual entry
Type fields directly → same confirmation and assessment path, marked
manual_entry in the ledger.

### Flow D — grading loop
Pending entry → capture closing reference (independent provider, quality
checked) → settle and grade → Luck Meter updates. Missing/stale/conflicting
closes produce UNEVALUABLE with reason codes, never zeros.

## Rating-card states

| State | Trigger | Copy |
|---|---|---|
| PRICE ABOVE MARKET HURDLE | fresh licensed comparison; delta below −0.25 pp | "Entered price is X pp better than the comparison snapshot" |
| PRICE AT MARKET HURDLE | delta within ±0.25 pp | "at comparison within ±0.25 pp" |
| PRICE BELOW MARKET HURDLE | delta above +0.25 pp | "Entered price is X pp worse than the comparison snapshot" |
| INSUFFICIENT MARKET DATA | no licensed comparison | fail-closed note |
| STALE QUOTE | comparison age > 300 s | snapshot retained, comparison not used |
| NO MODEL COVERAGE | model mode; no calibrated coverage | "No calibrated coverage" |
| UNVERIFIED CONTEXT | spread/total/weather observed-at missing or after pricing cutoff | fail-closed note |
| MODEL UNAVAILABLE | model surface outage | fail-closed note |
| SETTLED | settlement recorded | recorded outcome |

Error and empty states: loading, unconfirmed extraction, entitlement failure,
kill switch active, service unavailable — each fails closed with explicit copy.

## Alert rules

- Opt-in per alert type; daily cap of 3 push notifications per user.
- Non-urgent updates are batched.
- Every alert displays snapshot time and data source, and links to the
  immutable ledger entry.
- If freshness cannot be verified: send a STALE QUOTE state or suppress.
- Alerts are factual and past-tense; they contain no entry, exit, sizing, or
  timing instructions, and no model-derived content before a sport gate passes.

## Copy library

Required vocabulary: price assessment · break-even probability · market
comparison · snapshot time · data freshness · model coverage · uncertainty
interval · no calibrated coverage · insufficient evidence · descriptive only ·
recorded for review · closing reference unavailable · this is not a betting
recommendation.

The runtime copy registry is machine-checked by the copy-compliance linter;
the Docs view shows the live report.

## Free / Pro boundary (without selling picks)

Free: slip upload and manual entry, hurdle router price assessments, the
immutable ledger, the Luck Meter, and standard alerts.
Pro: additional licensed comparison feeds by sport, closing-reference capture
for additional leagues, longer retention windows, and data export.

Neither tier ever receives picks, signal strengths, sizing guidance, or
actionable-signal language; entitlement gates only data surfaces, and
verification is server-side only.
`;

const dbSchema = `
## Models (reference deployment: SQLite via Prisma; production: PostgreSQL with identical shape)

**User** — pseudonymous id, plan, retention defaults. No credentials, no
sportsbook account linkage.

**SessionToken** — jti, scopes, expiry, revocation timestamp. Redis-backed
revocation in production.

**SlipUpload** — source type (manual_entry | screenshot_upload |
extension_observation), OCR provider and confidence, extracted fields JSON,
retention flag, deletion timestamp, confirmation timestamp.

**Assessment** — canonical HurdleInput JSON, snapshot hash, result JSON,
scenario, link to slip upload and ledger entry.

**LedgerEntry** — the immutable core: ids, sport, event, game cluster, player,
market, selection, line, entered two-way quote, implied and break-even
probabilities, book, captured-at, snapshot hash, model version and coverage,
model probability and uncertainty, price assessment, provenance JSON, entry
hash, duplicate/correlation flags. No update path exists anywhere in the API.

**LedgerRevision** — append-only revisions: number, reason code and text,
actor, changed fields, prior hash, new hash, timestamp.

**MarketSnapshot** — comparison quotes with provider, two-way odds, captured
time, raw capture reference, snapshot hash.

**ClosingReference** — provider, captured time, two-way close, implied and
fair probabilities, quality (fresh | stale | missing | conflicting), second
source, independence flag, integrity hash.

**Settlement** — status (pending | settled | void | canceled | push | dnp),
result, reason code, actual statistic, source, settled timestamp.

**AlertEvent / AlertPreference** — factual alerts with snapshot time, source,
ledger linkage, delivery state, suppression reason; per-type opt-in.

**Entitlement** — surface, scope, status, source, expiry. Server-side
verification only; no client-side gating.

**AuditEvent** — actor, action, target, request id, metadata. Structured JSON
logging with request id, pseudonym, model version, provenance ids.

**GateSignal / GateAttempt / ComplianceApproval** — preregistered gate
evidence per sport: signals with cluster ids and reason codes, attempt results
with seed and bounds, compliance approval records.

**SystemFlag** — kill switches (extension, market intelligence) and model
outage flags.

## Append-only integrity

Entry hash = SHA-256 over the canonical JSON of the immutable core. Genesis
revision binds the entry hash. Every correction appends a revision whose new
hash chains from the prior hash. Verification recomputes the chain and reports
any mismatch as an integrity failure. Settlements and closing references are
child records, never mutations.
`;

const apiSpec = `
All endpoints return JSON envelopes: \`{ ok: true, ... }\` or
\`{ ok: false, code, detail }\`. Fail-closed errors are explicit states, never
silences. Rate limits: sliding window per IP and route (Redis in production).

| Method | Path | Purpose |
|---|---|---|
| POST | /api/slips/upload | Screenshot (multipart) or pasted text (JSON) → extraction with confidence; never analyzes |
| POST | /api/slips/confirm | Explicit confirmation → assessment pipeline → persisted Assessment |
| GET | /api/assessments/{id} | Assessment bundle (rating card + Evidence DNA inputs) |
| POST | /api/ledger/entries | Save immutable ledger entry from a confirmed assessment |
| GET | /api/ledger | List entries (filters: sport, settlement status) |
| GET | /api/ledger/{id} | Entry detail: core, provenance, revisions, close, settlement, grade, integrity |
| POST | /api/ledger/{id}/close | Capture closing reference (quality states; unevaluable reasons) |
| POST | /api/ledger/{id}/settle | Settle and grade (win/loss/push/void/canceled/dnp with reason codes) |
| POST | /api/ledger/{id}/correction | Append a revision (reason + hashes; forbidden fields rejected) |
| GET | /api/records/luck-meter | Luck Meter report: verdict ladder, exclusions, intervals, slices |
| POST | /api/alerts/preferences | Opt-in by alert type |
| GET | /api/alerts/preferences | Current preferences |
| GET | /api/alerts | Alert feed (snapshot time + source + ledger link) |
| POST | /api/alerts/evaluate | Run the alert evaluation worker (preferences, mute, daily cap, freshness) |
| POST | /api/extension/session | Issue read-only extension session (fixed scopes; kill switch respected) |
| POST | /api/extension/session/revoke | Revoke by token or jti |
| GET | /api/extension/health | Kill-switch state, adapter versions, read-only posture |
| GET | /api/gates | Gate monitor view per sport |
| POST | /api/gates/recompute | Deterministic recompute from stored signals (fixed seed) |
| GET | /api/copy-compliance | Live copy lint report over the product copy registry |
| GET | /api/me | Session pseudonym and plan |

Notable contracts:

- **POST /api/slips/confirm** rejects \`confirm !== true\` with
  CONFIRMATION_REQUIRED: unconfirmed extractions are never analyzed.
- **POST /api/ledger/entries** refuses an assessment twice (409
  ALREADY_SAVED) and refuses model-outage assessments (503 fail closed).
- **POST /api/ledger/{id}/correction** rejects empty changes, missing
  reasons, and immutable fields (ledgerId, entryHash, createdAtUtc,
  snapshotHash).
- **POST /api/extension/session** issues only
  market.observe.readonly + ledger.append scopes; placement/preparation/
  credential scopes are not issuable; a kill switch refusal is 503 with an
  explicit state.
- There is deliberately **no** PUT or PATCH route for ledger entries, and no
  bet placement, preparation, or submission route anywhere in the surface.
`;

const launchChecklist = `
## Security review

- [x] Server-side entitlement verification on every gated surface (no
      client-side gating).
- [x] Short-lived scoped session tokens: HMAC-SHA256 with sub, plan, iat,
      exp, jti.
- [x] jti revocation store (Redis in production) exercised on web and
      extension sessions.
- [x] Redis-backed sliding-window rate limits on upload/confirm/save routes.
- [x] Kill switches for extension and market-intelligence surfaces.
- [x] No secrets in client bundles (SDK use is server-only).
- [x] Strict CORS allowlist in production network configuration.
- [x] No sportsbook credential, cookie, balance, or account retention.

## Privacy review

- [x] Pseudonymous identities only.
- [x] Screenshot retention is opt-in and deletable; deletion tombstones the
      raw capture reference.
- [x] Data-export controls (ledger JSON export from the API).
- [x] Structured audit logging with request ids.

## Data-rights review

- [x] Comparison quotes only where licensed; unlicensed sports fail closed to
      INSUFFICIENT MARKET DATA.
- [x] Closing references from providers independent of the model input feed
      (namespace disjoint by construction).
- [x] Raw provider captures retained with hashes for provenance.

## Responsible-gambling review

- [x] Persistent "this is not a betting recommendation" banner.
- [x] 21+ and problem-gambling helpline in the footer.
- [x] No urgency language anywhere (machine-checked by the copy linter).
- [x] No sizing, allocation, or timing guidance of any kind; no instructions
      to enter, exit, or modify positions.
- [x] Product copy emphasizes record-keeping, not wagering speed.

## App-store / extension-store compliance

- [x] Extension is read-only: no bet placement, preparation, or submission
      capability; no credential collection; no anti-bot bypass.
- [x] Opt-in per-origin permissions; remote kill switch; versioned adapters
      with selector-drift monitoring.
- [x] NO MODEL COVERAGE shown for real books until a licensed
      possession-level feed and calibration corpus exist.

## Statistical gate review

- [x] Preregistered parameters enforced in code: N=600, +1.0 pp mean price
      CLV, one-sided alpha 0.0125, 10,000 game-clustered bootstrap
      replicates, fixed seed 20261024, max two attempts per sport.
- [x] Interim look at N=300 is descriptive only.
- [x] Cross-sport pooling raises CROSS_SPORT_POOLING_FORBIDDEN.
- [x] Insufficient cluster representation yields INCONCLUSIVE.
- [x] Failed second attempt retires the sport's commercial
      actionable-signal flag.
- [x] Model-version changes restart confirmatory accumulation
      (PRE_REGISTRATION reason code).

## Compliance approval record

Commercial actionable-signal launch requires BOTH a recorded gate PASS and an
explicit compliance approval record per sport. Default is deny. Current state
(NFL / NBA / UFC): all denied or pending — see the Gate Monitor view.
`;

export const DOCS: DocSection[] = [
  { id: 'product-spec', title: 'Product spec', markdown: productSpec },
  { id: 'db-schema', title: 'Database schema', markdown: dbSchema },
  { id: 'api-spec', title: 'API specification', markdown: apiSpec },
  { id: 'launch-checklist', title: 'Launch checklist', markdown: launchChecklist },
];
