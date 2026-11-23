"""owner_messages.newest_user_message: the newest message the person wrote to any agent, across several
Hermes session stores. Synthetic data only.

The tables keep the columns the reader uses, with the types and indexes of NousResearch/hermes-agent
persistence/sqlite/_schema_ddl.py (0f602c5): sessions(id, source), messages(session_id, role, content,
timestamp REAL NOT NULL) and idx_messages_session ON messages(session_id, timestamp).
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import owner_messages as om  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z
H = 3600.0
SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    timestamp REAL NOT NULL
);
"""
HERMES_INDEX = "CREATE INDEX idx_messages_session ON messages(session_id, timestamp);"
CONTENT = "synthetic words the reader must never return"


def make_db(path, messages, index=HERMES_INDEX, sessions=(("s-cli", "cli"), ("s-tg", "telegram"))):
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(SCHEMA + (index or ""))
    con.executemany("INSERT INTO sessions (id, source, started_at) VALUES (?, ?, 0)", sessions)
    con.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)", messages)
    con.commit()
    con.close()
    return path


class Newest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.a = make_db(self.dir / "a.db", [
            ("s-tg", "user", CONTENT + " one", NOW - 30 * H),
            ("s-tg", "assistant", CONTENT + " two", NOW - 1 * H),   # newer, but not the person
        ])
        self.b = make_db(self.dir / "b.db", [
            ("s-cli", "user", CONTENT + " three", NOW - 3 * H),
            ("s-cli", "tool", CONTENT + " four", NOW - 0.5 * H),
            ("s-tg", "user", CONTENT + " five", NOW - 2 * H),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_newest_user_message_across_every_db_and_source(self):
        out = om.newest_user_message([self.a, self.b], NOW)
        self.assertEqual(out["at"], "2030-01-15T10:00:00+00:00")
        self.assertAlmostEqual(out["age_h"], 2.0)
        self.assertEqual((out["sources_read"], out["sources_failed"]), (2, 0))

    def test_one_db_alone_looks_old(self):
        out = om.newest_user_message([self.a], NOW)
        self.assertAlmostEqual(out["age_h"], 30.0)

    def test_no_content_anywhere_in_the_result(self):
        out = json.dumps(om.newest_user_message([self.a, self.b], NOW))
        self.assertNotIn("synthetic", out)
        self.assertEqual(set(om.newest_user_message([self.a], NOW)), {"at", "age_h", "sources_read", "sources_failed"})

    def test_missing_malformed_and_odd_paths_count_as_failed_and_never_raise(self):
        junk = self.dir / "junk.db"
        junk.write_bytes(b"not a database at all " * 64)
        empty_schema = self.dir / "noschema.db"
        sqlite3.connect(str(empty_schema)).close()
        out = om.newest_user_message([self.dir / "gone.db", junk, empty_schema, self.dir, "", None, self.b], NOW)
        self.assertEqual(out["at"], "2030-01-15T10:00:00+00:00")
        self.assertEqual((out["sources_read"], out["sources_failed"]), (1, 6))

    def test_a_locked_db_counts_as_failed_quickly(self):
        lock = sqlite3.connect(str(self.a), isolation_level=None)
        lock.execute("BEGIN EXCLUSIVE")
        try:
            out = om.newest_user_message([self.a, self.b], NOW)
        finally:
            lock.execute("ROLLBACK")
            lock.close()
        self.assertEqual((out["sources_read"], out["sources_failed"]), (1, 1))
        self.assertAlmostEqual(out["age_h"], 2.0)
        self.assertLessEqual(om.BUSY_TIMEOUT_S, 1.0)

    def test_the_db_is_opened_read_only(self):
        before = self.a.read_bytes()
        mtime = self.a.stat().st_mtime_ns
        om.newest_user_message([self.a], NOW)
        self.assertEqual(self.a.read_bytes(), before)
        self.assertEqual(self.a.stat().st_mtime_ns, mtime)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["a.db", "b.db"])  # no journal, no wal

    def test_no_dbs_or_no_user_message_is_no_time_not_zero(self):
        out = om.newest_user_message([], NOW)
        self.assertEqual(out, {"at": None, "age_h": None, "sources_read": 0, "sources_failed": 0})
        quiet = make_db(self.dir / "quiet.db", [("s-cli", "assistant", CONTENT, NOW - H)])
        out = om.newest_user_message([quiet], NOW)
        self.assertEqual((out["at"], out["age_h"], out["sources_read"]), (None, None, 1))

    def test_a_clock_far_ahead_is_ignored_a_little_ahead_is_now(self):
        ahead = make_db(self.dir / "ahead.db", [
            ("s-cli", "user", CONTENT, NOW + 2 * H),           # a machine whose clock is wrong
            ("s-cli", "user", CONTENT, NOW + 60),              # small skew between machines
        ])
        out = om.newest_user_message([ahead, self.a], NOW)
        self.assertEqual(out["age_h"], 0.0)
        self.assertEqual(out["at"], "2030-01-15T12:01:00+00:00")

    def test_same_answer_with_or_without_the_hermes_index(self):
        bare = make_db(self.dir / "bare.db", [("s-cli", "user", CONTENT, NOW - 5 * H),
                                              ("s-tg", "user", CONTENT, NOW - 4 * H)], index=None)
        ts = make_db(self.dir / "ts.db", [("s-cli", "user", CONTENT, NOW - 5 * H),
                                          ("s-tg", "user", CONTENT, NOW - 4 * H)],
                     index="CREATE INDEX idx_ts ON messages(timestamp);")
        hermes = make_db(self.dir / "hermes.db", [("s-cli", "user", CONTENT, NOW - 5 * H),
                                                  ("s-tg", "user", CONTENT, NOW - 4 * H)])
        for db in (bare, ts, hermes):
            self.assertAlmostEqual(om.newest_user_message([db], NOW)["age_h"], 4.0, msg=db.name)


def plan(db):
    """EXPLAIN QUERY PLAN details for the query the reader picks for this store."""
    con = sqlite3.connect(str(db))
    try:
        sql = om.query_for(con)
        return sql, [r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + sql, (NOW,)).fetchall()]
    finally:
        con.close()


