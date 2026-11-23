"""The week review's flow-metrics line: one digit-free line after the flow line, none when unknown.

Synthetic data only: a tiny ActivityWatch DB, made-up app names, a fake push, a fixed clock, UTC days.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import flow_metrics as fm, weekly_target  # noqa: E402
from limitless import jobs, jobs_runner  # noqa: E402
from test_flow_week_hooks import KD, NOW, TODAY, UTC, FakePush, noon, write_db  # noqa: E402

M = 60.0
LINE = "Work pattern this week (observed app activity, not attention): {}."


class ReviewLine(unittest.TestCase):
    def test_words_for_each_label(self):
        for word in fm.LABELS:
            self.assertEqual(fm.review_line(word), LINE.format(word))
            self.assertEqual(re.findall(r"\d", fm.review_line(word)), [])

    def test_unknown_or_anything_else_is_empty(self):
        for word in ("unknown: no activity data", "unknown", "", None, "fresh", 3):
            self.assertEqual(fm.review_line(word), "")


class WeekReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def configure(self, **cfg):
        self.cfg.write_text(json.dumps(cfg))

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")

    def ours(self):
        return [x for x in self.review() if x.startswith("Work pattern")]

    def broken(self, day):
        t, out = noon(day), []
        for _ in range(6):
            out += [(t, t + 8 * M, "editor"), (t + 8 * M, t + 20 * M, "feed")]
            t += 20 * M
        return out

    def test_body_puts_the_line_right_after_the_flow_line(self):
        text = jobs.week_review_text(self.habit) + "\n" + weekly_target.REVIEW_ON_THE_WAY
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, flow="Flow: x.", body_line="Body: y.",
                                          fragment="Work pattern: z."),
                         text + "\nFlow: x.\nWork pattern: z.\nBody: y." + KD)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, fragment=""), text + KD)
        self.assertNotIn("Work pattern", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, fragment="Work pattern: z."))
        self.assertNotIn("Work pattern", jobs_runner.body(jobs.MIQ, self.habit, fragment="Work pattern: z."))

    def test_the_review_says_the_work_was_broken_up(self):
        write_db(self.st / "aw.db", self.broken(self.week_of + timedelta(days=1)) + self.broken(self.week_of + timedelta(days=3)))
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])
        lines = self.review()
        self.assertEqual(lines[0], jobs.week_review_text(self.habit))
        self.assertEqual(lines[1], weekly_target.REVIEW_ON_THE_WAY)
        self.assertTrue(lines[2].startswith("Flow ("), lines)
        self.assertEqual(lines[3], LINE.format("work was broken up"))      # right after the flow line
        self.assertEqual(re.findall(r"\d", lines[3]), [])

    def test_last_weeks_data_does_not_count(self):
        write_db(self.st / "aw.db", self.broken(self.week_of - timedelta(days=2)))
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])
        self.assertEqual(self.ours(), [])

    def test_long_blocks(self):
        d = noon(self.week_of + timedelta(days=2))
        write_db(self.st / "aw.db", [(d, d + 120 * M, "editor")])
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])
        self.assertEqual(self.ours(), [LINE.format("work stayed in long blocks")])

    def test_unknown_adds_no_line(self):
        d = noon(self.week_of + timedelta(days=2))
        write_db(self.st / "aw.db", [(d, d + 120 * M, "feed")])
        self.configure(aw_db="aw.db")                               # no work apps
        self.assertEqual(self.ours(), [])
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])    # rows, but no work time
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.ours(), [])
        self.configure()                                            # no DB at all
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_helper(self):
        d = noon(self.week_of + timedelta(days=2))
        write_db(self.st / "aw.db", [(d, d + 120 * M, "editor")])
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])
        self.assertEqual(jobs_runner.week_flow_metrics(self.st, self.habit, self.env, self.root, UTC),
                         LINE.format("work stayed in long blocks"))
        self.assertEqual(jobs_runner.week_flow_metrics(self.st, {}, self.env, self.root, UTC), "")   # no week
        self.assertEqual(jobs_runner.week_flow_metrics(self.st, None, self.env, self.root, UTC), "")

    def test_the_db_is_never_written(self):
        db = self.st / "aw.db"
        write_db(db, self.broken(self.week_of + timedelta(days=1)))
        self.configure(aw_db="aw.db", flow_work_apps=["editor"])
        before = (db.read_bytes(), db.stat().st_mtime_ns)
        self.review()
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
