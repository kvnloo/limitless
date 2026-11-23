"""The habit check-in gains one plain line from the phone's feed-app hint; the tap stays the person's.

Synthetic AW DBs (tests/test_aw_reader.make_db) and synthetic app names only. NOW is an arbitrary
epoch; only differences between times matter. Pushes go to a fake sender; nothing really sends.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import feeds_evidence, jobs, jobs_runner  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
WAKE = NOW - 1.2 * H                     # the habit cue (WAKE + 1 h) came 0.2 h ago
EVENING = WAKE - 9 * H                   # the last action before a quiet night
HABIT = {"habit": "Synthetic habit", "week_of": date.fromtimestamp(NOW).isoformat(), "checkins": {}}
SEEN_LINE = "Phone: a feed app was opened in that hour"
NOT_SEEN_LINE = "Phone: no feed app seen in that hour"


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body):
        self.calls.append((title, body))
        return "telegram"


class Body(unittest.TestCase):
    def test_seen_adds_one_line(self):
        plain = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT)
        got = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT, phone={"seen": True, "count": 3})
        self.assertEqual(got, plain + "\n" + SEEN_LINE)

    def test_not_seen_adds_one_line(self):
        plain = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT)
        got = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT, phone={"seen": False, "count": 0})
        self.assertEqual(got, plain + "\n" + NOT_SEEN_LINE)

    def test_unknown_adds_nothing(self):
        plain = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT)
        for phone in (None, {}, {"seen": None, "count": 2}):
            self.assertEqual(jobs_runner.body(jobs.HABIT_CHECKIN, HABIT, phone=phone), plain)

    def test_line_has_no_digits_and_the_taps_stay(self):
        for seen in (True, False):
            line = feeds_evidence.line({"seen": seen, "count": 7})
            self.assertIsNone(re.search(r"\d", line), line)
            got = jobs_runner.body(jobs.HABIT_CHECKIN, HABIT, phone={"seen": seen, "count": 7})
            self.assertIn("Reply Done, No or Skip.", got)

    def test_other_jobs_never_get_the_line(self):
        for spec in (jobs.WAKE_BRIEF, jobs.NAP, jobs.MIQ):
            self.assertEqual(jobs_runner.body(spec, HABIT, phone={"seen": True, "count": 1}),
                             jobs_runner.body(spec, HABIT))


class RunOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.st / "aw.db"
        (self.st / "habit.json").write_text(json.dumps(HABIT))
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json"), "LIMITLESS_AW_DB": str(self.db),
                    "LIMITLESS_FEED_APPS": "feedapp"}

    def tearDown(self):
        self.tmp.cleanup()

    def checkin(self, env):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=env, home=self.root)
        row = {r["job"]: r for r in rows}["Habit check-in"]
        self.assertEqual(row["action"], jobs.DELIVER, row)
        bodies = [b for t, b in push.calls if t == "Habit check-in"]
        self.assertEqual(len(bodies), 1, push.calls)
        return bodies[0]

    def plain(self):
        return jobs_runner.body(jobs.HABIT_CHECKIN, HABIT)

    def test_feed_app_in_the_hour(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        self.assertEqual(self.checkin(self.env), self.plain() + "\n" + SEEN_LINE)

    def test_no_feed_app_in_the_hour(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "reader"), (WAKE + H + 60, WAKE + H + 90, "feedapp")])
        self.assertEqual(self.checkin(self.env), self.plain() + "\n" + NOT_SEEN_LINE)

    def test_data_short_of_the_hour_says_nothing(self):
        make_db(self.db, unlocks=[EVENING, WAKE], spans=[(WAKE + 600, WAKE + 900, "reader")])
        self.assertEqual(self.checkin(self.env), self.plain())

    def test_no_feed_list_says_nothing(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        env = {k: v for k, v in self.env.items() if k != "LIMITLESS_FEED_APPS"}
        self.assertEqual(self.checkin(env), self.plain())

    def test_feed_list_from_config(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"aw_db": "aw.db", "feed_apps": ["feedapp"]}))
        self.assertEqual(self.checkin({"LIMITLESS_CONFIG": str(cfg)}), self.plain() + "\n" + SEEN_LINE)

    def test_the_hint_never_writes_habit_json_or_logs_an_answer(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "reader"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        before = (self.st / "habit.json").read_bytes()
        self.checkin(self.env)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)
        sent = [json.loads(x) for x in (self.st / jobs_runner.SENT_LOG).read_text().splitlines()]
        self.assertEqual({tuple(sorted(e)) for e in sent}, {("job", "k", "t")})

    def test_dry_run_sends_nothing(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        push = FakePush()
        jobs_runner.run_once(self.st, NOW, push=push, dry_run=True, env=self.env, home=self.root)
        self.assertEqual(push.calls, [])


if __name__ == "__main__":
    unittest.main()
