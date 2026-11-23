"""Passive habit days: the older loop's per-day rows, read as measured evidence (a proxy), never a check-in.

Synthetic rows only. The file is the config key ``passive_habit_file`` (relative = the state dir); none by
default, and no file or no rows is unknown, never "0 of 0".
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless.state_reader import StateReader  # noqa: E402


def row(day, met, **kw):
    r = {"day": day, "wake": "07:00", "feedMinFirstHour": 0.0, "firstApp": "synthetic", "firstCat": "tool",
         "minToFirstFeed": None, "met": met}
    r.update(kw)
    return r


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, name="passive.jsonl"):
        self.cfg.write_text(json.dumps({"passive_habit_file": name}))

    def write_rows(self, rows, name="passive.jsonl", extra=""):
        p = Path(name) if Path(name).is_absolute() else self.st / name
        p.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)
        return p


class PassiveDays(Setup):
    def test_no_file_configured_is_empty(self):
        self.write_rows([row("2030-01-14", True)])
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])

    def test_relative_path_is_in_the_state_dir(self):
        self.configure("passive.jsonl")
        self.write_rows([row("2030-01-14", True), row("2030-01-15", False)])
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([(r["day"], r["met"]) for r in got], [("2030-01-14", True), ("2030-01-15", False)])
        self.assertEqual(StateReader(self.st).passive_habit_file(self.env), self.st / "passive.jsonl")

    def test_absolute_path(self):
        p = self.root / "elsewhere.jsonl"
        self.configure(str(p))
        self.write_rows([row("2030-01-14", True)], name=str(p))
        self.assertEqual(len(StateReader(self.st).passive_habit_days(self.env)), 1)

    def test_malformed_rows_are_ignored(self):
        self.configure()
        self.write_rows([row("2030-01-10", True), row("2030-01-11", "yes"), row("2030-13-01", True),
                         row("not a day", False), row(20300112, True), {"met": True}, row("2030-01-13", None),
                         row("20300114", True), row("2030-01-15", False)],
                        extra="{broken json\n[1, 2]\n")
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([r["day"] for r in got], ["2030-01-10", "2030-01-15"])

    def test_one_row_per_day_the_last_wins_sorted(self):
        self.configure()
        self.write_rows([row("2030-01-15", False), row("2030-01-14", True), row("2030-01-15", True)])
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([(r["day"], r["met"]) for r in got], [("2030-01-14", True), ("2030-01-15", True)])

    def test_missing_file_or_bad_config_is_empty(self):
        self.configure("nope.jsonl")
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])
        self.cfg.write_text(json.dumps({"passive_habit_file": 7}))
        self.assertIsNone(StateReader(self.st).passive_habit_file(self.env))
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])

    def test_reading_writes_nothing(self):
        self.configure()
        self.write_rows([row("2030-01-15", True)])
        before = sorted(p.name for p in self.st.iterdir())
        StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
