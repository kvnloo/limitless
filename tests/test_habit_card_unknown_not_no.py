"""The Unknown != No contract of the habit card. A week replied Done, Done, (nothing), No, Skip, (nothing), Done
is done three, logged four, unknown three: never "four of seven failed" and never a rate over seven.
Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card  # noqa: E402

START = date(2030, 1, 7)
WEEK = ("Done", "Done", None, "No", "Skip", None, "Done")   # None: no reply that day


def replied_week():
    state = {}
    for i, r in enumerate(WEEK):
        if r is not None:
            state = habit_card.record(state, (START + timedelta(days=i)).isoformat(), r)
    return state


class UnknownIsNotNo(unittest.TestCase):
    def test_the_week_is_done_three_logged_four_unknown_three(self):
        self.assertEqual(habit_card.week_number(replied_week(), START), {"done": 3, "logged": 4, "unknown": 3})

    def test_skip_and_silence_are_the_same_unknown_day(self):
        self.assertNotIn((START + timedelta(days=4)).isoformat(), replied_week()["checkins"])
        self.assertEqual(len(replied_week()["checkins"]), 4)

    def test_only_one_day_is_a_no_never_four_of_seven_failed(self):
        n = habit_card.week_number(replied_week(), START)
        self.assertEqual(n["logged"] - n["done"], 1)                      # the one No
        self.assertNotEqual(habit_card.WEEK_DAYS - n["done"], n["logged"] - n["done"])

    def test_no_rate_over_seven_and_no_score(self):
        n = habit_card.week_number(replied_week(), START)
        self.assertEqual(set(n), {"done", "logged", "unknown"})
        self.assertTrue(all(isinstance(v, int) and not isinstance(v, bool) for v in n.values()))
        for banned in ("rate", "score", "failed", "missed", "percent", "streak", "total"):
            self.assertFalse(any(banned in k for k in n), banned)


if __name__ == "__main__":
    unittest.main()
