"""Synthetic fixtures for prospective capture and fail-closed close audits."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.crypto_utils import canonical_json_sha256
from src.prospective_board import capture_board, grade_board


def snapshot(player: str, market: str, kind: str, quote: dict | None = None) -> dict:
    row = {
        "snapshot_id": f"SYN-{player}-{market}-{kind}",
        "snapshot_type": kind,
        "created_at": "2030-01-01T15:00:00+00:00",
        "slate": "SYNTHETIC",
        "game_id": "SYN-GAME",
        "player_id": player,
        "player_name": player,
        "market": market,
        "model": {"version": "synthetic-test"},
        "quote": quote or {"status": "unquoted", "line": None},
    }
    row["content_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return row


def close(line: float) -> dict:
    row = {
        "event_id": "SYN-GAME", "player_id": "SYN-A", "book": "SyntheticBook",
        "market": "receptions", "closing_line": line, "closing_over_odds": -120,
        "closing_under_odds": 100, "closing_fair_line": line,
        "provider_event_id": "SYN-PROVIDER-GAME",
        "provider_update_ts": int(datetime(2030, 1, 1, 16, 59, 30, tzinfo=timezone.utc).timestamp() * 1000),
        "raw_provider_payload_sha256": "a" * 64,
    }
    row["closing_snapshot_sha256"] = canonical_json_sha256({"schema": "propwire.closing_snapshot.v1", **row})
    return row


class ProspectiveBoardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshots = self.root / "snapshots.jsonl"
        self.kickoffs = self.root / "kickoffs.json"
        self.journal = self.root / "journal.jsonl"
        self.closes = self.root / "closes.json"
        self.now = datetime(2030, 1, 1, 16, tzinfo=timezone.utc)
        self.kickoffs.write_text(json.dumps({"SYN-GAME": "2030-01-01T17:00:00Z"}))
        self.rows = [
            snapshot("SYN-A", "receptions", "pre_kickoff"),
            snapshot("SYN-B", "receptions", "pre_kickoff"),
            snapshot("SYN-A", "receptions", "first_published", {
                "status": "unverified", "book": "SyntheticBook", "line": 4.5,
                "over_odds": -110, "under_odds": -110,
                "observed_at": "2030-01-01T15:00:00Z", "quote_id": "SYN-QUOTE",
                "evaluation": {"is_qualified": True, "best_side": "OVER"},
            }),
        ]
        self.snapshots.write_text("".join(json.dumps(row) + "\n" for row in self.rows))

    def capture(self):
        return capture_board(self.snapshots, self.kickoffs, self.journal, captured_at=self.now)

    def test_captures_pass_and_unverified_qualified_claim(self):
        summary = capture_board(self.snapshots, self.kickoffs, self.journal,
                                captured_at=self.now, game_id="SYN-GAME")
        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(summary["pass_no_quote_count"], 1)
        self.assertEqual(summary["observed_quote_count"], 1)
        journal = [json.loads(line) for line in self.journal.read_text().splitlines()]
        self.assertEqual({row["decision"] for row in journal}, {"PASS_NO_QUOTE", "OBSERVED_RESEARCH_ONLY"})
        self.assertEqual(journal[0]["observations"][0]["receipt_status"], "NO_INDEPENDENT_SOURCE_RECEIPT")
        with self.assertRaises(FileExistsError):
            self.capture()

    def test_missing_scheduled_universe_refuses_capture(self):
        self.kickoffs.write_text(json.dumps({
            "SYN-GAME": "2030-01-01T17:00:00Z",
            "SYN-MISSING": "2030-01-01T18:00:00Z",
        }))
        with self.assertRaisesRegex(ValueError, "missing frozen candidate universe"):
            self.capture()

    def test_bad_source_hash_and_post_kickoff_refuse_capture(self):
        self.rows[0]["player_name"] = "tampered"
        self.snapshots.write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        with self.assertRaisesRegex(ValueError, "invalid frozen snapshot hash"):
            self.capture()
        self.assertFalse(self.journal.exists())
        self.rows[0]["player_name"] = "SYN-A"
        self.snapshots.write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        with self.assertRaisesRegex(ValueError, "every game has kicked off"):
            capture_board(self.snapshots, self.kickoffs, self.journal,
                          captured_at=datetime(2030, 1, 1, 18, tzinfo=timezone.utc))

    def test_exact_close_is_still_unverified_entry(self):
        self.capture()
        self.closes.write_text(json.dumps([close(4.5)]))
        report = grade_board(self.journal, self.closes)
        self.assertEqual(report["status_counts"], {"PASS_NO_QUOTE": 1, "UNVERIFIED_ENTRY_RECEIPT": 1})
        self.assertEqual(report["verified_clv_sample_size"], 0)
        self.assertIsNone(report["beat_close_rate"])

    def test_line_change_and_missing_close_are_explicit(self):
        self.capture()
        self.closes.write_text(json.dumps([close(5.5)]))
        self.assertEqual(grade_board(self.journal, self.closes)["status_counts"],
                         {"LINE_CHANGED_NO_EXACT_PRICE_COMPARISON": 1, "PASS_NO_QUOTE": 1})
        self.closes.write_text("[]")
        self.assertEqual(grade_board(self.journal, self.closes)["status_counts"],
                         {"MISSING_CLOSE": 1, "PASS_NO_QUOTE": 1})

    def test_stale_close_is_not_accepted(self):
        self.capture()
        old = close(4.5)
        old["provider_update_ts"] -= 300_000
        old["closing_snapshot_sha256"] = canonical_json_sha256({
            "schema": "propwire.closing_snapshot.v1",
            **{key: value for key, value in old.items() if key != "closing_snapshot_sha256"},
        })
        self.closes.write_text(json.dumps([old]))
        self.assertEqual(grade_board(self.journal, self.closes)["status_counts"],
                         {"PASS_NO_QUOTE": 1, "UNVERIFIED_OR_AMBIGUOUS_CLOSE": 1})

    def test_tampered_journal_fails(self):
        self.capture()
        rows = [json.loads(line) for line in self.journal.read_text().splitlines()]
        rows[0]["observations"][0]["line"] = 99.5
        self.journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.closes.write_text("[]")
        with self.assertRaisesRegex(ValueError, "journal record hash mismatch"):
            grade_board(self.journal, self.closes)


if __name__ == "__main__":
    unittest.main()
