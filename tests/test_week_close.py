"""A Keep / Drop decision closes the habit week. Synthetic data only; nothing sends.

A decided week is finished as of today: the check-in drops ("habit week closed"), habit_start starts the
next week and keeps the old file byte for byte as habit-<week_of>.json, and tools.habit shows the decision.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_start, jobs, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 2_000_000_000.0
TODAY = date(2033, 5, 18)


def week(days_back, **kw):
    return dict({"week_of": (TODAY - timedelta(days=days_back)).isoformat(), "habit": "Synthetic habit",
                 "checkins": {}}, **kw)


class Gate(unittest.TestCase):
    def test_a_decided_week_is_closed(self):
        for d in ("Keep", "Drop", "keep"):
            self.assertEqual(jobs.habit_week_gate(week(6, decision=d), TODAY),
                             jobs.Verdict(jobs.DROP, "habit week closed"), d)

    def test_no_decision_or_another_word_leaves_the_week_running(self):
        for h in (week(6), week(6, decision=None), week(6, decision="maybe"), week(6, decision=3)):
            self.assertIsNone(jobs.habit_week_gate(h, TODAY), h)


class Start(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, obj):
        raw = json.dumps(obj).encode()
        (self.st / "habit.json").write_bytes(raw)
        return raw

    def test_day_seven_with_a_decision_starts_the_next_week_and_keeps_the_old_one(self):
        old = week(6, decision="Keep", decided_at="2033-05-18T09:00:00+00:00")
        raw = self.put(old)
        r = habit_start.start_week(self.st, "Synthetic habit", TODAY, write=True, now=NOW)
        self.assertEqual(r["action"], habit_start.STARTED, r)
        self.assertEqual(r["kept"], f"habit-{old['week_of']}.json")
        self.assertEqual((self.st / r["kept"]).read_bytes(), raw)
        new = json.loads((self.st / "habit.json").read_text())
        self.assertEqual((new["week_of"], new["checkins"]), (TODAY.isoformat(), {}))
        self.assertNotIn("decision", new)

    def test_day_seven_without_a_decision_is_still_running(self):
        raw = self.put(week(6))
        r = habit_start.start_week(self.st, "Synthetic habit", TODAY, write=True, now=NOW)
        self.assertEqual(r["action"], habit_start.REFUSED)
        self.assertEqual((self.st / "habit.json").read_bytes(), raw)

    def test_a_finished_week_keeps_its_decision(self):
        raw = self.put(week(9, decision="Drop", decided_at="2033-05-16T09:00:00+00:00"))
        r = habit_start.start_week(self.st, "Another synthetic habit", TODAY, write=True, now=NOW)
        self.assertEqual(r["action"], habit_start.STARTED)
        self.assertEqual(json.loads((self.st / r["kept"]).read_bytes())["decision"], "Drop")
        self.assertEqual((self.st / r["kept"]).read_bytes(), raw)


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def value(self, obj):
        (self.st / "habit.json").write_text(json.dumps(obj))
        return tools.habit(StateReader(self.st), NOW, TODAY)["value"]

    def test_shows_the_decision_when_present(self):
        v = self.value(week(6, decision="keep", decided_at="2033-05-18T09:00:00+00:00"))
        self.assertEqual((v["decision"], v["decided_at"]), ("Keep", "2033-05-18T09:00:00+00:00"))

    def test_no_decision_means_no_decision_key_never_drop(self):
        for obj in (week(6), week(6, decision="maybe")):
            v = self.value(obj)
            self.assertNotIn("decision", v)
            self.assertNotIn("decided_at", v)


if __name__ == "__main__":
    unittest.main()
