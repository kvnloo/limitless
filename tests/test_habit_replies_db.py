"""habit_replies.replies_from_hermes_db against a synthetic Hermes session store. Synthetic data only.

The tables keep the columns the reader uses, with the types and constraints of NousResearch/hermes-agent
hermes_state.py (v2026.4.13, 1af2e18) and persistence/sqlite/_schema_ddl.py (0f602c5).
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_replies  # noqa: E402

T0 = 1894708800.0
SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    started_at REAL NOT NULL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL
);
"""


def make_db(path, sessions, messages):
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)", sessions)
    con.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)", messages)
    con.commit()
    con.close()


class HermesDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "state.db"
        make_db(self.db, [("s-tg", "telegram", T0 - 100), ("s-cli", "cli", T0 - 100)], [
            ("s-tg", "user", "synthetic before", T0 - 10),
            ("s-tg", "assistant", "Did you do it today? Reply Done, No or Skip.", T0),
            ("s-tg", "user", "Done", T0 + 60),
            ("s-tg", "tool", "No", T0 + 61),
            ("s-cli", "user", "Skip", T0 + 62),
            ("s-tg", "user", None, T0 + 63),
            ("s-tg", "user", "no", T0 + 30),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_user_messages_from_the_source_after_since_oldest_first(self):
        self.assertEqual(habit_replies.replies_from_hermes_db(self.db, T0), [(T0 + 30, "no"), (T0 + 60, "Done")])

    def test_other_source(self):
        self.assertEqual(habit_replies.replies_from_hermes_db(self.db, T0, source="cli"), [(T0 + 62, "Skip")])

    def test_since_is_exclusive(self):
        self.assertEqual(habit_replies.replies_from_hermes_db(self.db, T0 + 30), [(T0 + 60, "Done")])

    def test_read_only_leaves_the_file_as_it_was(self):
        before = (self.db.read_bytes(), sorted(p.name for p in self.dir.iterdir()))
        habit_replies.replies_from_hermes_db(self.db, T0)
        self.assertEqual((self.db.read_bytes(), sorted(p.name for p in self.dir.iterdir())), before)

    def test_opened_with_a_read_only_uri(self):
        seen = []
        real = sqlite3.connect

        def spy(db, *a, **kw):
            seen.append((db, kw.get("uri")))
            return real(db, *a, **kw)
        habit_replies.sqlite3.connect = spy
        try:
            habit_replies.replies_from_hermes_db(self.db, T0)
        finally:
            habit_replies.sqlite3.connect = real
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0][0].startswith("file:") and seen[0][0].endswith("?mode=ro") and seen[0][1])

    def test_missing_or_broken_db_reads_as_no_replies(self):
        self.assertEqual(habit_replies.replies_from_hermes_db(self.dir / "absent.db", T0), [])
        self.assertEqual(habit_replies.replies_from_hermes_db(None, T0), [])
        junk = self.dir / "junk.db"
        junk.write_bytes(b"not a database at all, synthetic" * 10)
        self.assertEqual(habit_replies.replies_from_hermes_db(junk, T0), [])
        empty = self.dir / "empty.db"
        sqlite3.connect(str(empty)).close()
        self.assertEqual(habit_replies.replies_from_hermes_db(empty, T0), [])
        self.assertFalse((self.dir / "absent.db").exists())

    def test_replies_feed_ingest(self):
        st = self.dir / "state"
        st.mkdir()
        (st / "habit.json").write_text(json.dumps({"week_of": "2030-01-11", "habit": "Synthetic habit"}))
        (st / "jobs-sent.jsonl").write_text(json.dumps({"t": T0 + 20, "k": "x", "job": "habit_checkin"}) + "\n")
        replies = habit_replies.replies_from_hermes_db(self.db, T0 + 20)
        habit_replies.ingest(st, replies, T0 + 3600, tz=habit_replies.timezone.utc)
        self.assertEqual(json.loads((st / "habit.json").read_text())["checkins"], {"2030-01-15": "No"})


class DbPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.cfg = self.home / "config.json"
        self.st = self.home / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, env=None, arg=None):
        env = dict({"LIMITLESS_CONFIG": str(self.cfg)}, **(env or {}))
        return habit_replies.hermes_db_path(self.st, env=env, home=self.home, arg=arg)

    def test_none_by_default(self):
        self.assertIsNone(self.path())

    def test_config_key_relative_to_the_state_dir(self):
        self.cfg.write_text(json.dumps({"hermes_db": "hermes/state.db"}))
        self.assertEqual(self.path(), self.st / "hermes/state.db")

    def test_env_beats_config_and_arg_beats_env(self):
        self.cfg.write_text(json.dumps({"hermes_db": "cfg.db"}))
        self.assertEqual(self.path({"LIMITLESS_HERMES_DB": str(self.home / "env.db")}), self.home / "env.db")
        self.assertEqual(self.path({"LIMITLESS_HERMES_DB": str(self.home / "env.db")}, arg=str(self.home / "a.db")),
                         self.home / "a.db")


if __name__ == "__main__":
    unittest.main()
