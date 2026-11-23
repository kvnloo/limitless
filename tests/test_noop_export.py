"""limitless/noop_export.py: wearable sleep summaries and pre-sleep heart rate from a NOOP app DB copy.

Synthetic DBs only (tests/noop_fixture.py: NOOP's public table and column names, made-up rows). UTC stands in
for the local zone. Nothing here sends.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from limitless import noop_export as nx  # noqa: E402
from noop_fixture import IMPORT, PHONE, RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "noop.db"


class ReadOnly(Base):
    def test_the_db_is_never_changed_and_nothing_is_created_beside_it(self):
        d = date(2030, 1, 10)
        on = at(d, 23)
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))], hr=hr_before(RING, on, 60))
        con = sqlite3.connect(str(self.db))
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        os.utime(self.db, (1_000_000_000, 1_000_000_000))
        before, mtime = self.db.read_bytes(), self.db.stat().st_mtime_ns
        got = nx.read(self.db, tz=UTC)
        self.assertIsNone(got["reason"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.db.stat().st_mtime_ns, mtime)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["noop.db"])

    def test_the_uri_is_read_only_and_immutable(self):
        uri = nx.uri(self.dir / "a b.db")
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro&immutable=1"))
        self.assertIn("a%20b.db", uri)

    def test_a_missing_file_is_one_plain_reason(self):
        got = nx.read(self.dir / "absent.db", tz=UTC)
        self.assertEqual(got["reason"], nx.NO_FILE)
        self.assertEqual((got["sleep"], got["presleep"]), ([], []))
        self.assertFalse((self.dir / "absent.db").exists())

    def test_a_file_that_is_not_sqlite_is_one_plain_reason(self):
        self.db.write_text("not a database\n" * 20)
        self.assertEqual(nx.read(self.db, tz=UTC)["reason"], nx.NOT_NOOP)


class Schema(Base):
    def test_a_missing_table_is_named_and_nothing_is_read(self):
        for table in ("sleepSession", "hrSample", "pairedDevice"):
            with self.subTest(table=table):
                make_db(self.db, drop=table)
                got = nx.read(self.db, tz=UTC)
                self.assertEqual(got["reason"], f"{nx.SCHEMA_PREFIX}no table {table}")
                self.assertEqual((got["sleep"], got["presleep"]), ([], []))
                self.db.unlink()

    def test_a_missing_column_is_named(self):
        for table, col in (("sleepSession", "endTs"), ("sleepSession", "stagesJSON"),
                           ("pairedDevice", "sourceKind")):
            with self.subTest(column=col):
                make_db(self.db, drop_column=(table, col))
                self.assertEqual(nx.read(self.db, tz=UTC)["reason"], f"{nx.SCHEMA_PREFIX}no column {table}.{col}")
                self.db.unlink()

    def test_optional_parts_may_be_missing(self):
        d = date(2030, 1, 10)
        on = at(d, 23)
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))], drop="dismissedSleep")
        self.assertIsNone(nx.read(self.db, tz=UTC)["reason"])
        self.db.unlink()
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))],
                drop_column=("sleepSession", "startTsAdjusted"))
        self.assertIsNone(nx.read(self.db, tz=UTC)["reason"])


if __name__ == "__main__":
    unittest.main()