class LargeDbGuard(unittest.TestCase):
    """A multi-GB store must not be read row by row: the plan walks an index whenever the store has one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        rows = [("s-cli", "user" if i % 7 == 0 else "assistant", CONTENT, NOW - i) for i in range(2000)]
        self.rows = rows

    def tearDown(self):
        self.tmp.cleanup()

    def test_hermes_schema_walks_idx_messages_session_per_session(self):
        sql, steps = plan(make_db(self.dir / "h.db", self.rows))
        self.assertIn("ORDER BY m.timestamp DESC LIMIT 1", sql)
        self.assertTrue(any("idx_messages_session" in s for s in steps), steps)
        self.assertFalse(any(s.startswith("SCAN m") or s == "SCAN messages" for s in steps), steps)
        self.assertFalse(any("TEMP B-TREE" in s for s in steps), steps)
        con = sqlite3.connect(str(self.dir / "h.db"))  # why: the naive query would scan and sort it all
        naive = [r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + om.FLAT_SQL, (NOW,)).fetchall()]
        con.close()
        self.assertIn("SCAN messages", naive)

    def test_a_timestamp_index_is_walked_backwards_once(self):
        sql, steps = plan(make_db(self.dir / "t.db", self.rows, index="CREATE INDEX idx_ts ON messages(timestamp);"))
        self.assertIn("ORDER BY timestamp DESC LIMIT 1", sql)
        self.assertTrue(any("idx_ts" in s for s in steps), steps)
        self.assertFalse(any("TEMP B-TREE" in s for s in steps), steps)

    def test_a_partial_index_is_not_trusted(self):
        sql, _ = plan(make_db(self.dir / "p.db", self.rows,
                              index="CREATE INDEX idx_p ON messages(timestamp) WHERE role = 'assistant';"))
        self.assertEqual(sql, om.FLAT_SQL)

    def test_no_index_is_the_one_documented_full_scan(self):
        sql, steps = plan(make_db(self.dir / "n.db", self.rows, index=None))
        self.assertEqual(sql, om.FLAT_SQL)
        self.assertTrue(any(s.startswith("SCAN") for s in steps), steps)
        self.assertIn("full scan", om.__doc__.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
