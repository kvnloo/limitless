"""bin/limitless-habit-ingest end to end in a temp HOME with a synthetic Hermes DB. Synthetic data only."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-habit-ingest"


class HabitIngestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        self.sent_at = now - 1800
        self.day = datetime.fromtimestamp(self.sent_at).date().isoformat()
        (self.st / "habit.json").write_text(json.dumps({"week_of": self.day, "habit": "Synthetic habit", "keep": 1}))
        (self.st / "jobs-sent.jsonl").write_text(
            json.dumps({"t": self.sent_at, "k": "x", "job": "habit_checkin"}) + "\n")
        self.db = self.home / "hermes.db"
        con = sqlite3.connect(str(self.db))
        con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
        con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (now - 7200,))
        con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', ?, ?)",
                    ("Done synthetic-private-words", now - 600))
        con.commit()
        con.close()
        self.cfg = self.home / "config.json"
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **(env or {}))),
                              capture_output=True, text=True, timeout=60)

    def habit(self):
        return json.loads((self.st / "habit.json").read_text())

    def test_no_db_configured_does_nothing_and_says_so(self):
        before = (self.st / "habit.json").read_bytes()
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no Hermes DB", r.stdout)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)

    def test_dry_run_by_default_prints_what_it_would_write(self):
        before = (self.st / "habit.json").read_bytes()
        r = self.run_cli("--db", str(self.db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{self.day}: would write: Done", r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)

    def test_write_writes_and_keeps_other_keys(self):
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{self.day}: write: Done", r.stdout)
        self.assertEqual(self.habit(), {"week_of": self.day, "habit": "Synthetic habit", "keep": 1,
                                        "checkins": {self.day: "Done"}})
        again = self.run_cli("--db", str(self.db), "--write")
        self.assertIn(f"{self.day}: keep: Done", again.stdout)

    def test_db_from_env_or_config(self):
        r = self.run_cli("--write", env={"LIMITLESS_HERMES_DB": str(self.db)})
        self.assertEqual(self.habit()["checkins"], {self.day: "Done"}, r.stdout + r.stderr)
        (self.st / "habit.json").write_text(json.dumps({"week_of": self.day, "habit": "Synthetic habit"}))
        self.cfg.write_text(json.dumps({"hermes_db": str(self.db)}))
        r = self.run_cli("--write")
        self.assertEqual(self.habit()["checkins"], {self.day: "Done"}, r.stdout + r.stderr)

    def test_never_echoes_the_reply(self):
        r = self.run_cli("--db", str(self.db))
        self.assertNotIn("synthetic-private-words", r.stdout + r.stderr)

    def test_no_check_in_sent_says_so(self):
        (self.st / "jobs-sent.jsonl").unlink()
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no habit check-in sent yet", r.stdout)
        self.assertNotIn("checkins", self.habit())

    def test_bad_args_print_usage(self):
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: limitless-habit-ingest", r.stderr)


if __name__ == "__main__":
    unittest.main()
