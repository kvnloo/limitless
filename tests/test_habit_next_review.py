"""After a Drop at the week review: at most one words line, "Next up, if you want it: <name>.", through
tier_audit.gate. Nothing after Keep, nothing when the decision is unknown, nothing when the list is exhausted.
No new push and no new job: the line is said where the Drop is logged (bin/limitless-habit-ingest).
Synthetic data only."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_catalogue, jobs, jobs_runner, stop_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-habit-ingest"
CAT = habit_catalogue.CATALOGUE
NOW = 1894708800.0
WEEK = {"habit": CAT[0]["name"], "week_of": "2030-01-08", "checkins": {"2030-01-08": "No"}}


class ReviewLine(unittest.TestCase):
    def test_drop_names_the_next_habit(self):
        line = habit_catalogue.review_line("Drop", [], WEEK)
        self.assertEqual(line, f"Next up, if you want it: {CAT[1]['name']}.")
        self.assertFalse(any(c.isdigit() for c in line))
        self.assertEqual(len(line.splitlines()), 1)

    def test_the_dropped_week_counts_before_its_loop_row_exists(self):
        rows = [{"kind": "loop", "week_of": "2030-01-08", "habit": CAT[0]["name"], "decision": "Drop"}]
        self.assertEqual(habit_catalogue.review_line("Drop", rows, WEEK), habit_catalogue.review_line("Drop", [], WEEK))

    def test_nothing_after_keep_or_unknown(self):
        for d in ("Keep", None, "", "drop it", "your call", "unknown", 1):
            self.assertEqual(habit_catalogue.review_line(d, [], WEEK), "", d)

    def test_nothing_when_the_list_is_exhausted(self):
        rows = [{"kind": "loop", "week_of": f"2030-0{i // 4 + 1}-{i % 4 * 7 + 1:02d}", "habit": h["name"],
                 "decision": "Keep"} for i, h in enumerate(CAT[1:])]
        self.assertEqual(habit_catalogue.review_line("Drop", rows, WEEK), "")

    def test_a_habit_not_on_the_list_still_gets_the_first_untried_one(self):
        self.assertEqual(habit_catalogue.review_line("Drop", [], dict(WEEK, habit="Synthetic habit")),
                         f"Next up, if you want it: {CAT[0]['name']}.")


class WeekNext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.log = self.st / "audit.jsonl"
        self.env = {"LIMITLESS_AUDIT": str(self.log), "LIMITLESS_CONFIG": str(self.st / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_drop_is_gated_and_audited(self):
        line = jobs_runner.week_next(self.st, WEEK, "Drop", env=self.env)
        self.assertEqual(line, f"Next up, if you want it: {CAT[1]['name']}.")
        row = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("week_review:next", "T1", False))
        self.assertNotIn(CAT[1]["name"], self.log.read_text())   # the audit never holds the text

    def test_keep_and_unknown_say_nothing_and_record_nothing(self):
        for d in ("Keep", None):
            self.assertEqual(jobs_runner.week_next(self.st, WEEK, d, env=self.env), "")
        self.assertFalse(self.log.exists())

    def test_reads_the_loop_rows_in_the_state_dir(self):
        stop_rule.record_loop(self.st, dict(WEEK, week_of="2030-01-01", habit=CAT[1]["name"]), "Keep",
                              "2030-01-07T09:00:00+00:00", now=NOW)
        self.assertEqual(jobs_runner.week_next(self.st, WEEK, "Drop", env=self.env),
                         f"Next up, if you want it: {CAT[2]['name']}.")

    def test_a_broken_state_dir_says_nothing(self):
        self.assertEqual(jobs_runner.week_next(self.st / "nowhere", "not a dict", "Drop", env=self.env),
                         f"Next up, if you want it: {CAT[0]['name']}.")
        self.assertEqual(jobs_runner.week_next(None, None, "Drop", env=self.env), "")

    def test_no_new_job(self):
        self.assertEqual(set(jobs.SPECS), {"wake_brief", "nap", "miq", "habit_checkin", "week_review", "break_nudge"})


class IngestCli(unittest.TestCase):
    """bin/limitless-habit-ingest prints the one line after the Drop it logs, and nothing after a Keep."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.now = time.time()
        review_at = self.now - 1800
        day7 = datetime.fromtimestamp(review_at).date()
        self.week_of = (day7 - timedelta(days=6)).isoformat()
        (self.st / "habit.json").write_text(json.dumps({"week_of": self.week_of, "habit": CAT[0]["name"]}))
        (self.st / "jobs-sent.jsonl").write_text(json.dumps({"t": review_at, "k": "x", "job": "week_review"}) + "\n")
        self.db = self.home / "hermes.db"
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def reply(self, text):
        con = sqlite3.connect(str(self.db))
        con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
        con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (self.now - 7200,))
        con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', ?, ?)",
                    (text, self.now - 600))
        con.commit()
        con.close()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), "--db", str(self.db), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_drop_then_one_next_line(self):
        self.reply("Drop")
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        want = f"Next up, if you want it: {CAT[1]['name']}."
        self.assertEqual([ln for ln in r.stdout.splitlines() if ln.startswith("Next up")], [want])
        # a second run logs nothing new and says nothing new
        r = self.run_cli("--write")
        self.assertNotIn("Next up", r.stdout)

    def test_dry_run_says_it_too_and_writes_nothing(self):
        self.reply("drop.")
        before = (self.st / "habit.json").read_bytes()
        r = self.run_cli()
        self.assertIn(f"Next up, if you want it: {CAT[1]['name']}.", r.stdout)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)
        self.assertFalse((self.st / "predictions.jsonl").exists())

    def test_keep_says_nothing_next(self):
        self.reply("Keep")
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("write: Keep", r.stdout)
        self.assertNotIn("Next up", r.stdout)

    def test_no_decision_says_nothing_next(self):
        self.reply("maybe")
        r = self.run_cli("--write")
        self.assertNotIn("Next up", r.stdout)


if __name__ == "__main__":
    unittest.main()
