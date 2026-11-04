-- Ledger foundation. Postgres is the source of truth.
-- A hash chain is tamper-evident, not tamper-proof: a superuser can disable
-- triggers. The app role cannot UPDATE, DELETE, or TRUNCATE these tables,
-- and triggers reject those statements even for the table owner.
-- Corrections, closes, settlements, and withdrawals are new rows.
-- event_id and event_start_at are required at insert on ledger records.
-- They are not nullable, so they cannot be backfilled later.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'propstein_app') THEN
    CREATE ROLE propstein_app LOGIN;
  END IF;
END
$$;

CREATE TABLE schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pseudonym TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT users_pseudonym_nonempty CHECK (length(btrim(pseudonym)) > 0)
);

CREATE TABLE evidence_passports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users (id),
  cohort TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  context_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT evidence_passports_cohort_chk CHECK (cohort IN (
    'prospective_full_board', 'user_research', 'user_slip', 'historical_backtest'
  )),
  CONSTRAINT evidence_passports_context_chk CHECK (context_status IN (
    'VERIFIED_CONTEXT', 'UNVERIFIED_CONTEXT', 'NOT_APPLICABLE'
  ))
);

CREATE TABLE prospective_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  passport_id UUID NOT NULL UNIQUE REFERENCES evidence_passports (id),
  cohort TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  source_name TEXT NOT NULL,
  source_record_sha256 TEXT NOT NULL UNIQUE,
  game_id TEXT,
  player_id TEXT,
  market TEXT,
  model_version TEXT,
  payload_canonical TEXT NOT NULL,
  captured_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT prospective_signals_cohort_chk CHECK (cohort IN (
    'prospective_full_board', 'historical_backtest'
  )),
  CONSTRAINT prospective_signals_event_nonempty CHECK (length(btrim(event_id)) > 0)
);

CREATE INDEX prospective_signals_event_id_idx ON prospective_signals (event_id);

CREATE TABLE historical_evidence_gaps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_name TEXT NOT NULL,
  source_locator TEXT NOT NULL,
  source_cohort TEXT NOT NULL,
  missing_fields TEXT[] NOT NULL,
  flag TEXT NOT NULL DEFAULT 'MISSING_EVIDENCE',
  payload_canonical TEXT NOT NULL,
  source_integrity_hash TEXT,
  event_id TEXT,
  event_start_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT historical_evidence_gaps_flag_chk CHECK (flag = 'MISSING_EVIDENCE'),
  CONSTRAINT historical_evidence_gaps_no_backfill CHECK (
    event_id IS NULL AND event_start_at IS NULL
  ),
  CONSTRAINT historical_evidence_gaps_locator_uniq UNIQUE (source_name, source_locator)
);

