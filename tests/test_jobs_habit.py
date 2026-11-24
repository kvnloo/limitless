"""Habit check-in answers: Done / No / Skip in one tap; a day with no answer is unlogged, never No."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import copy
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import jobs  # noqa: E402

HABIT = {"week_of": "2030-01-11", "habit": "Synthetic habit", "start": "Two-minute start",
         "checkins": {"2030-01-11": "Done"}}
NOW = 2_000_000_000.0


class HabitAnswers(unittest.TestCase):
    def test_taps(self):
        self.assertEqual(jobs.habit_answer("Done"), "Done")
        self.assertEqual(jobs.habit_answer("No"), "No")
        self.assertEqual(jobs.habit_answer("Skip"), "Skipped")
        self.assertEqual(jobs.habit_answer(" skip "), "Skipped")

    def test_no_answer_is_unlogged(self):
        for tap in (None, "", "  ", "maybe", 0, False, "expired"):
            self.assertIsNone(jobs.habit_answer(tap), repr(tap))

    def test_day_status(self):
        self.assertEqual(jobs.habit_day(HABIT, "2030-01-11"), "Done")
        self.assertEqual(jobs.habit_day(HABIT, "2030-01-12"), "unlogged")
        self.assertEqual(jobs.habit_day({"checkins": {"2030-01-12": ""}}, "2030-01-12"), "unlogged")
        self.assertEqual(jobs.habit_day(None, "2030-01-12"), "unlogged")

    def test_record_is_pure_and_silence_writes_nothing(self):
        before = copy.deepcopy(HABIT)
        same = jobs.record_checkin(HABIT, "2030-01-12", None)
        self.assertNotIn("2030-01-12", same["checkins"])
        self.assertEqual(jobs.record_checkin(HABIT, "2030-01-12", "Skip")["checkins"]["2030-01-12"], "Skipped")
        self.assertEqual(jobs.record_checkin(HABIT, "2030-01-12", "No")["checkins"]["2030-01-12"], "No")
        self.assertEqual(HABIT, before)

    def test_unanswered_never_overwrites(self):
        h = jobs.record_checkin(HABIT, "2030-01-11", None)
        self.assertEqual(h["checkins"]["2030-01-11"], "Done")

    def test_dropped_or_held_checkin_never_says_no(self):
        spec = jobs.SPECS["habit_checkin"]
        cases = [[], [{"event": "habit_cue", "at": NOW - 2 * 3600}, {"event": "sleep_mode_on", "at": NOW - 3600}],
                 [{"event": "habit_cue", "at": NOW - 30 * 3600}]]
        for events in cases:
            for state in (dw.WindowState("asleep"), dw.WindowState("anytime"), None):
                v = jobs.should_fire(spec, events, state, [], NOW)
                self.assertIsNone(re.search(r"\bNo\b", v.reason), v)


if __name__ == "__main__":
    unittest.main()
