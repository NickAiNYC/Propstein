/**
 * NFL Sport Adapter — first adapter in the PropWire sport layer.
 *
 * Every hook below is a VERBATIM extraction of the pre-adapter viewer logic
 * (HEAD bdc229f). NFL behavior is byte-identical to the pre-adapter build,
 * proven by test/nfl-parity.snapshot.mjs golden snapshots.
 *
 * Adapter contract (see registry.js): id, label, periodNoun, markets,
 * defaultMarket, slates — plus the optional hooks used by viewer/app.js.
 * Hooks receive `ctx`, a helpers bundle bound once by viewer/app.js via
 * bindContext() (the adapter is a separate file and has no closure access).
 */
(() => {
  'use strict';

  let ctx = {};
  const num = (...args) => ctx.num(...args);
  const pct = (...args) => ctx.pct(...args);
  const esc = (...args) => ctx.esc(...args);

  const NFL_ADAPTER = {
    id: 'nfl',
    label: 'NFL',
    /** Period noun for slate copy: "Week 7", "Game Day", "Event" in other sports. */
    periodNoun: 'Week',

    /** Allow viewer/app.js to lend its helper functions to hook implementations. */
    bindContext(helpers) {
      ctx = helpers || {};
    },

    // ── Distribution model constants (compound NegBin/Gamma, NFL-calibrated) ─
    model: {
      alpha: 0.1097,
      k: 1.555
    },

    // ── Slate registry (verbatim from app.js SLATES, pre-adapter) ───────────
    slates: {
      '2026_w7': {
        season: 2026,
        week: 7,
        shortLabel: 'W7 Live',
        state: 'Upcoming slate · Oct 22–26',
        slate: 'slate_2026_w7.json',
        games: 'games_2026_w7.json',
        picks: 'current_picks_w7.json',
        injuries: 'injuries_2026_w7.json',
        odds: 'live_odds_feed.json',
        snapshots: 'snapshots_2026_w7.json',
        historical: false
      },
      '2026_w1': {
        season: 2026,
        week: 1,
        shortLabel: 'W1 Audit',
        state: 'Historical audit · Sept 10–14',
        slate: 'slate_2026_w1.json',
        games: 'games_2026_w1.json',
        picks: 'current_picks_w1.json',
        injuries: null,
        odds: null,
        snapshots: 'snapshots_2026_w1.json',
        historical: true
      }
    },

    // ── Markets ─────────────────────────────────────────────────────────────
    // Field hooks (fair/projection/actual/settled*) replicate the exact
    // pre-adapter branches, INCLUDING historical quirks that other sports
    // must not inherit:
    //   · anytime_td "actual" reads receptions (legacy settled-row quirk)
    //   · anytime_td naturalInsight unit is 'yds' and ceiling 75.0 (quirk)
    markets: {
      receiving_yards: {
        id: 'receiving_yards',
        chipLabel: 'Yards',
        unit: 'yds',
        bulletUnit: 'y',
        naturalInsightUnit: 'yds',
        settledUnit: 'yds',
        breakerUnit: 'yds',
        isYards: true,
        strongCeiling: 75.0,
        breaker: { driftHurdle: 5.0, beneficiaryMax: 8.5 },
        fair: (row) => num(row.fair_line_yards),
        projection: (row) => num(row.proj_yards),
        actual: (row) => num(row.receiving_yards),
        settledActual: (row) => num(row.receiving_yards),
        settledLine: (row) => num(row.fair_line_yards),
        fairProbText: () => 'P(over fair) 50.0%',
        dist: (row) => {
          const fair = num(row.fair_line_yards || row.proj_yards || 40.0);
          const proj = num(row.proj_yards || 40.0);
          const low = Math.max(0, Math.round(fair * 0.58));
          const high = Math.round(proj * 1.48);
          return { low, high, fair, proj, isRec: false };
        },
        prediction: (row) => {
          const fair = num(row.fair_line_yards || row.proj_yards || 40.0);
          const proj = num(row.proj_yards || 40.0);
          const low = Math.max(0, Math.round(fair * 0.58));
          const high = Math.round(proj * 1.48);
          return `80% Range: ${low} – ${high} yds`;
        }
      },
      receptions: {
        id: 'receptions',
        chipLabel: 'Rec',
        unit: 'rec',
        bulletUnit: 'rec',
        naturalInsightUnit: 'rec',
        settledUnit: 'rec',
        breakerUnit: 'rec',
        isYards: false,
        strongCeiling: 5.5,
        breaker: { driftHurdle: 1.0, beneficiaryMax: 2.0 },
        fair: (row) => num(row.fair_line_rec),
        projection: (row) => num(row.proj_rec),
        actual: (row) => num(row.receptions),
        settledActual: (row) => num(row.receptions),
        settledLine: (row) => num(row.fair_line_rec),
        fairProbText: (row) => `P(over fair) ${pct(row.p_rec_at_fair_line)}`,
        dist: (row) => {
          const mu = num(row.mu_rec || row.proj_rec || 3.0);
          const low = Math.max(0, Math.floor(mu * 0.55));
          const high = Math.max(low + 1, Math.ceil(mu * 1.55 + 0.5));
          const fair = num(row.fair_line_rec);
          const proj = num(row.proj_rec);
          return { low, high, fair, proj, isRec: true };
        },
        prediction: (row) => {
          const mu = num(row.mu_rec || row.proj_rec || 3.0);
          const low = Math.max(0, Math.floor(mu * 0.55));
          const high = Math.max(low + 1, Math.ceil(mu * 1.55 + 0.5));
          return `80% Range: ${low} – ${high} rec`;
        }
      },
      anytime_td: {
        id: 'anytime_td',
        chipLabel: 'TD',
        unit: 'yds',
        bulletUnit: 'y',
        naturalInsightUnit: 'yds',
        settledUnit: 'rec',
        breakerUnit: 'rec',
        isYards: false,
        strongCeiling: 75.0,
        breaker: { driftHurdle: 1.0, beneficiaryMax: 2.0 },
        fair: (row) => Math.round(num(row.f_tgt_share || row.target_share, 0.15) * 2.2 * 10) / 10,
        projection: (row) => Math.round(num(row.f_tgt_share || row.target_share, 0.15) * 2.4 * 10) / 10,
        actual: (row) => num(row.receptions),
        settledActual: (row) => num(row.receptions),
        settledLine: (row) => num(row.fair_line_rec),
        fairProbText: () => 'Poisson Red Zone Model (Holdout)',
        dist: (row) => {
          const share = num(row.f_tgt_share || row.target_share, 0.15);
          const prob = Math.min(0.65, Math.max(0.12, share * 1.8));
          return { low: 0, high: 1, fair: prob, proj: prob, isTd: true, prob };
        },
        prediction: (row) => {
          const share = num(row.f_tgt_share || row.target_share, 0.15);
          const prob = Math.min(0.65, Math.max(0.12, share * 1.8));
          return `Implied P(TD): ${pct(prob, 0)}`;
        }
      }
    },

    defaultMarket: 'receiving_yards',
    marketOrder: ['receiving_yards', 'receptions', 'anytime_td'],

    // ── Positions / roles ───────────────────────────────────────────────────
    positions: ['WR', 'TE', 'RB'],

    /** Verbatim roleLabel() from pre-adapter app.js. */
    roleLabel(row) {
      const share = num(row.f_tgt_share || row.target_share);
      const targets = num(row.c_targets);
      if (share >= 0.22 || targets >= 6.5) return `Featured ${row.position}`;
      if (share >= 0.14 || targets >= 4.5) return `Starting ${row.position}`;
      return `Rotational ${row.position}`;
    },

    /** Verbatim keyDriverTag() body from pre-adapter app.js (lines 214-247). */
    driverTag(row, beneficiary, market) {
      const { SVG_ICONS } = ctx;
      if (market === 'anytime_td') {
        const rzShare = Math.min(0.48, Math.max(0.12, (num(row.f_tgt_share || row.target_share) * 1.5)));
        const ezTargets = (num(row.c_targets, 4.0) * 0.18).toFixed(1);
        if (rzShare >= 0.28) {
          return `<span class="driver-badge surge" title="Red Zone Target Share">${SVG_ICONS.target} RZ Share (${pct(rzShare, 0)})</span>`;
        }
        return `<span class="driver-badge alpha" title="End Zone Targets">${SVG_ICONS.target} EZ Targets (${ezTargets}/gm)</span>`;
      }
      if (beneficiary) {
        return `<span class="driver-badge surge" title="Role surge catalyst: ${esc(beneficiary.catalyst_injury || 'Vacancy')}">${SVG_ICONS.surge} Surge (+${num(beneficiary.added_targets).toFixed(1)} tgt)</span>`;
      }
      const share = num(row.f_tgt_share || row.target_share);
      const ayShare = num(row.f_ay_share || row.air_yards_share);
      const adot = num(row.f_adot || row.adot);
      const tgts = num(row.c_targets);

      if (share >= 0.25) {
        return `<span class="driver-badge alpha" title="Target share alpha: ${pct(share)}">${SVG_ICONS.alpha} Alpha (${pct(share, 0)})</span>`;
      }
      if (ayShare >= 0.35) {
        return `<span class="driver-badge air" title="Air yards share: ${pct(ayShare)}">${SVG_ICONS.air} Air Lead (${pct(ayShare, 0)})</span>`;
      }
      if (adot >= 12.5) {
        return `<span class="driver-badge adot" title="Average depth of target: ${adot.toFixed(1)} yds">${SVG_ICONS.adot} Deep (${adot.toFixed(1)} aDOT)</span>`;
      }
      if (tgts >= 6.5) {
        return `<span class="driver-badge volume" title="Target volume: ${tgts.toFixed(1)} tgt/gm">${SVG_ICONS.volume} Volume (${tgts.toFixed(1)} tgt)</span>`;
      }
      if (share >= 0.16) {
        return `<span class="driver-badge starter" title="Starting share: ${pct(share)}">${SVG_ICONS.starter} Starter (${pct(share, 0)})</span>`;
      }
      return `<span class="driver-badge depth" title="Rotational depth target">${SVG_ICONS.depth} Depth</span>`;
    },

    /** Verbatim intent-filter thresholds from pre-adapter filteredRows(). */
    intentFilters: {
      surge: (row, beneficiary) => Boolean(beneficiary),
      volume: (row) => num(row.c_targets) >= 6.5 || num(row.f_tgt_share || row.target_share) >= 0.22,
      deep: (row) => num(row.f_adot || row.adot) >= 12.0 || num(row.f_ay_share || row.air_yards_share) >= 0.30
    },

    // ── UI labels (verbatim strings from pre-adapter render paths) ──────────
    labels: {
      byeImpact: () => 'Week 7 Bye (0 Slate Impact)',
      ticker: {
        games: (n) => `${n} Games`,
        teams: (n) => `${n} Teams`,
        records: (n) => `${n} Modeled player records`,
        ingestedTail: (ingested, verified) => `${ingested} ingested (${verified} verified)`
      },
      injuredQuantImpact: {
        vacated: (item) => `Vacates ${item.vacated_targets} tgt/g (${item.vacated_air_yards ? `${item.vacated_air_yards} air yds/g` : 'high volume'})`
      }
    },

    // ── Team logo map (verbatim NFL_LOGO_MAP + ESPN NFL CDN URL) ────────────
    logo: {
      espnCdnBase: 'https://a.espncdn.com/i/teamlogos/nfl/500/',
      map: {
        ARI: { slug: 'ari', bg: 'rgba(151,35,63,0.18)', border: 'rgba(151,35,63,0.45)' },
        ATL: { slug: 'atl', bg: 'rgba(167,25,48,0.18)', border: 'rgba(167,25,48,0.45)' },
        BAL: { slug: 'bal', bg: 'rgba(36,23,115,0.25)', border: 'rgba(158,124,12,0.45)' },
        BUF: { slug: 'buf', bg: 'rgba(0,51,141,0.25)', border: 'rgba(198,12,48,0.45)' },
        CAR: { slug: 'car', bg: 'rgba(0,133,202,0.18)', border: 'rgba(0,133,202,0.45)' },
        CHI: { slug: 'chi', bg: 'rgba(11,22,42,0.45)', border: 'rgba(200,56,3,0.50)' },
        CIN: { slug: 'cin', bg: 'rgba(251,79,20,0.18)', border: 'rgba(251,79,20,0.45)' },
        CLE: { slug: 'cle', bg: 'rgba(255,60,0,0.18)', border: 'rgba(255,60,0,0.45)' },
        DAL: { slug: 'dal', bg: 'rgba(134,147,151,0.20)', border: 'rgba(134,147,151,0.50)' },
        DEN: { slug: 'den', bg: 'rgba(251,79,20,0.18)', border: 'rgba(0,34,68,0.55)' },
        DET: { slug: 'det', bg: 'rgba(0,118,182,0.22)', border: 'rgba(176,183,188,0.45)' },
        GB:  { slug: 'gb',  bg: 'rgba(24,48,40,0.40)', border: 'rgba(255,184,28,0.45)' },
        HOU: { slug: 'hou', bg: 'rgba(3,32,47,0.40)', border: 'rgba(167,25,48,0.45)' },
        IND: { slug: 'ind', bg: 'rgba(0,44,95,0.30)', border: 'rgba(162,170,173,0.45)' },
        KC:  { slug: 'kc',  bg: 'rgba(227,24,55,0.18)', border: 'rgba(255,184,28,0.45)' },
        LA:  { slug: 'lar', bg: 'rgba(0,53,148,0.25)', border: 'rgba(255,163,0,0.45)' },
        LAR: { slug: 'lar', bg: 'rgba(0,53,148,0.25)', border: 'rgba(255,163,0,0.45)' },
        LAC: { slug: 'lac', bg: 'rgba(0,128,198,0.25)', border: 'rgba(255,194,14,0.45)' },
        LV:  { slug: 'lv',  bg: 'rgba(165,172,175,0.18)', border: 'rgba(165,172,175,0.45)' },
        MIA: { slug: 'mia', bg: 'rgba(0,142,151,0.22)', border: 'rgba(252,76,2,0.45)' },
        MIN: { slug: 'min', bg: 'rgba(79,38,131,0.26)', border: 'rgba(255,198,47,0.45)' },
        NE:  { slug: 'ne',  bg: 'rgba(0,34,68,0.35)', border: 'rgba(198,12,48,0.45)' },
        NO:  { slug: 'no',  bg: 'rgba(211,188,141,0.18)', border: 'rgba(211,188,141,0.50)' },
        NYG: { slug: 'nyg', bg: 'rgba(1,35,82,0.30)', border: 'rgba(163,13,45,0.45)' },
        NYJ: { slug: 'nyj', bg: 'rgba(18,87,64,0.30)', border: 'rgba(18,87,64,0.55)' },
        PHI: { slug: 'phi', bg: 'rgba(0,76,84,0.30)', border: 'rgba(165,172,175,0.45)' },
        PIT: { slug: 'pit', bg: 'rgba(255,182,18,0.18)', border: 'rgba(255,182,18,0.50)' },
        SEA: { slug: 'sea', bg: 'rgba(0,34,68,0.35)', border: 'rgba(105,190,40,0.50)' },
        SF:  { slug: 'sf',  bg: 'rgba(170,0,0,0.22)', border: 'rgba(179,153,93,0.50)' },
        TB:  { slug: 'tb',  bg: 'rgba(213,10,10,0.22)', border: 'rgba(177,186,191,0.45)' },
        TEN: { slug: 'ten', bg: 'rgba(75,146,219,0.22)', border: 'rgba(75,146,219,0.50)' },
        WAS: { slug: 'wsh', bg: 'rgba(90,20,20,0.30)', border: 'rgba(255,182,18,0.45)' },
        WSH: { slug: 'wsh', bg: 'rgba(90,20,20,0.30)', border: 'rgba(255,182,18,0.45)' }
      }
    },

    // ── Detail modal hooks (Phase 2 remediation, audit item B4) ─────────────
    // VERBATIM extraction of the pre-adapter inline fallbacks that used to
    // live in viewer/app.js detailMarkup(). The modal now calls
    // adapter.detail.* unconditionally — no sport branches remain in app.js.
    // Byte-equality with the pre-refactor modal is proven by the
    // test/snapshots/nfl/detail_modal.json golden.
    detail: {
      scenarioCapable: true,
      marketLabel: (market) => (market === 'receptions' ? 'Receptions' : 'Receiving yards'),
      modelSpec: (market) => market === 'receptions' ? 'MODEL SPEC: INTEGER POISSON' : market === 'anytime_td' ? 'MODEL SPEC: ZERO-INFLATED POISSON' : 'MODEL SPEC: CONTINUOUS MEDIAN',
      distributionDesc: (market) => market === 'receptions' ? 'Discrete Poisson (Half-step)' : market === 'anytime_td' ? 'Poisson Red Zone Model' : 'Calibrated Continuous Log-Normal',
      sampleNote: (row) => `${num(row.games_prior, 16)} games prior · ${row.season || '2026'}`,
      scopeNote: (row, market) => market === 'receptions'
        ? `Receptions use integer outcomes and half-step lines. Fair line calibrated at P(over) = ${pct(row.p_rec_at_fair_line)}.`
        : 'Receiving-yards fair line is the calibrated continuous median, where P(over) is exactly 50.0%.',
      environment: (row, game) => {
        const isDome = row.is_dome || game?.roof === 'dome';
        const wind = game?.wind ?? row.wind_speed ?? row.wind;
        const tag = isDome ? 'ENV: DOME' : (Number.isFinite(wind) && wind > 0) ? `ENV: ${wind} MPH WIND` : 'ENV: MILD / OUTDOOR';
        const desc = isDome ? 'Indoor Dome (Controlled Conditions)' : (Number.isFinite(wind) && wind > 0) ? `${wind} mph wind (${game?.home_team ? `${game.home_team} stadium` : 'Open'})` : 'Controlled / mild conditions';
        return { tag, desc, dome: isDome };
      }
    },

    // ── Storage namespaces ──────────────────────────────────────────────────
    // Legacy keys are NEVER renamed or deleted (30-day dual-write policy);
    // migration copies legacy data into these sport-namespaced keys once.
    storageKeys: {
      ledger: 'propwire_portfolio_ledger_v2',
      watchlist: 'propwire_watchlist_nfl',
      sniperConfig: 'propwire_sniper_config_nfl',
      dismissedCorrelations: 'propwire_dismissed_correlations_nfl'
    },
    legacyKeys: {
      portfolioLedger: 'propwire_portfolio_ledger',
      watchlist: 'propwire_watchlist',
      sniperConfig: 'propwire_sniper_config',
      dismissedCorrelations: 'propwire_dismissed_correlations'
    },

    // ── Circuit breaker fallback ────────────────────────────────────────────
    // PRIMARY SOURCE: viewer/circuit_breaker_config.json (fetched at slate
    // load; single source of truth, shared with scripts/sniper_cron.py).
    // These fallbacks exist ONLY for offline/fetch-failure resilience and
    // carry the exact calibrated NFL values. Never copy these numbers to
    // another sport — each sport ships its own (initially uncalibrated)
    // config block.
    breakerFallback: {
      drift_pct_hurdle: 0.12,
      high_edge_caution_hurdle: 0.15,
      cooldown_minutes: 15,
      deadman_switch_max_age_seconds: 300,
      calibrated: true
    },

    /**
     * Correlation rule — verbatim key from pre-adapter checkCorrelatedRisk:
     * NFL receivers on the same team share game-script/target distribution.
     */
    correlationKey: (row, market) => `${row.team}::${market}`
  };

  window.PropWireSports.register(NFL_ADAPTER);
})();