CREATE TABLE research_references (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  passport_id UUID NOT NULL UNIQUE REFERENCES evidence_passports (id),
  user_id UUID NOT NULL REFERENCES users (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  player_id TEXT NOT NULL,
  player_name TEXT,
  team TEXT,
  opponent TEXT,
  game_id TEXT NOT NULL,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  line NUMERIC NOT NULL,
  book TEXT,
  quoted_american_odds INTEGER,
  observed_at TIMESTAMPTZ NOT NULL,
  snapshot_id TEXT,
  model_version TEXT,
  model_coverage TEXT NOT NULL,
  model_probability DOUBLE PRECISION,
  uncertainty_low DOUBLE PRECISION,
  uncertainty_high DOUBLE PRECISION,
  input_snapshot_hash TEXT,
  fair_line DOUBLE PRECISION,
  projected_volume DOUBLE PRECISION,
  context_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT research_references_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT research_references_selection_chk CHECK (selection IN ('over', 'under')),
  CONSTRAINT research_references_coverage_chk CHECK (
    (
      model_coverage = 'none'
      AND model_probability IS NULL
      AND model_version IS NULL
      AND input_snapshot_hash IS NULL
    )
    OR (
      model_coverage = 'uncalibrated'
      AND model_version IS NOT NULL
      AND input_snapshot_hash IS NOT NULL
      AND model_probability IS NOT NULL
    )
  ),
  CONSTRAINT research_references_context_chk CHECK (context_status IN (
    'VERIFIED_CONTEXT', 'UNVERIFIED_CONTEXT'
  ))
);

CREATE INDEX research_references_event_id_idx ON research_references (event_id);

CREATE TABLE intended_quotes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL UNIQUE REFERENCES prospective_signals (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  line NUMERIC NOT NULL,
  settlement_rules TEXT NOT NULL,
  over_american_odds INTEGER NOT NULL,
  under_american_odds INTEGER NOT NULL,
  book TEXT,
  quoted_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT intended_quotes_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT intended_quotes_selection_chk CHECK (selection IN ('over', 'under')),
  CONSTRAINT intended_quotes_rules_nonempty CHECK (length(btrim(settlement_rules)) > 0),
  CONSTRAINT intended_quotes_odds_chk CHECK (
    abs(over_american_odds) >= 100 AND abs(under_american_odds) >= 100
  )
);

CREATE TABLE placements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES prospective_signals (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  ticket_ref TEXT NOT NULL,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  achieved_line NUMERIC NOT NULL,
  settlement_rules TEXT NOT NULL,
  over_american_odds INTEGER NOT NULL,
  under_american_odds INTEGER NOT NULL,
  book TEXT,
  placed_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT placements_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT placements_ticket_nonempty CHECK (length(btrim(ticket_ref)) > 0),
  CONSTRAINT placements_selection_chk CHECK (selection IN ('over', 'under')),
  CONSTRAINT placements_rules_nonempty CHECK (length(btrim(settlement_rules)) > 0),
  CONSTRAINT placements_odds_chk CHECK (
    abs(over_american_odds) >= 100 AND abs(under_american_odds) >= 100
  )
);

CREATE TABLE closing_references (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID REFERENCES prospective_signals (id),
  placement_id UUID REFERENCES placements (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  source_id TEXT NOT NULL,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  line NUMERIC NOT NULL,
  settlement_rules TEXT,
  over_american_odds INTEGER,
  under_american_odds INTEGER,
  observed_at TIMESTAMPTZ NOT NULL,
  match_status TEXT NOT NULL,
  reason_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT closing_references_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT closing_references_source_nonempty CHECK (length(btrim(source_id)) > 0),
  CONSTRAINT closing_references_selection_chk CHECK (selection IN ('over', 'under')),
  CONSTRAINT closing_references_link_chk CHECK (signal_id IS NOT NULL OR placement_id IS NOT NULL),
  CONSTRAINT closing_references_status_chk CHECK (match_status IN ('MATCHED', 'UNMATCHED')),
  CONSTRAINT closing_references_reason_chk CHECK (
    (match_status = 'MATCHED' AND reason_code IS NULL AND settlement_rules IS NOT NULL)
    OR (match_status = 'UNMATCHED' AND reason_code IS NOT NULL)
  )
);

CREATE TABLE settlements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES prospective_signals (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  settlement_rules TEXT NOT NULL,
  result TEXT NOT NULL,
  settled_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT settlements_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT settlements_result_chk CHECK (result IN (
    'win', 'loss', 'push', 'void', 'dnp', 'cancelled'
  ))
);

CREATE TABLE withdrawals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES prospective_signals (id),
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  withdrawn_at TIMESTAMPTZ NOT NULL,
  reason_code TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT withdrawals_event_nonempty CHECK (length(btrim(event_id)) > 0)
);

CREATE TABLE attestations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  passport_id UUID REFERENCES evidence_passports (id),
  ledger_event_id UUID,
  status TEXT NOT NULL,
  payload_canonical TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT attestations_status_chk CHECK (status IN ('PENDING', 'CONFIRMED', 'FAILED'))
);

CREATE TABLE slip_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  passport_id UUID NOT NULL UNIQUE REFERENCES evidence_passports (id),
  user_id UUID NOT NULL REFERENCES users (id),
  registration_id UUID NOT NULL,
  disclaimer TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE slip_legs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slip_audit_id UUID NOT NULL REFERENCES slip_audits (id),
  leg_index INTEGER NOT NULL,
  event_id TEXT NOT NULL,
  event_start_at TIMESTAMPTZ NOT NULL,
  player_id TEXT NOT NULL,
  team TEXT,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  line NUMERIC NOT NULL,
  book TEXT,
  user_confirmed BOOLEAN NOT NULL,
  research_reference_id UUID,
  ocr_confidence DOUBLE PRECISION,
  ocr_confirmed BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT slip_legs_event_nonempty CHECK (length(btrim(event_id)) > 0),
  CONSTRAINT slip_legs_confirmed_chk CHECK (user_confirmed),
  CONSTRAINT slip_legs_selection_chk CHECK (selection IN ('over', 'under')),
  CONSTRAINT slip_legs_index_uniq UNIQUE (slip_audit_id, leg_index)
);

