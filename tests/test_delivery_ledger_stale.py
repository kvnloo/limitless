"""delivery_ledger.name_stale_unknown: the ledger form of kevin-push's name_unknown.

A queued row whose send was killed before it settled (OOM kill, reboot) would hold its slot as queued forever.
The next push names it unknown: it keeps its slot and dedupe key, is never replayed, and a send that was only
slow still settles its own row (unknown -> sent or held/failed).
Synthetic targets only; nothing is sent. NOW is an arbitrary epoch.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_ledger as dl  # noqa: E402
from limitless import send_gate  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
DAY = NOW - 6 * H
T = "telegram:synthetic-chat:"
AFTER = send_gate.PENDING_UNKNOWN_S


class Stale(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = dl.open_ledger(Path(tmp.name) / "ledger.sqlite3")
        self.addCleanup(self.db.close)

    def q(self, at, key=None):
        r = dl.reserve(self.db, T, "synthetic body", day_start=DAY, now=at, dedup_key=key)
        self.assertEqual(r.state, "queued")
        return r.id

    def state(self, row_id):
        return self.db.execute("SELECT state FROM delivery WHERE id = ?", (row_id,)).fetchone()[0]

    def test_a_queued_row_older_than_after_s_becomes_unknown_and_a_fresh_one_stays(self):
        old, fresh = self.q(NOW - AFTER - 1), self.q(NOW - 5)
        self.assertEqual(dl.name_stale_unknown(self.db, NOW, AFTER), 1)
        self.assertEqual((self.state(old), self.state(fresh)), ("unknown", "queued"))

    def test_exactly_after_s_is_not_yet_stale(self):
        row = self.q(NOW - AFTER)
        self.assertEqual(dl.name_stale_unknown(self.db, NOW, AFTER), 0)
        self.assertEqual(self.state(row), "queued")

    def test_the_named_row_keeps_its_slot_and_its_dedupe_key(self):
        self.q(NOW - AFTER - 1, key="once:wake_brief:synthetic")
        before = dl.used(self.db, T, DAY)
        dl.name_stale_unknown(self.db, NOW, AFTER)
        self.assertEqual(dl.used(self.db, T, DAY), before)
        again = dl.reserve(self.db, T, "other words", day_start=DAY, now=NOW, dedup_key="once:wake_brief:synthetic")
        self.assertEqual((again.state, again.reason), ("held", "dedup"))

    def test_a_slow_send_still_settles_its_own_row_after_it_was_named(self):
        ok, bad = self.q(NOW - AFTER - 9), self.q(NOW - AFTER - 8)
        dl.name_stale_unknown(self.db, NOW, AFTER)
        dl.mark_sent(self.db, ok, NOW)
        dl.mark_failed(self.db, bad)
        self.assertEqual((self.state(ok), self.state(bad)), ("sent", "held"))

    def test_only_queued_rows_move_and_a_second_pass_moves_nothing(self):
        sent, held = self.q(NOW - AFTER - 9), None
        dl.mark_sent(self.db, sent, NOW - AFTER - 8)
        held = dl.reserve(self.db, T, "synthetic", day_start=DAY, now=NOW - AFTER - 7, hold="sleep").id
        self.q(NOW - AFTER - 1)
        self.assertEqual(dl.name_stale_unknown(self.db, NOW, AFTER), 1)
        self.assertEqual(dl.name_stale_unknown(self.db, NOW, AFTER), 0)
        self.assertEqual((self.state(sent), self.state(held)), ("sent", "held"))

    def test_a_negative_after_s_raises_and_moves_nothing(self):
        row = self.q(NOW - AFTER - 1)
        with self.assertRaises(ValueError):
            dl.name_stale_unknown(self.db, NOW, -1)
        self.assertEqual(self.state(row), "queued")


if __name__ == "__main__":
    unittest.main()
