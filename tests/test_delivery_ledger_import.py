"""limitless/delivery_ledger.import_legacy: the Cutover import of sent.json + held.jsonl rows into the ledger.

Synthetic rows and targets only; nothing is sent and nothing reads the real state files.
NOW is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_ledger as dl  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
DAY = NOW - 6 * H
T = "telegram:synthetic-chat:"


class ImportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = dl.open_ledger(Path(self.tmp.name) / "ledger.sqlite3")
        self.addCleanup(self.db.close)

    def rows(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM delivery ORDER BY id")]

    def run_import(self, sent=(), held=()):
        return dl.import_legacy(self.db, T, list(sent), list(held), day_start=DAY, now=NOW)

    def test_delivered_row_becomes_sent_and_keeps_its_slot(self):
        out = self.run_import(sent=[{"t": NOW - H, "k": "abc"}])
        [row] = self.rows()
        self.assertEqual((row["state"], row["reserved_at"], row["sent_at"]), ("sent", NOW - H, NOW - H))
        self.assertEqual(row["dedup_key"], "k:abc")
        self.assertEqual(dl.used(self.db, T, DAY), 1)
        self.assertEqual(out["sent"], 1)

    def test_once_key_is_the_dedup_key_and_holds_a_later_copy(self):
        self.run_import(sent=[{"t": NOW - H, "k": "abc", "once": "wake_brief:e1"}])
        later = dl.reserve(self.db, T, "x", day_start=DAY, now=NOW, dedup_key="once:wake_brief:e1")
        self.assertEqual((later.state, later.reason), ("held", "dedup"))

    def test_pending_and_unknown_rows_become_unknown_with_their_slot(self):
        out = self.run_import(sent=[{"t": NOW - H, "k": "a", "pending": "tok1"},
                                    {"t": NOW - 2 * H, "k": "b", "unknown": True, "token": "tok2"}])
        self.assertEqual([r["state"] for r in self.rows()], ["unknown", "unknown"])
        self.assertEqual(dl.used(self.db, T, DAY), 2)
        self.assertEqual(out["unknown"], 2)

    def test_rows_before_the_budget_day_are_not_imported(self):
        out = self.run_import(sent=[{"t": DAY - 1, "k": "old"}])
        self.assertEqual(self.rows(), [])
        self.assertEqual(out["skipped"], 1)

    def test_quiet_claim_is_not_a_send(self):
        out = self.run_import(sent=[{"t": NOW - H, "once": "e", "quiet": True}])
        self.assertEqual(self.rows(), [])
        self.assertEqual(dl.used(self.db, T, DAY), 0)
        self.assertEqual(out["skipped"], 1)

    def test_held_row_becomes_held_sleep_with_title_first(self):
        out = self.run_import(held=[{"at": int(NOW - 3 * H), "tag": "limitless", "title": "Pick one",
                                     "body": "Keep it?", "k": "once:ev", "once": "ev"}])
        [row] = self.rows()
        self.assertEqual((row["state"], row["reason"], row["reserved_at"]), ("held", "sleep", None))
        self.assertEqual(row["body"], "Pick one\nKeep it?")
        self.assertEqual(row["dedup_key"], "once:ev")
        self.assertEqual(row["created_at"], NOW - 3 * H)
        self.assertEqual(out["held"], 1)

    def test_held_rows_are_imported_even_from_before_the_budget_day(self):
        self.run_import(held=[{"at": int(DAY - 5 * H), "title": "t", "body": "b"}])
        self.assertEqual([r["state"] for r in self.rows()], ["held"])

    def test_malformed_rows_are_skipped_not_raised(self):
        out = self.run_import(sent=["nope", {"k": "no time"}, {"t": "x"}], held=[{"title": 1}, 7])
        self.assertEqual(self.rows(), [])
        self.assertEqual(out["skipped"], 5)

    def test_refuses_a_ledger_that_already_has_rows(self):
        dl.reserve(self.db, T, "first", day_start=DAY, now=NOW)
        with self.assertRaises(dl.LedgerNotEmpty):
            self.run_import(sent=[{"t": NOW - H, "k": "abc"}])
        self.assertEqual(len(self.rows()), 1)

    def test_import_is_one_transaction(self):
        class Boom(Exception):
            pass

        class Row(dict):
            def get(self, k, d=None):
                if k == "body":
                    raise Boom()
                return dict.get(self, k, d)

        with self.assertRaises(Boom):
            self.run_import(sent=[{"t": NOW - H, "k": "a"}],
                            held=[Row(at=int(NOW), title="t", body="b")])
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
