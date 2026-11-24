"""habit_card.week_number(card_state, week_start) -> {done, logged, unknown}: the one day-seven number. Unknown is
the days with no Done or No entry and is never counted as a No. Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card  # noqa: E402

START = date(2030, 1, 7)


def day(i):
    return (START + timedelta(days=i)).isoformat()


class WeekNumber(unittest.TestCase):
    def test_an_empty_week_is_seven_unknown_days_not_seven_nos(self):
        self.assertEqual(habit_card.week_number({}, START), {"done": 0, "logged": 0, "unknown": 7})
        self.assertEqual(habit_card.week_number(None, START.isoformat()), {"done": 0, "logged": 0, "unknown": 7})

    def test_done_and_no_are_logged(self):
        s = {"checkins": {day(0): "Done", day(1): "No", day(2): "Done"}}
        self.assertEqual(habit_card.week_number(s, START), {"done": 2, "logged": 3, "unknown": 4})

    def test_only_the_seven_days_from_week_start_are_read(self):
        s = {"checkins": {day(-1): "Done", day(6): "No", day(7): "Done"}}
        self.assertEqual(habit_card.week_number(s, START), {"done": 0, "logged": 1, "unknown": 6})

    def test_any_other_entry_is_no_entry(self):
        s = {"checkins": {day(0): "Skipped", day(1): "maybe", day(2): None, day(3): " done "}}
        self.assertEqual(habit_card.week_number(s, START), {"done": 1, "logged": 1, "unknown": 6})

    def test_no_valid_week_start_is_none_never_zero(self):
        for bad in (None, "", "next week", "2030-13-01", 7):
            self.assertIsNone(habit_card.week_number({"checkins": {day(0): "Done"}}, bad), bad)

    def test_the_three_numbers_always_cover_the_seven_days(self):
        s = {"checkins": {day(i): ("Done", "No")[i % 2] for i in range(0, 7, 3)}}
        n = habit_card.week_number(s, START)
        self.assertEqual(n["logged"] + n["unknown"], habit_card.WEEK_DAYS)
        self.assertEqual(sorted(n), ["done", "logged", "unknown"])


if __name__ == "__main__":
    unittest.main()
