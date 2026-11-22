"""habit1.jsonl (the sync's per-day 'feeds-free first hour' row) + 1-tap answers -> one day-7 number.

Synthetic rows only; the fixture clock is 2030-01-15T12:00:00Z (epoch 1894708800).
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
TODAY = date(2030, 1, 15)
WEEK = "2030-01-09"           # day 7 of the week is 2030-01-15


def sync_row(day, met, **kw):
    r = {"day": day, "wake": f"{day}T00:00:00Z", "feedMinFirstHour": 0 if met else 12, "firstApp": "com.example.app",
         "firstCat": "tools" if met else "feed", "minToFirstFeed": 75 if met else 4, "met": met}
    r.update(kw)
    return r


def state(d, habit=None, rows=None, raw=None):
    p = Path(d)
    if habit is not None:
        (p / "habit.json").write_text(json.dumps(habit))
    if rows is not None or raw is not None:
        text = "\n".join(json.dumps(r) for r in rows or ()) + "\n" + (raw or "")
        (p / "habit1.jsonl").write_text(text)
    return StateReader(p)


class HabitDays(unittest.TestCase):
    def test_reads_met_and_missed(self):
        with tempfile.TemporaryDirectory() as d:
            r = state(d, rows=[sync_row("2030-01-10", True), sync_row("2030-01-11", False)])
            self.assertEqual(r.habit_days(), {"2030-01-10": "met", "2030-01-11": "missed"})

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(StateReader(Path(d)).habit_days(), {})

    def test_rows_without_a_real_met_are_left_out(self):
        rows = [sync_row("2030-01-10", True), {"day": "2030-01-11", "met": None}, {"day": "2030-01-12", "met": "yes"},
                {"day": "2030-01-13"}, {"met": True}, {"day": "not a date", "met": True}]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(state(d, rows=rows, raw="{broken\n").habit_days(), {"2030-01-10": "met"})

    def test_a_later_row_for_the_same_day_wins(self):
        with tempfile.TemporaryDirectory() as d:
            r = state(d, rows=[sync_row("2030-01-10", False), sync_row("2030-01-10", True)])
            self.assertEqual(r.habit_days(), {"2030-01-10": "met"})


class Precedence(unittest.TestCase):
    H = {"checkins": {"2030-01-10": "No", "2030-01-11": "Done", "2030-01-12": "Skipped"}}
    SYNC = {"2030-01-10": "met", "2030-01-11": "missed", "2030-01-12": "met", "2030-01-13": "met",
            "2030-01-14": "missed"}

    def test_a_tap_beats_the_sync(self):
        self.assertEqual(jobs.habit_day(self.H, "2030-01-10", self.SYNC), "No")
        self.assertEqual(jobs.habit_day(self.H, "2030-01-11", self.SYNC), "Done")
        self.assertEqual(jobs.habit_day(self.H, "2030-01-12", self.SYNC), "Skipped")

    def test_the_sync_fills_an_untapped_day(self):
        self.assertEqual(jobs.habit_day(self.H, "2030-01-13", self.SYNC), "Done")
        self.assertEqual(jobs.habit_day(self.H, "2030-01-14", self.SYNC), "No")

    def test_neither_is_unlogged_never_no(self):
        self.assertEqual(jobs.habit_day(self.H, "2030-01-15", self.SYNC), "unlogged")
        self.assertEqual(jobs.habit_day(None, "2030-01-15", None), "unlogged")
        self.assertEqual(jobs.habit_day(None, "2030-01-15", {"2030-01-15": "maybe"}), "unlogged")

    def test_old_two_argument_call_still_works(self):
        self.assertEqual(jobs.habit_day(self.H, "2030-01-11"), "Done")


class LimitlessHabit(unittest.TestCase):
    HABIT = {"at": "2030-01-15T06:00:00Z", "week_of": WEEK, "habit": "Feeds-free first hour",
             "start": "Phone face down", "checkins": {"2030-01-09": "Done", "2030-01-10": "No",
                                                       "2030-01-11": "Skipped"}}
    ROWS = [sync_row("2030-01-10", True), sync_row("2030-01-12", True), sync_row("2030-01-13", False),
            sync_row("2030-01-15", True, wake="2030-01-15T10:00:00Z")]

    def env(self, habit=None, rows=None):
        with tempfile.TemporaryDirectory() as d:
            return tools.habit(state(d, habit or self.HABIT, rows), NOW, TODAY)

    def test_day_seven_is_one_number_of_logged_days(self):
        v = self.env(rows=self.ROWS)["value"]
        # 09 Done (tap), 10 No (tap beats met), 11 Skipped, 12 Done (sync), 13 No (sync), 14 unlogged, 15 Done (sync)
        self.assertEqual([x["checkin"] for x in v["days"]],
                         ["Done", "No", "Skipped", "Done", "No", "unlogged", "Done"])
        self.assertEqual(v["day"], 7)
        self.assertEqual(v["logged"], "3 of 5 logged days")

    def test_unlogged_and_skipped_days_stay_out_of_m(self):
        v = self.env(rows=[])["value"]
        self.assertEqual(v["logged"], "1 of 2 logged days")         # Done, No; Skipped and unlogged left out

    def test_nothing_logged_says_so(self):
        v = self.env(habit=dict(self.HABIT, checkins={}))["value"]
        self.assertEqual(v["logged"], "0 of 0 logged days")
        self.assertEqual(v["counts"]["No"], 0)

    def test_where_each_day_came_from(self):
        v = self.env(rows=self.ROWS)["value"]
        self.assertEqual([x["from"] for x in v["days"]], ["tap", "tap", "tap", "sync", "sync", None, "sync"])

    def test_envelope_like_the_other_tools(self):
        taps_only = self.env(rows=[])
        self.assertEqual((taps_only["modality"], taps_only["age_h"], taps_only["evidence_tier"]),
                         ("self_report", 6.0, "direct"))
        mixed = self.env(rows=self.ROWS)
        # A sync day is phone-usage proxy evidence; age is the newest source (the sync row's wake, 2 h ago).
        self.assertEqual((mixed["modality"], mixed["age_h"], mixed["evidence_tier"]), ("proxy", 2.0, "indirect"))

    def test_fixture_state_dir_is_unchanged(self):
        fix = Path(__file__).resolve().parent / "fixtures" / "state"
        env = tools.habit(StateReader(fix), NOW, TODAY)
        self.assertEqual(env["value"]["logged"], "2 of 3 logged days")
        self.assertEqual(env["modality"], "self_report")


if __name__ == "__main__":
    unittest.main()
