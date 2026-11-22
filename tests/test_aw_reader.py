"""ActivityWatch-for-Android SQLite rows as the person's own actions (unlocks and app spans).

Synthetic DBs only, built here with the ActivityWatch schema. NOW is an arbitrary epoch; only
differences between times matter.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import aw_reader  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
NS = 1_000_000_000

SCHEMA = """
CREATE TABLE buckets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, client TEXT, hostname TEXT,
                     created TEXT, data TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, bucketrow INTEGER REFERENCES buckets(id), starttime INTEGER,
                    endtime INTEGER, data TEXT);
"""


def make_db(path, unlocks=(), spans=(), unlock_bucket="b-unlock", window_bucket="b-window"):
    """A synthetic AW DB: ``unlocks`` are epoch seconds, ``spans`` are (start_s, end_s, app)."""
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, ?, 'os.lockscreen.unlocks', 'test', 'test-host', '', '{}')",
                (unlock_bucket,))
    con.execute("INSERT INTO buckets VALUES (2, ?, 'currentwindow', 'test', 'test-host', '', '{}')",
                (window_bucket,))
    for t in unlocks:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, '{}')",
                    (int(t * NS), int(t * NS)))
    for s, e, app in spans:
        data = json.dumps({"app": app, "classname": app + ".Main", "package": "org.example." + app})
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (2, ?, ?, ?)",
                    (int(s * NS), int(e * NS), data))
    con.commit()
    con.close()


class PersonRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "aw.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_unlocks_and_span_starts_in_seconds(self):
        make_db(self.db, unlocks=[NOW - 9 * H, NOW - H],
                spans=[(NOW - 9 * H + 10, NOW - 9 * H + 60, "reader")])
        rows = aw_reader.person_rows(self.db)
        self.assertEqual(rows, [
            {"ts": NOW - 9 * H, "type": "KEYGUARD_HIDDEN"},
            {"ts": NOW - 9 * H + 10, "type": "USER_INTERACTION"},
            {"ts": NOW - H, "type": "KEYGUARD_HIDDEN"},
        ])

    def test_buckets_found_by_type_not_name(self):
        make_db(self.db, unlocks=[NOW], spans=[(NOW + 1, NOW + 2, "a")],
                unlock_bucket="anything-1", window_bucket="anything-2")
        types = [r["type"] for r in aw_reader.person_rows(self.db)]
        self.assertEqual(types, ["KEYGUARD_HIDDEN", "USER_INTERACTION"])

    def test_other_bucket_types_ignored(self):
        make_db(self.db, unlocks=[NOW])
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO buckets VALUES (3, 'n', 'os.notifications', 'test', 'h', '', '{}')")
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (3, ?, ?, '{}')",
                    (int((NOW + 5) * NS), int((NOW + 5) * NS)))
        con.commit()
        con.close()
        self.assertEqual(aw_reader.person_rows(self.db), [{"ts": NOW, "type": "KEYGUARD_HIDDEN"}])

    def test_default_bound_is_three_days_before_newest_row(self):
        make_db(self.db, unlocks=[NOW - 5 * 24 * H, NOW - 2 * 24 * H, NOW])
        ts = [r["ts"] for r in aw_reader.person_rows(self.db)]
        self.assertEqual(ts, [NOW - 2 * 24 * H, NOW])

    def test_since_s_limits_rows(self):
        make_db(self.db, unlocks=[NOW - 5 * H, NOW - 3 * H, NOW])
        ts = [r["ts"] for r in aw_reader.person_rows(self.db, since_s=NOW - 4 * H)]
        self.assertEqual(ts, [NOW - 3 * H, NOW])

    def test_read_never_writes_the_db(self):
        make_db(self.db, unlocks=[NOW - 9 * H, NOW], spans=[(NOW + 1, NOW + 2, "a")])
        before = (self.db.stat().st_mtime_ns, self.db.read_bytes())
        entries = sorted(p.name for p in self.db.parent.iterdir())
        aw_reader.person_rows(self.db)
        aw_reader.person_rows(self.db, since_s=NOW - H)
        self.assertEqual((self.db.stat().st_mtime_ns, self.db.read_bytes()), before)
        self.assertEqual(sorted(p.name for p in self.db.parent.iterdir()), entries)   # no -wal/-journal left

    def test_missing_file_is_empty(self):
        self.assertEqual(aw_reader.person_rows(self.db), [])
        self.assertFalse(self.db.exists())          # read-only open never creates the file
        self.assertEqual(aw_reader.person_rows(None), [])

    def test_missing_tables_is_empty(self):
        sqlite3.connect(str(self.db)).close()
        self.assertEqual(aw_reader.person_rows(self.db), [])

    def test_not_a_database_is_empty(self):
        self.db.write_bytes(b"not sqlite at all" * 100)
        self.assertEqual(aw_reader.person_rows(self.db), [])

    def test_bad_rows_are_skipped_and_never_raise(self):
        make_db(self.db, unlocks=[NOW])
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (2, ?, ?, '{bad')",
                    (int((NOW + 5) * NS), int((NOW + 6) * NS)))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, 'x', NULL, NULL)")
        con.commit()
        con.close()
        self.assertEqual(aw_reader.person_rows(self.db), [{"ts": NOW, "type": "KEYGUARD_HIDDEN"}])

    def test_only_bad_json_is_empty(self):
        make_db(self.db)
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (2, ?, ?, '[1,')",
                    (int(NOW * NS), int(NOW * NS)))
        con.commit()
        con.close()
        self.assertEqual(aw_reader.person_rows(self.db), [])

    def test_locked_db_is_empty(self):
        make_db(self.db, unlocks=[NOW])
        con = sqlite3.connect(str(self.db), isolation_level=None)
        con.execute("BEGIN EXCLUSIVE")
        try:
            self.assertEqual(aw_reader.person_rows(self.db), [])
        finally:
            con.execute("ROLLBACK")
            con.close()


if __name__ == "__main__":
    unittest.main()
