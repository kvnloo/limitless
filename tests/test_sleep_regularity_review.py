"""The week review's sleep line gains one digit-free regularity clause; none when regularity is unknown.

Synthetic rows only, UTC as the local zone, a fake push.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs_runner, regularity, sleep  # noqa: E402
import test_sleep_review as base  # noqa: E402  (a module import: its Review tests are not collected twice)
from test_sleep_review import TODAY, screen_rows, sleep_rows  # noqa: E402

UTC = timezone.utc
H = 3600


def timed_rows(nights=range(1, 8), start_h=23.0, hours=7.0, step_h=0.0):
    out = []
    for d in nights:
        day = TODAY - timedelta(days=d)
        s = datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + (start_h - d * step_h) * H
        out.append({"night": day.isoformat(), "asleep_s": int(hours * H), "source": "synthetic-ring",
                    "start": s, "end": s + hours * H})
    return out


class Line(unittest.TestCase):
    LAB = {"label": "sleep: wearable on most nights; phone proxy says longer", "tier": "T1"}

    def test_the_clause_follows_the_sleep_words(self):
        r = {"wearable": {"known": True, "pattern": "steady"}, "proxy": {"known": False}}
        self.assertEqual(sleep.review_line(self.LAB, r),
                         "Sleep: wearable on most nights; phone proxy says longer; wearable says sleep times steady.")

    def test_unknown_regularity_adds_nothing(self):
        plain = "Sleep: wearable on most nights; phone proxy says longer."
        self.assertEqual(sleep.review_line(self.LAB), plain)
        self.assertEqual(sleep.review_line(self.LAB, {"wearable": {"known": False}, "proxy": {"known": False}}),
                         plain)
        self.assertEqual(sleep.review_line(self.LAB, "drifting later"), plain)
        self.assertEqual(sleep.review_line({"label": "x"}, {"wearable": {"known": True, "pattern": "steady"}}), "")


class Week(unittest.TestCase):
    R = base.Review
    setUp, configure, write, review = R.setUp, R.configure, R.write, R.review   # its helpers, not its tests

    def test_the_review_line_names_how_regular_sleep_was(self):
        self.configure(sleep_file="sleep.jsonl")
        self.write("sleep.jsonl", timed_rows(step_h=0.4))            # each night later than the one before
        lines = self.review()
        self.assertEqual(lines[-1], "Sleep: wearable on most nights; phone proxy has no night to compare; "
                                    "wearable says drifting later.")
        self.assertEqual(re.findall(r"\d", lines[-1]), [])

    def test_the_phone_estimate_clause_when_the_wearable_has_no_times(self):
        self.configure(sleep_file="sleep.jsonl")
        self.write("sleep.jsonl", sleep_rows())
        self.write("screen-events.jsonl", screen_rows(range(1, 8)))
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root, TODAY, UTC),
                         "Sleep: wearable on most nights; phone proxy says longer; "
                         "phone estimate says sleep times steady.")

    def test_too_few_nights_leaves_the_line_as_it_was(self):
        self.configure(sleep_file="sleep.jsonl", regularity_min_nights=9)
        self.write("sleep.jsonl", timed_rows())
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root, TODAY, UTC),
                         "Sleep: wearable on most nights; phone proxy has no night to compare.")

    def test_every_clause_is_digit_free(self):
        for c in regularity.CLAUSES:
            self.assertEqual(re.findall(r"\d", c), [])


if __name__ == "__main__":
    unittest.main()
