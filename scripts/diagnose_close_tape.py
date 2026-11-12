#!/usr/bin/env python3
"""Read-only close-tape diagnosis. Does not connect to Postgres.

Row count is unknown. DATABASE_URL is not read. The CREATE TABLE in
src/closing_snapshot_cron.py is the schema this script judges.
"""

from __future__ import annotations

SQL = """
BEGIN READ ONLY;
SELECT COUNT(*) AS n FROM closing_snapshots;
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'closing_snapshots'
ORDER BY ordinal_position;
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'closing_snapshots'
  AND column_name IN ('kickoff_at', 'captured_at', 'game_kickoff_ts');
ROLLBACK;
"""

FINDING = """
Not queried. No production connection from this script.
Schema in src/closing_snapshot_cron.py, table closing_snapshots:
  id, event_id, player_id, book, market, closing_line,
  closing_over_odds, closing_under_odds,
  closing_de_vig_over_prob, closing_de_vig_under_prob, closing_fair_line,
  provider_event_id, provider_update_ts, raw_provider_payload_sha256,
  closing_snapshot_sha256, locked_at.
kickoff_at is absent. captured_at is absent.
game_kickoff_ts is selected from latest_market_quotes and then discarded
unless a new lock writes it. New locks store kickoff_at and captured_at and
include both in closing_snapshot_sha256. Older rows do not have those columns
populated. Do not backfill them.
A future snapshots/close_tape.jsonl row needs player_id, market, book, line,
captured_at, kickoff_at, and receipt_sha256, with captured_at < kickoff_at.
"""


def main() -> int:
    print(SQL.strip())
    print(FINDING.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
