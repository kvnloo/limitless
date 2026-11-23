"""anki.reviews: count Anki's own review log rows in a time range, opened read-only.

Synthetic only: each test builds a tiny sqlite file with a ``revlog`` table (id = epoch ms, as in Anki).
No real collection is ever committed. Missing, locked or malformed input is unknown with a path-free reason,
never zero and never a traceback.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import anki  # noqa: E402

T0 = 1894708800.0   # a synthetic clock


def collection(path: Path, stamps_s=(), ease=3, wal=False) -> Path:
    """A minimal synthetic collection: a revlog table with one row per epoch second in ``stamps_s``."""
    con = sqlite3.connect(str(path))
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE revlog (id integer primary key, cid integer not null, usn integer not null, "
                "ease integer not null, ivl integer not null, lastIvl integer not null, factor integer not null, "
                "time integer not null, type integer not null)")
    for i, s in enumerate(stamps_s):
        e = ease[i] if isinstance(ease, (list, tuple)) else ease
        con.execute("INSERT INTO revlog VALUES (?, 1, 0, ?, 1, 0, 2500, 4000, 1)", (int(s * 1000), e))
    con.commit()
    con.close()
    return path


class Reviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_rows_in_the_range_only(self):
        db = collection(self.dir / "c.anki2", [T0 - 10, T0 + 1, T0 + 3600, T0 + 7200, T0 + 9000])
        got = anki.reviews(db, T0, T0 + 9000)
        self.assertEqual(got["count"], 3)            # [since, until): the row at until is out
        self.assertIsNone(got["reason"])
        self.assertEqual(got["newest_s"], T0 + 7200)
        self.assertEqual(got["stamps_s"], [T0 + 1, T0 + 3600, T0 + 7200])

    def test_a_known_empty_range_is_zero_not_unknown(self):
        db = collection(self.dir / "c.anki2", [T0 - 86400])
        got = anki.reviews(db, T0, T0 + 3600)
        self.assertEqual(got["count"], 0)
        self.assertIsNone(got["reason"])
        self.assertEqual(got["newest_s"], T0 - 86400)   # the newest review before until, for age_h

    def test_manual_reschedules_are_not_reviews(self):
        db = collection(self.dir / "c.anki2", [T0 + 1, T0 + 2], ease=[3, 0])   # ease 0: set due date, no answer
        self.assertEqual(anki.reviews(db, T0, T0 + 10)["count"], 1)

    def test_missing_path_or_file_is_unknown(self):
        for p in (None, "", self.dir / "nowhere.anki2", self.dir):
            got = anki.reviews(p, T0, T0 + 10)
            self.assertIsNone(got["count"], p)
            self.assertTrue(got["reason"], p)
            self.assertNotIn(str(self.dir), got["reason"])

    def test_malformed_db_is_unknown_with_a_path_free_reason(self):
        bad = self.dir / "bad.anki2"
        bad.write_bytes(b"this is not a sqlite file at all" * 64)
        empty = self.dir / "empty.anki2"
        sqlite3.connect(str(empty)).execute("CREATE TABLE notes (id integer)").connection.close()
        for p in (bad, empty):
            got = anki.reviews(p, T0, T0 + 10)
            self.assertIsNone(got["count"], p)
            self.assertNotIn(str(self.dir), got["reason"])
            self.assertNotIn("Traceback", got["reason"])

    def test_a_locked_db_is_unknown_not_zero(self):
        db = collection(self.dir / "c.anki2", [T0 + 1])
        holder = sqlite3.connect(str(db), isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        try:
            got = anki.reviews(db, T0, T0 + 10, timeout_s=0.05)
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertIsNone(got["count"])
        self.assertIn("locked", got["reason"])
        self.assertNotIn(str(self.dir), got["reason"])

    def test_never_writes_the_collection(self):
        db = collection(self.dir / "c.anki2", [T0 + 1, T0 + 2], wal=True)
        before = (db.read_bytes(), db.stat().st_mtime_ns)
        names = set(os.listdir(self.dir))
        anki.reviews(db, T0, T0 + 10)
        anki.reviews(db, T0, T0 + 10, immutable=True)
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns), before)
        self.assertEqual(set(os.listdir(self.dir)) - names, set())   # no journal, -wal or -shm left behind

    def test_reads_a_wal_collection_anki_has_open(self):
        db = collection(self.dir / "c.anki2", [T0 + 1], wal=True)
        live = sqlite3.connect(str(db))          # Anki running: -wal and -shm exist and hold a new answer
        live.execute("INSERT INTO revlog VALUES (?, 1, 0, 3, 1, 0, 2500, 4000, 1)", (int((T0 + 2) * 1000),))
        live.commit()
        try:
            self.assertTrue(Path(str(db) + "-wal").exists())
            self.assertEqual(anki.reviews(db, T0, T0 + 10)["count"], 2)
        finally:
            live.close()

    def test_the_uri_is_read_only_and_immutable_only_for_a_copy(self):
        p = self.dir / "a b#c?.anki2"
        self.assertTrue(anki._uri(p, immutable=False).endswith("?mode=ro"))
        self.assertTrue(anki._uri(p, immutable=True).endswith("?mode=ro&immutable=1"))
        self.assertNotIn("#", anki._uri(p, immutable=False))
        self.assertNotIn(" ", anki._uri(p, immutable=False))

    def test_a_copy_reads_with_immutable(self):
        db = collection(self.dir / "copy.anki2", [T0 + 1, T0 + 5])
        self.assertEqual(anki.reviews(db, T0, T0 + 10, immutable=True)["count"], 2)

    def test_a_bad_range_is_unknown(self):
        db = collection(self.dir / "c.anki2", [T0 + 1])
        for lo, hi in ((None, T0), (T0, "x"), (T0 + 10, T0), (float("nan"), T0)):
            self.assertIsNone(anki.reviews(db, lo, hi)["count"], (lo, hi))


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.none = {"LIMITLESS_CONFIG": str(self.dir / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_none_by_default(self):
        self.assertIsNone(anki.collection_path(self.none))
        got = anki.reviews(anki.collection_path(self.none), T0, T0 + 10)
        self.assertEqual(got["reason"], anki.NO_COLLECTION)
        self.assertEqual(anki.NO_COLLECTION, "no Anki collection set")

    def test_env_then_config(self):
        cfg = self.dir / "config.json"
        cfg.write_text('{"anki_collection": "~/synthetic/collection.anki2", "anki_copy": true}')
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(anki.collection_path(env, home=self.dir), self.dir / "synthetic" / "collection.anki2")
        self.assertTrue(anki.is_copy(env))
        env["LIMITLESS_ANKI"] = str(self.dir / "other.anki2")
        self.assertEqual(anki.collection_path(env), self.dir / "other.anki2")
        self.assertFalse(anki.is_copy(self.none))


if __name__ == "__main__":
    unittest.main()
