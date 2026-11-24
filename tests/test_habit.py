"""limitless_habit: this week's one habit; Done/No/Skipped; an unanswered day is unlogged, never No."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)


def habit_in(d, **h):
    (Path(d) / "habit.json").write_text(json.dumps(h))
    return StateReader(Path(d))


class Habit(unittest.TestCase):
    def setUp(self):
        self.env = tools.habit(StateReader(FIX), NOW, TODAY)
        self.v = self.env["value"]

    def test_one_habit_with_its_two_minute_start(self):
        self.assertEqual(self.v["habit"], "Lights down when wind-down starts")
        self.assertEqual(self.v["start"], "Dim one lamp")
        self.assertEqual(self.env["modality"], "self_report")
        self.assertEqual(self.env["age_h"], 4.5)

    def test_days_so_far_this_week(self):
        self.assertEqual([d["date"] for d in self.v["days"]],
                         ["2030-01-11", "2030-01-12", "2030-01-13", "2030-01-14", "2030-01-15"])
        self.assertEqual([d["checkin"] for d in self.v["days"]], ["Done", "Skipped", "No", "unlogged", "Done"])

    def test_unanswered_is_unlogged_not_no(self):
        self.assertEqual(self.v["counts"], {"Done": 2, "No": 1, "Skipped": 1, "unlogged": 1})
        self.assertEqual(self.v["today"], "Done")

    def test_odd_values_are_unlogged_and_case_is_forgiven(self):
        with tempfile.TemporaryDirectory() as d:
            r = habit_in(d, week_of="2030-01-14", habit="h", checkins={"2030-01-14": "done", "2030-01-15": "maybe"})
            v = tools.habit(r, NOW, TODAY)["value"]
        self.assertEqual([x["checkin"] for x in v["days"]], ["Done", "unlogged"])
        self.assertEqual(v["counts"]["No"], 0)

    def test_last_weeks_habit_is_not_this_weeks(self):
        with tempfile.TemporaryDirectory() as d:
            env = tools.habit(habit_in(d, week_of="2030-01-01", habit="old"), NOW, TODAY)
        self.assertIsNone(env["value"])
        self.assertIn("2030-01-01", env["reason"])

    def test_no_habit_file(self):
        with tempfile.TemporaryDirectory() as d:
            env = tools.habit(StateReader(Path(d)), NOW, TODAY)
        self.assertIsNone(env["value"])
        self.assertIn("habit.json", env["reason"])


if __name__ == "__main__":
    unittest.main()
