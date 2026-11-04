/**
 * PropStein — central copy registry.
 *
 * Every user-facing product string lives here (or in lint-scanned component
 * literals) so the copy-compliance test can prove the language standards.
 * Required vocabulary: "price assessment", "break-even probability",
 * "market comparison", "snapshot time", "data freshness", "model coverage",
 * "uncertainty interval", "no calibrated coverage", "insufficient evidence",
 * "descriptive only", "recorded for review", "closing reference unavailable",
 * "this is not a betting recommendation".
 */

export const COPY = {
  brand: 'PropStein',
  product: 'Evidence-First Research Terminal',
  banner:
    'This is not a betting recommendation. PropStein records prices, uncertainty, provenance, and your own record — nothing else.',

  nav: {
    slip: 'Slip',
    ledger: 'Ledger',
    record: 'Record',
    alerts: 'Alerts',
    gates: 'Gate Monitor',
    docs: 'Docs',
  },

  slip: {
    title: 'Record a proposed price',
    intro:
      'Upload a screenshot, paste slip text, or enter fields manually. Extraction always requires your explicit confirmation before any assessment runs.',
    uploadTab: 'Screenshot',
    pasteTab: 'Paste slip text',
    manualTab: 'Manual entry',
    uploadHint: 'PNG or JPG. Screenshots are stored only if you opt in; deletion is available from the entry.',
    pasteHint: 'Paste the slip text exactly as shown by the sportsbook.',
    confirmTitle: 'Confirm the extracted selections',
    confirmIntro:
      'Every field is editable. Nothing is analyzed until you confirm. Low-confidence fields are highlighted for manual review.',
    confirmCheckbox: 'I confirm these fields match the slip I am recording.',
    confirmButton: 'Confirm and run price assessment',
    retainScreenshot: 'Retain the screenshot with the ledger record (optional; deletable at any time)',
    wagerOptional: 'Wager amount (optional, for your record only — never used in assessments)',
    unconfirmedWarning: 'Unconfirmed extraction. Analysis is blocked until you confirm the fields.',
    saveButton: 'Save immutable ledger entry',
    savedToast: 'Ledger entry saved. It is append-only and can no longer be edited — only corrected via revision.',
  },

  ratingCard: {
    title: 'Price assessment',
    enteredPrice: 'Entered price',
    breakEven: 'Break-even probability',
    marketComparison: 'Market comparison',
    comparisonImplied: 'Comparison implied probability',
    delta: 'Price difference',
    deltaBetter: (pp: string) => `Entered price is ${pp} percentage points better than the comparison snapshot`,
    deltaWorse: (pp: string) => `Entered price is ${pp} percentage points worse than the comparison snapshot`,
    deltaAt: 'Entered price is at the comparison snapshot within the preregistered band',
    snapshotTime: 'Snapshot time',
    dataFreshness: 'Data freshness',
    modelCoverage: 'Model coverage',
    uncertaintyInterval: 'Uncertainty interval',
    modelVersion: 'Model version',
    noCalibratedCoverage: 'No calibrated coverage',
    modelNoneNote: 'No calibrated model coverage exists for this market. This is not an instruction to take or decline the price.',
    provenance: 'Provenance',
    recordedForReview: 'Recorded for review',
    notBettingRecommendation: 'This is not a betting recommendation',
    closingUnavailable: 'Closing reference unavailable',
    insufficientEvidence: 'Insufficient evidence',
    descriptiveOnly: 'Descriptive only',
    failClosed: 'Assessment fails closed when provenance, freshness, entitlement, or coverage is missing.',
    marketNotModel: 'This is a market comparison, not a model assessment.',
  },

  luckMeter: {
    title: 'Your record, reported honestly',
    evaluableEntries: 'Evaluable entries',
    excludedEntries: 'Excluded entries (retained with reason codes)',
    meanClv: 'Mean price CLV',
    shrunkClv: 'Shrunk CLV estimate',
    confidenceInterval: 'Confidence interval (95%, game-clustered bootstrap)',
    beatClose: 'Entries beating close',
    calibration: 'Model calibration (where calibrated model probabilities exist)',
    brier: 'Brier score',
    exclusionsHistogram: 'Reason-code histogram',
    minSampleWarning: 'Not enough evaluable entries to draw a conclusion.',
    verdictChip: 'Record verdict',
    note: 'Descriptive only. This record does not authorize any commercial actionable-signal claim.',
    clvNote:
      'CLV = de-vigged closing fair probability − de-vigged entry fair probability, in percentage points. Positive means the recorded price was superior to the closing reference. Excluded records are never counted as losses or zeros.',
  },

  alerts: {
    title: 'Tracked-entry alerts',
    intro:
      'Opt-in, low-volume, factual updates on entries you saved. Alerts carry snapshot time and source, link to the ledger entry, and never contain entry, exit, sizing, or timing instructions.',
    dailyCap: 'Daily cap: at most 3 push notifications per user; non-urgent updates are batched.',
    preferences: 'Alert preferences',
    feed: 'Alert feed',
    muteEntry: 'Mute this entry',
    checkNow: 'Evaluate updates on saved entries',
    staleOrSuppress: 'If freshness cannot be verified, a STALE QUOTE state is sent or the alert is suppressed.',
    types: {
      quote_changed: 'Saved quote changed',
      quote_aged: 'Saved quote aged',
      player_status: 'Player status changed',
      market_suspended: 'Market suspended',
      closing_available: 'Closing reference available',
      entry_settled: 'Saved entry settled',
      entry_unevaluable: 'Saved entry unevaluable',
    } as Record<string, string>,
  },

  gates: {
    title: 'Preregistered gate monitor',
    intro:
      'One evaluation per sport. A commercial actionable-signal surface may launch for a sport only after the preregistered gate passes AND an explicit compliance approval record exists. Default is deny. Cross-sport pooling is forbidden.',
    progress: 'Gate progress',
    attempts: 'Attempt history',
    compliance: 'Compliance approval',
    commercialFlag: 'Commercial actionable-signal flag',
    recompute: 'Recompute from stored signals (deterministic, fixed seed)',
    params: 'Preregistered parameters',
    interimNote: 'Interim look at N=300 is descriptive only and never a verdict.',
  },

  ledger: {
    title: 'Immutable ledger',
    intro:
      'Append-only records. Corrections create a new revision with a reason and integrity hash; the original is never overwritten. Pushes, voids, cancellations, and DNPs are retained with reason codes and excluded from CLV.',
    revisions: 'Revision history',
    captureClose: 'Capture closing reference',
    settleEntry: 'Settle and grade',
    requestCorrection: 'Request correction (creates a revision)',
    correctionReason: 'Reason for correction (required)',
    duplicateFlag: 'Duplicate of an existing entry — retained, excluded from confirmatory counts.',
    correlatedFlag: 'Correlated entry — retained, flagged; cluster dependence is preserved in statistics.',
    chainVerify: 'Integrity check: hash chain verified.',
    chainBroken: 'Integrity check failed: the record no longer matches its hash chain.',
    empty: 'No ledger entries yet. Record a proposed price to start your append-only record.',
  },

  evidenceDna: {
    title: 'Evidence DNA',
    inputs: 'Inputs',
    provenance: 'Provenance',
    model: 'Model',
    market: 'Market',
    record: 'Record',
    whatExisted: 'What information existed',
    whenObserved: 'When each input was observed',
    whatMissing: 'What was missing',
    whatWouldUnavail: 'What would make the assessment unavailable',
    beforeCutoff: 'Context known before the pricing cutoff',
    closingIndependent: 'Closing reference independent and fresh',
    hardRule:
      'If spread, total, or weather lacks an observed-at timestamp before the pricing cutoff, the assessment becomes UNVERIFIED CONTEXT.',
  },

  empty: {
    record: 'No graded entries yet.',
    alerts: 'No alerts yet. Alerts appear for entries you saved and opted into.',
    assessment: 'No assessment yet. Confirm an extraction or enter a slip to run the Hurdle Router.',
  },

  errors: {
    generic: 'The request could not be completed. Nothing was invented to fill the gap.',
    entitlement: 'Server-side entitlement verification did not grant this data surface.',
    killSwitch: 'This surface is disabled by a kill switch. The state is explicit, not silent.',
    rateLimit: 'Rate limit reached. Try again shortly.',
  },

  footer: {
    disclaimer:
      'PropStein is a research and record-keeping product. It does not place, prepare, or automate wagers, and it makes no actionable-signal claims before preregistered evidence exists.',
    responsible: '21+. If gambling is causing problems for you or someone close to you, help is available: call 1-800-GAMBLER.',
    language: 'This is not a betting recommendation.',
  },
} as const;
