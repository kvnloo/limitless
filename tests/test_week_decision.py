"""A Keep or Drop reply after the week review closes the habit week. Synthetic data only; nothing sends.

The first Keep or Drop (first word, case-insensitive, trailing punctuation or one emoji ignored) after
the latest week review of this week (sent on or after its day seven, at or before ``now``, and no more
than DECISION_REPLY_S before the reply) writes ``decision`` and ``decided_at`` into habit.json, atomically,
with every other key kept. Dry run by default. No reply, or any other reply, writes nothing: the week stays
undecided, never a Drop. A decision already in habit.json is never overwritten.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_replies, jobs  # noqa: E402

UTC = timezone.utc
H = 3600.0
DAY_S = 24 * H
REVIEW_AT = 2_000_000_000.0                       # the week review send, on day seven
TODAY = datetime.fromtimestamp(REVIEW_AT, UTC).date()
WEEK_OF = (TODAY - timedelta(days=6)).isoformat()
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-habit-ingest"


def iso(t):
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds")


class Words(unittest.TestCase):
    def test_keep_and_drop_first_word(self):
        for text, want in [("Keep", "Keep"), ("keep!", "Keep"), ("DROP.", "Drop"), ("Drop \U0001F44D", "Drop"),
                           ("Keep\U0001F44D", "Keep"), ("keep it going", "Keep")]:
            self.assertEqual(habit_replies.decision(text), want, text)

    def test_anything_else_is_no_decision(self):
        for text in ("Done", "No", "Skip", "keeping", "maybe", "", "   ", None, 7, "drop-ish", "K"):
            self.assertIsNone(habit_replies.decision(text), repr(text))

    def test_latest_review_only_counts_week_review_sends_until_now(self):
        log = [{"t": REVIEW_AT - DAY_S, "job": "habit_checkin"}, {"t": REVIEW_AT, "job": "week_review"},
               {"t": REVIEW_AT + 10, "job": "week_review"}, {"t": True, "job": "week_review"}, "junk"]
        self.assertEqual(habit_replies.latest_review(log, REVIEW_AT + 5), REVIEW_AT)
        self.assertIsNone(habit_replies.latest_review(log, REVIEW_AT - 1))


class Decide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.habit_obj = {"week_of": WEEK_OF, "habit": "Synthetic habit", "start": "Synthetic start",
                          "checkins": {WEEK_OF: "Done"}, "keep": 1}
        self.write_habit(self.habit_obj)
        self.sent([{"t": REVIEW_AT, "k": "x", "job": "week_review"}])

    def tearDown(self):
        self.tmp.cleanup()

    def write_habit(self, obj):
        (self.st / "habit.json").write_text(json.dumps(obj))

    def sent(self, rows):
        (self.st / "jobs-sent.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def habit(self):
        return json.loads((self.st / "habit.json").read_text())

    def decide(self, replies, now=REVIEW_AT + 2 * H, **kw):
        return habit_replies.decide(self.st, replies, now, tz=UTC, **kw)

    def test_dry_run_is_the_default_and_writes_nothing(self):
        before = (self.st / "habit.json").read_bytes()
        rows = self.decide([(REVIEW_AT + 60, "Keep")])
        self.assertEqual([(r["action"], r["answer"]) for r in rows], [(habit_replies.WOULD_WRITE, "Keep")])
        self.assertEqual((self.st / "habit.json").read_bytes(), before)

    def test_keep_writes_decision_and_decided_at_keeping_every_other_key(self):
        rows = self.decide([(REVIEW_AT + 60, "Keep")], dry_run=False)
        self.assertEqual(rows[0]["action"], habit_replies.WRITE)
        self.assertEqual(rows[0]["week_of"], WEEK_OF)
        self.assertEqual(self.habit(), dict(self.habit_obj, decision="Keep", decided_at=iso(REVIEW_AT + 60)))

    def test_drop_writes_drop(self):
        self.decide([(REVIEW_AT + 60, "drop.")], dry_run=False)
        self.assertEqual(self.habit()["decision"], "Drop")

    def test_first_decision_wins_and_is_never_overwritten(self):
        rows = self.decide([(REVIEW_AT + 60, "Keep"), (REVIEW_AT + 120, "Drop")], dry_run=False)
        self.assertEqual([r["action"] for r in rows], [habit_replies.WRITE, habit_replies.KEEP])
        again = self.decide([(REVIEW_AT + 180, "Drop")], dry_run=False)
        self.assertEqual(self.habit()["decision"], "Keep")
        self.assertEqual([r["action"] for r in again], [habit_replies.KEEP])
        self.assertIn("already says Keep", again[0]["reason"])

    def test_no_reply_or_another_reply_stays_undecided_never_drop(self):
        before = (self.st / "habit.json").read_bytes()
        self.assertEqual(self.decide([], dry_run=False)[0]["action"], habit_replies.NOTHING)
        rows = self.decide([(REVIEW_AT + 60, "Done"), (REVIEW_AT + 90, "not sure")], dry_run=False)
        self.assertEqual([r["action"] for r in rows], [habit_replies.IGNORE, habit_replies.IGNORE])
        self.assertEqual((self.st / "habit.json").read_bytes(), before)
        self.assertNotIn("decision", self.habit())

    def test_reply_before_the_review_or_after_it_expired_is_ignored(self):
        rows = self.decide([(REVIEW_AT - 60, "Keep"), (REVIEW_AT + habit_replies.DECISION_REPLY_S + 60, "Keep")],
                           now=REVIEW_AT + 2 * DAY_S, dry_run=False)
        self.assertEqual([r["action"] for r in rows], [habit_replies.IGNORE, habit_replies.IGNORE])
        self.assertNotIn("decision", self.habit())

    def test_no_review_sent_for_this_week_logs_nothing(self):
        self.sent([{"t": REVIEW_AT, "k": "x", "job": "habit_checkin"}])
        rows = self.decide([(REVIEW_AT + 60, "Keep")], dry_run=False)
        self.assertEqual([r["action"] for r in rows], [habit_replies.NOTHING])
        # a review sent for an earlier week (before this week's day seven) is not this week's
        self.sent([{"t": REVIEW_AT - 3 * DAY_S, "k": "x", "job": "week_review"}])
        rows = self.decide([(REVIEW_AT - 3 * DAY_S + 60, "Keep")], dry_run=False)
        self.assertEqual([r["action"] for r in rows], [habit_replies.NOTHING])
        self.assertNotIn("decision", self.habit())

    def test_no_habit_logs_nothing(self):
        (self.st / "habit.json").unlink()
        self.assertEqual(self.decide([(REVIEW_AT + 60, "Keep")], dry_run=False)[0]["action"], habit_replies.NOTHING)

    def test_rows_never_echo_the_reply(self):
        rows = self.decide([(REVIEW_AT + 60, "Keep synthetic-private-words"), (REVIEW_AT + 90, "other synthetic words")])
        self.assertNotIn("synthetic", json.dumps(rows))

    def test_a_done_reply_to_the_review_is_not_a_checkin(self):
        # the Done/No/Skip ingest only reads replies to the check-in; the review's reply leaves check-ins alone
        self.decide([(REVIEW_AT + 60, "Keep")], dry_run=False)
        self.assertEqual(self.habit()["checkins"], {WEEK_OF: "Done"})


class IngestCli(unittest.TestCase):
    """bin/limitless-habit-ingest also logs a Keep / Drop reply to the week review; dry run unless --write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        self.review_at = now - 1800
        day7 = datetime.fromtimestamp(self.review_at).date()
        self.week_of = (day7 - timedelta(days=6)).isoformat()
        (self.st / "habit.json").write_text(json.dumps({"week_of": self.week_of, "habit": "Synthetic habit"}))
        (self.st / "jobs-sent.jsonl").write_text(json.dumps({"t": self.review_at, "k": "x", "job": "week_review"}) + "\n")
        self.db = self.home / "hermes.db"
        con = sqlite3.connect(str(self.db))
        con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
        con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (now - 7200,))
        con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', ?, ?)",
                    ("Drop", now - 600))
        con.commit()
        con.close()
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), "--db", str(self.db), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def habit(self):
        return json.loads((self.st / "habit.json").read_text())

    def test_dry_run_says_it_would_write_the_decision(self):
        before = (self.st / "habit.json").read_bytes()
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"week of {self.week_of}: would write: Drop", r.stdout)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)

    def test_write_records_the_decision(self):
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"week of {self.week_of}: write: Drop", r.stdout)
        self.assertEqual(self.habit()["decision"], "Drop")
        self.assertIn("decided_at", self.habit())


if __name__ == "__main__":
    unittest.main()