CREATE INDEX slip_legs_event_id_idx ON slip_legs (event_id);

CREATE TABLE rule_registry (
  rule_id TEXT PRIMARY KEY,
  family TEXT NOT NULL,
  summary TEXT NOT NULL,
  CONSTRAINT rule_registry_family_chk CHECK (family IN (
    'structural_overlap', 'structural_quality', 'reserved'
  ))
);

CREATE TABLE rule_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  release_id TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  artifact_canonical TEXT NOT NULL,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT rule_registrations_hash_chk CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$')
);

ALTER TABLE slip_audits
  ADD CONSTRAINT slip_audits_registration_fk
  FOREIGN KEY (registration_id) REFERENCES rule_registrations (id);

CREATE TABLE audit_findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slip_audit_id UUID NOT NULL REFERENCES slip_audits (id),
  rule_id TEXT NOT NULL REFERENCES rule_registry (rule_id),
  leg_indexes INTEGER[] NOT NULL,
  detail TEXT NOT NULL,
  disclaimer TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE ledger_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  passport_id UUID NOT NULL REFERENCES evidence_passports (id),
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload_canonical TEXT NOT NULL,
  prev_hash TEXT,
  integrity_hash TEXT NOT NULL,
  created_at_canonical TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ledger_events_seq_chk CHECK (seq >= 1),
  CONSTRAINT ledger_events_seq_uniq UNIQUE (passport_id, seq),
  CONSTRAINT ledger_events_hash_uniq UNIQUE (passport_id, integrity_hash),
  CONSTRAINT ledger_events_hash_chk CHECK (integrity_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ledger_events_prev_chk CHECK (prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$')
);

ALTER TABLE attestations
  ADD CONSTRAINT attestations_ledger_event_fk
  FOREIGN KEY (ledger_event_id) REFERENCES ledger_events (id);

CREATE TABLE gate_flag_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  flag_name TEXT NOT NULL,
  passed BOOLEAN NOT NULL,
  basis TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT gate_flag_events_name_chk CHECK (flag_name IN (
    'model_validation', 'paid_tier_clv'
  ))
);

INSERT INTO rule_registry (rule_id, family, summary) VALUES
  ('STRUCT_SAME_PLAYER', 'structural_overlap', 'Two or more confirmed legs name the same player.'),
  ('STRUCT_SAME_TEAM', 'structural_overlap', 'Two or more confirmed legs name the same team.'),
  ('STRUCT_SAME_GAME', 'structural_overlap', 'Two or more confirmed legs name the same event.'),
  ('STRUCT_DUPLICATE_SELECTION', 'structural_overlap', 'Two or more confirmed legs repeat the same selection.'),
  ('OCR_LOW_CONFIDENCE', 'structural_quality', 'A confirmed leg carries an OCR confidence below the registered threshold.'),
  ('OCR_UNCONFIRMED', 'structural_quality', 'A confirmed leg carries an OCR read that was not confirmed.'),
  ('MISSING_REFERENCE', 'structural_quality', 'A confirmed leg has no research reference.'),
  ('MARKET_UNSUPPORTED', 'structural_quality', 'A confirmed leg names a market outside the registered scope.'),
  ('MODEL_LINE_MISMATCH', 'reserved', 'Reserved. Not evaluated.'),
  ('MODEL_PRICE_MISMATCH', 'reserved', 'Reserved. Not evaluated.'),
  ('JOINT_DEPENDENCE_HIGH', 'reserved', 'Reserved. Not evaluated.'),
  ('PAYOUT_DISTRIBUTION_MISMATCH', 'reserved', 'Reserved. Not evaluated.'),
  ('SCENARIO_SENSITIVITY', 'reserved', 'Reserved. Not evaluated.'),
  ('DISAGREEMENT_INVESTIGATION', 'reserved', 'Reserved. Not evaluated.');

CREATE OR REPLACE FUNCTION ledger_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'append-only ledger: % on % is rejected', TG_OP, TG_TABLE_NAME
    USING ERRCODE = '55000';
