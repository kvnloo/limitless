"""The week review's experiment line: "Experiment: outcome pending (judged later)" when the habit week's locked
prediction has a lag that has not passed (its receipt would be pending); otherwise nothing new. Digit-free,
through tier_audit.gate, before the stop-rule line. Synthetic data only; nothing sends."""
import json
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs, jobs_runner, prediction  # noqa: E402

LINE = "Experiment: outcome pending (judged later)"
KD = "Reply: Keep / Drop"
WEEK = date(2030, 1, 15)
DAY7 = WEEK + timedelta(days=6)
NOW = 1894708800.0
UTC = timezone.utc


class ExperimentLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "none.json"), "LIMITLESS_AUDIT": str(self.audit)}
        self.habit = {"habit": "Synthetic habit", "week_of": WEEK.isoformat(), "stop_rule": "any_done",
                      "checkins": {(WEEK + timedelta(days=i)).isoformat(): "Done" for i in range(4)}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))

    def lock(self, lag, metric="sleep_h", direction="up"):
        r = prediction.lock(self.st, WEEK.isoformat(), "Synthetic prediction", metric, direction, write=True,
                            today=WEEK, now=NOW, lag_days=lag)
        self.assertEqual(r["action"], prediction.LOCKED, r)

    def line(self, today=DAY7, habit=None):
        return jobs_runner.week_experiment(self.st, self.habit if habit is None else habit, today, self.env, self.root)

    def test_the_line_when_the_outcome_is_judged_later(self):
        for lag in (7, 14):
            with self.subTest(lag=lag):
                (self.st / prediction.PREDICTIONS_FILE).unlink(missing_ok=True)
                self.lock(lag)
                self.assertEqual(self.line(), LINE)
        self.assertEqual(re.findall(r"\d", LINE), [])
        rows = [json.loads(x) for x in self.audit.read_text().splitlines()]
        self.assertEqual({r["hook"] for r in rows}, {"week_review:experiment"})
        self.assertNotIn("text", rows[0])

    def test_nothing_new_otherwise(self):
        self.assertEqual(self.line(), "")                       # nothing locked
        self.lock(0)
        self.assertEqual(self.line(), "")                       # no lag: judged after day seven, as before
        self.assertEqual(self.line(habit={}), "")               # no started week
        self.assertEqual(jobs_runner.week_experiment(self.st, None, DAY7, self.env, self.root), "")

    def test_nothing_once_the_lag_has_passed(self):
        self.lock(7)
        self.assertEqual(self.line(today=WEEK + timedelta(days=14)), "")

    def test_body_puts_it_before_the_rule_line(self):
        got = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, experiment_line=LINE,
                               rule_line="Your rule says: keep it")
        self.assertEqual(got.splitlines()[-3:], [LINE, "Your rule says: keep it", KD])
        self.assertNotIn("Experiment", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, experiment_line=LINE))

    def test_the_week_review_body_carries_it(self):
        self.lock(7)
        text = jobs_runner.week_review_body(self.st, self.habit, {}, self.env, self.root, UTC, DAY7)
        self.assertIn(LINE, text.splitlines())
        self.assertEqual(text.splitlines()[-1], KD)

    def test_the_week_review_body_is_unchanged_without_a_lag(self):
        before = jobs_runner.week_review_body(self.st, self.habit, {}, self.env, self.root, UTC, DAY7)
        self.lock(0)
        self.assertEqual(jobs_runner.week_review_body(self.st, self.habit, {}, self.env, self.root, UTC, DAY7),
                         before)
        self.assertNotIn("Experiment", before)


if __name__ == "__main__":
    unittest.main()
