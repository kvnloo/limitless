"""limitless/delivery_ledger.py: one row per message to one target, its moves, and the day budget.

Synthetic targets only (telegram:synthetic-chat:...); nothing is sent and nothing touches the network.
NOW is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_ledger as dl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 2_000_000_000.0
H = 3600.0
DAY = NOW - 6 * H          # the caller's budget day started six hours ago
YESTERDAY = DAY - 24 * H
T = "telegram:synthetic-chat:"
T2 = "telegram:synthetic-chat:synthetic-thread"


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.db = self.connect()

    def connect(self):
        conn = dl.open_ledger(self.path)
        self.addCleanup(conn.close)
        return conn

    def row(self, row_id):
        return dict(self.db.execute("SELECT * FROM delivery WHERE id = ?", (row_id,)).fetchone())

    def fill(self, n, target=T, cls="anytime", at=NOW, cap=dl.DEFAULT_CAP, day=DAY):
        out = [dl.reserve(self.db, target, f"body {i}", day_start=day, now=at, cap=cap, window_class=cls)
               for i in range(n)]
        self.assertTrue(all(r.state == "queued" for r in out), out)
        return out


# --- stage schema
class Schema(LedgerCase):
    def test_one_table_with_the_agreed_columns(self):
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(delivery)")]
        self.assertEqual(cols, ["id", "target", "job_id", "dedup_key", "window_class", "state", "reason", "body",
                                "created_at", "release_after", "sent_at", "reserved_at"])
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        self.assertEqual(tables, ["delivery"])

    def test_the_index_is_target_state_created_at(self):
        idx = [r[1] for r in self.db.execute("PRAGMA index_list(delivery)") if not r[1].startswith("sqlite_")]
        self.assertEqual(len(idx), 1)
        self.assertEqual([r[2] for r in self.db.execute(f"PRAGMA index_info({idx[0]})")],
                         ["target", "state", "created_at"])

    def test_a_state_or_class_outside_the_lists_is_refused_by_the_table(self):
        sql = ("INSERT INTO delivery (target, window_class, state, reason, body, created_at)"
               " VALUES (?, ?, ?, ?, 'b', 0)")
        for cls, state, reason in (("anytime", "lost", "cap"), ("wind_down", "held", "cap"),
                                   ("anytime", "held", "bored"), ("anytime", "held", None)):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, (T, cls, state, reason))

    def test_open_twice_keeps_the_rows(self):
        self.db.execute("INSERT INTO delivery (target, window_class, state, reason, body, created_at)"
                        " VALUES (?, 'anytime', 'held', 'cap', 'b', 0)", (T,))
        self.assertEqual(self.connect().execute("SELECT COUNT(*) FROM delivery").fetchone()[0], 1)

    def test_the_doc_shows_the_schema_and_the_budget_query_the_code_runs(self):
        doc = (ROOT / "docs" / "delivery-ledger.md").read_text()
        blocks = re.findall(r"```sql\n(.*?)```", doc, re.S)
        self.assertIn(dl.SCHEMA, blocks)
        flat = [" ".join(b.split()) for b in blocks]
        self.assertTrue(any(f.startswith(" ".join(dl.BUDGET_SQL.split())) for f in flat), flat)


if __name__ == "__main__":
    unittest.main()