END;
$$;

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'schema_migrations',
    'users',
    'evidence_passports',
    'prospective_signals',
    'historical_evidence_gaps',
    'research_references',
    'intended_quotes',
    'placements',
    'closing_references',
    'settlements',
    'withdrawals',
    'attestations',
    'slip_audits',
    'slip_legs',
    'rule_registry',
    'rule_registrations',
    'audit_findings',
    'ledger_events',
    'gate_flag_events'
  ]
  LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION ledger_reject_mutation()',
      t || '_reject_update', t
    );
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW EXECUTE FUNCTION ledger_reject_mutation()',
      t || '_reject_delete', t
    );
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_mutation()',
      t || '_reject_truncate', t
    );
  END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION ledger_events_enforce_link() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  prior_hash text;
  prior_seq integer;
BEGIN
  IF NEW.seq = 1 THEN
    IF NEW.prev_hash IS NOT NULL THEN
      RAISE EXCEPTION 'append-only ledger: first event must have null prev_hash';
    END IF;
    RETURN NEW;
  END IF;
  SELECT integrity_hash, seq INTO prior_hash, prior_seq
  FROM ledger_events
  WHERE passport_id = NEW.passport_id
  ORDER BY seq DESC
  LIMIT 1;
  IF prior_seq IS NULL OR prior_seq <> NEW.seq - 1 THEN
    RAISE EXCEPTION 'append-only ledger: sequence gap for passport %', NEW.passport_id;
  END IF;
  IF NEW.prev_hash IS DISTINCT FROM prior_hash THEN
    RAISE EXCEPTION 'append-only ledger: prev_hash does not match prior integrity_hash';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_events_link
  BEFORE INSERT ON ledger_events
  FOR EACH ROW EXECUTE FUNCTION ledger_events_enforce_link();

CREATE OR REPLACE FUNCTION prospective_signals_cohort_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  passport_cohort text;
BEGIN
  SELECT cohort INTO passport_cohort FROM evidence_passports WHERE id = NEW.passport_id;
  IF passport_cohort IS DISTINCT FROM NEW.cohort THEN
    RAISE EXCEPTION 'signal cohort does not match passport';
  END IF;
  IF NEW.cohort NOT IN ('prospective_full_board', 'historical_backtest') THEN
    RAISE EXCEPTION 'user records cannot be inserted as signal ledger rows';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER prospective_signals_cohort
  BEFORE INSERT ON prospective_signals
  FOR EACH ROW EXECUTE FUNCTION prospective_signals_cohort_guard();

CREATE OR REPLACE FUNCTION research_references_cohort_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  passport_cohort text;
BEGIN
  SELECT cohort INTO passport_cohort FROM evidence_passports WHERE id = NEW.passport_id;
  IF passport_cohort IS DISTINCT FROM 'user_research' THEN
    RAISE EXCEPTION 'research references are user records';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER research_references_cohort
  BEFORE INSERT ON research_references
  FOR EACH ROW EXECUTE FUNCTION research_references_cohort_guard();

CREATE OR REPLACE FUNCTION slip_audits_cohort_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  passport_cohort text;
BEGIN
  SELECT cohort INTO passport_cohort FROM evidence_passports WHERE id = NEW.passport_id;
  IF passport_cohort IS DISTINCT FROM 'user_slip' THEN
    RAISE EXCEPTION 'slip audits are user records';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER slip_audits_cohort
  BEFORE INSERT ON slip_audits
  FOR EACH ROW EXECUTE FUNCTION slip_audits_cohort_guard();

CREATE OR REPLACE FUNCTION closing_match_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  quote_row intended_quotes%ROWTYPE;
  placement_row placements%ROWTYPE;
