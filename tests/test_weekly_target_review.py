"""The week review gains one words-only weekly target line under its "N of M logged days" line.

Synthetic habit weeks; NOW is an arbitrary epoch; pushes go to a fake sender, nothing really sends.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, one_tap, weekly_target  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "Reply: Keep / Drop"


def week(days_back=6, done=0, no=0):
    """A habit.json whose week_of is ``days_back`` days ago: ``done`` Done days, then ``no`` No days."""
    start = TODAY - timedelta(days=days_back)
    words = ["Done"] * done + ["No"] * no
    return {"habit": "Synthetic habit", "week_of": start.isoformat(),
            "checkins": {(start + timedelta(days=i)).isoformat(): w for i, w in enumerate(words)}}


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body))
        return "telegram"


class Line(unittest.TestCase):
    def test_words(self):
        self.assertEqual(weekly_target.REVIEW_REACHED, "habit: target reached this week")
        self.assertEqual(weekly_target.REVIEW_ON_THE_WAY, "habit: on the way")
        for line in (weekly_target.REVIEW_REACHED, weekly_target.REVIEW_ON_THE_WAY):
            self.assertIsNone(re.search(r"\d", line))

    def test_on_the_way_under_the_number(self):
        h = week(done=2, no=3)
        lines = jobs_runner.body(jobs.WEEK_REVIEW, h).splitlines()
        self.assertEqual(lines, [jobs.week_review_text(h), "habit: on the way", KD])
        self.assertEqual(lines[0], "Synthetic habit: 2 of 5 logged days this week.")   # the number stays

    def test_reached(self):
        h = week(done=4, no=3)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, h).splitlines(),
                         [jobs.week_review_text(h), "habit: target reached this week", KD])

    def test_no_done_day_adds_no_line(self):
        for h in (week(), week(no=7), None, {}):
            self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, h), jobs.week_review_text(h) + "\n" + KD, h)

    def test_target_days_changes_only_the_words(self):
        h = week(done=2)
        self.assertIn("habit: on the way", jobs_runner.body(jobs.WEEK_REVIEW, h))
        self.assertIn("habit: target reached this week", jobs_runner.body(jobs.WEEK_REVIEW, h, target_days=2))

    def test_sync_done_days_count(self):
        h = week()
        synced = {(TODAY - timedelta(days=6 - i)).isoformat(): "met" for i in range(4)}
        self.assertIn("habit: target reached this week", jobs_runner.body(jobs.WEEK_REVIEW, h, synced=synced))

    def test_a_late_review_still_reads_its_own_week(self):
        h = week(days_back=9, done=4)                     # first cue came on day ten: the week is the same
        self.assertIn("habit: target reached this week", jobs_runner.body(jobs.WEEK_REVIEW, h))

    def test_other_lines_stay_after_it_and_choices_last(self):
        h = week(done=1)
        got = jobs_runner.body(jobs.WEEK_REVIEW, h, flow="Flow: x.", passive="Phone: y.")
        self.assertEqual(got.splitlines(), [jobs.week_review_text(h), "habit: on the way", "Phone: y.", "Flow: x.", KD])
        self.assertTrue(one_tap.is_one_tap(got))

    def test_no_new_jobs(self):
        self.assertEqual(sorted(jobs.SPECS),
                         ["break_nudge", "habit_checkin", "miq", "nap", "wake_brief", "week_review"])


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def review(self, habit):
        (self.st / "habit.json").write_text(json.dumps(habit))
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [b for t, b in push.calls if t == "Week review"]
        return text.splitlines()

    def test_default_target(self):
        self.assertEqual(self.review(week(done=3))[1], "habit: on the way")

    def test_config_target_days(self):
        self.cfg.write_text(json.dumps({"habit_target_days": 3}))
        self.assertEqual(self.review(week(done=3))[1], "habit: target reached this week")


if __name__ == "__main__":
    unittest.main()
