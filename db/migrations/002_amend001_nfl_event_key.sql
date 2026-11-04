-- AMEND-001 NFL event key. Prospective from 2026-11-01T00:00:00Z.
-- event_id stays the clustering key. provider_event_id is a separate nullable
-- column and is not a clustering key. Existing rows are not rewritten.

CREATE TABLE protocol_amendments (
  amendment_id TEXT PRIMARY KEY,
  sport TEXT NOT NULL,
  effective_at TIMESTAMPTZ NOT NULL,
  prospective_only BOOLEAN NOT NULL,
  summary TEXT NOT NULL,
  document_path TEXT NOT NULL,
  document_sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT protocol_amendments_id_chk CHECK (amendment_id ~ '^AMEND-[0-9]{3}$'),
  CONSTRAINT protocol_amendments_hash_chk CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT protocol_amendments_prospective_chk CHECK (prospective_only),
  CONSTRAINT protocol_amendments_sport_nonempty CHECK (length(btrim(sport)) > 0)
);

CREATE TRIGGER protocol_amendments_reject_update
  BEFORE UPDATE ON protocol_amendments
  FOR EACH ROW EXECUTE FUNCTION ledger_reject_mutation();

CREATE TRIGGER protocol_amendments_reject_delete
  BEFORE DELETE ON protocol_amendments
  FOR EACH ROW EXECUTE FUNCTION ledger_reject_mutation();

CREATE TRIGGER protocol_amendments_reject_truncate
  BEFORE TRUNCATE ON protocol_amendments
  FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_mutation();

INSERT INTO protocol_amendments (
  amendment_id, sport, effective_at, prospective_only, summary, document_path, document_sha256
) VALUES (
  'AMEND-001',
  'NFL',
  '2026-11-01T00:00:00Z',
  TRUE,
  'NFL ledger event_id is the captured nflverse game_id. provider_event_id is stored separately and is not a clustering key. event_start_at is the captured kickoff_at.',
  'docs/protocol_amendments/AMEND-001-nfl-event-key.md',
  'a3f03276d014cc7bccd5e572a9c765861f25e6921031b6ab388a23566bd9e6c5'
);

ALTER TABLE rule_registry DROP CONSTRAINT rule_registry_family_chk;

ALTER TABLE rule_registry ADD CONSTRAINT rule_registry_family_chk CHECK (family IN (
  'structural_overlap', 'structural_quality', 'reserved', 'protocol'
));

INSERT INTO rule_registry (rule_id, family, summary) VALUES (
  'AMEND-001',
  'protocol',
  'NFL ledger event_id is the captured nflverse game_id. provider_event_id is stored separately and is not a clustering key. event_start_at is the captured kickoff_at. Prospective from 2026-11-01.'
);

ALTER TABLE prospective_signals
  ADD COLUMN provider_event_id TEXT,
  ADD COLUMN amendment_id TEXT;

ALTER TABLE prospective_signals
  ADD CONSTRAINT prospective_signals_amendment_fk
  FOREIGN KEY (amendment_id) REFERENCES protocol_amendments (amendment_id);

COMMENT ON COLUMN prospective_signals.event_id IS
  'Clustering key. Under AMEND-001 for NFL this is the captured nflverse game_id.';

COMMENT ON COLUMN prospective_signals.provider_event_id IS
  'Odds-provider event id when that field was captured on the source row. Never a clustering key.';

-- SELECT * views keep the column list from when they were created.
CREATE OR REPLACE VIEW population_committed_forecasts AS
  SELECT * FROM prospective_signals WHERE cohort = 'prospective_full_board';

CREATE VIEW population_nfl_confirmatory AS
  SELECT *
  FROM population_committed_forecasts
  WHERE amendment_id = 'AMEND-001';

GRANT SELECT ON protocol_amendments, population_nfl_confirmatory TO propstein_app;

REVOKE UPDATE, DELETE, TRUNCATE ON protocol_amendments FROM propstein_app;