BEGIN
  IF NEW.match_status = 'UNMATCHED' THEN
    RETURN NEW;
  END IF;
  IF NEW.signal_id IS NOT NULL THEN
    SELECT * INTO quote_row FROM intended_quotes WHERE signal_id = NEW.signal_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'matched close requires the intended quote committed with the forecast';
    END IF;
    IF quote_row.event_id IS DISTINCT FROM NEW.event_id
       OR quote_row.market IS DISTINCT FROM NEW.market
       OR quote_row.selection IS DISTINCT FROM NEW.selection
       OR quote_row.line IS DISTINCT FROM NEW.line
       OR quote_row.settlement_rules IS DISTINCT FROM NEW.settlement_rules THEN
      RAISE EXCEPTION 'matched close must share event, market, selection, line, and settlement rules';
    END IF;
  END IF;
  IF NEW.placement_id IS NOT NULL THEN
    SELECT * INTO placement_row FROM placements WHERE id = NEW.placement_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'placement close is missing its placement';
    END IF;
    IF placement_row.event_id IS DISTINCT FROM NEW.event_id
       OR placement_row.market IS DISTINCT FROM NEW.market
       OR placement_row.selection IS DISTINCT FROM NEW.selection
       OR placement_row.achieved_line IS DISTINCT FROM NEW.line
       OR placement_row.settlement_rules IS DISTINCT FROM NEW.settlement_rules THEN
      RAISE EXCEPTION 'matched placement close must share event, market, selection, achieved line, and settlement rules';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER closing_references_match
  BEFORE INSERT ON closing_references
  FOR EACH ROW EXECUTE FUNCTION closing_match_guard();

CREATE VIEW population_committed_forecasts AS
  SELECT * FROM prospective_signals WHERE cohort = 'prospective_full_board';

CREATE VIEW population_graded_forecasts AS
  SELECT s.*
  FROM population_committed_forecasts s
  WHERE EXISTS (SELECT 1 FROM settlements g WHERE g.signal_id = s.id);

CREATE VIEW population_placements AS
  SELECT p.*
  FROM placements p
  JOIN population_committed_forecasts s ON s.id = p.signal_id;

CREATE VIEW population_closing_matches_committed AS
  SELECT DISTINCT s.id AS signal_id
  FROM population_committed_forecasts s
  JOIN closing_references c ON c.signal_id = s.id
  WHERE c.match_status = 'MATCHED';

CREATE VIEW population_closing_matches_placements AS
  SELECT DISTINCT p.id AS placement_id
  FROM population_placements p
  JOIN closing_references c ON c.placement_id = p.id
  WHERE c.match_status = 'MATCHED';

CREATE VIEW population_missing_closing_quotes AS
  SELECT s.*
  FROM population_committed_forecasts s
  WHERE NOT EXISTS (
    SELECT 1 FROM closing_references c
    WHERE c.signal_id = s.id AND c.match_status = 'MATCHED'
  );

CREATE VIEW population_withdrawals AS
  SELECT w.*
  FROM withdrawals w
  JOIN population_committed_forecasts s ON s.id = w.signal_id;

CREATE VIEW population_counts AS
  SELECT
    (SELECT count(*) FROM population_committed_forecasts) AS committed_forecasts,
    (SELECT count(*) FROM population_graded_forecasts) AS graded_forecasts,
    (SELECT count(*) FROM population_placements) AS placements,
    (SELECT count(*) FROM population_closing_matches_committed) AS closing_price_matches,
    (SELECT count(*) FROM population_closing_matches_committed) AS closing_price_matches_committed,
    (SELECT count(*) FROM population_closing_matches_placements) AS closing_price_matches_placements,
    (SELECT count(*) FROM population_missing_closing_quotes) AS missing_closing_quotes,
    (SELECT count(*) FROM population_withdrawals) AS withdrawals;

CREATE VIEW independent_gate_flags AS
  SELECT DISTINCT ON (flag_name) flag_name, passed, basis, recorded_at
  FROM gate_flag_events
  ORDER BY flag_name, recorded_at DESC, id DESC;

REVOKE ALL ON SCHEMA public FROM propstein_app;
GRANT USAGE ON SCHEMA public TO propstein_app;

GRANT SELECT, INSERT ON
  users,
  evidence_passports,
  prospective_signals,
  historical_evidence_gaps,
  research_references,
  intended_quotes,
  placements,
  closing_references,
  settlements,
  withdrawals,
  slip_audits,
  slip_legs,
  audit_findings,
  ledger_events
TO propstein_app;

GRANT SELECT ON
  rule_registry,
  rule_registrations,
  attestations,
  gate_flag_events,
  schema_migrations,
  population_committed_forecasts,
  population_graded_forecasts,
  population_placements,
  population_closing_matches_committed,
  population_closing_matches_placements,
  population_missing_closing_quotes,
  population_withdrawals,
  population_counts,
  independent_gate_flags
TO propstein_app;

REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM propstein_app;
