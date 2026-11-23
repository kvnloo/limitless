"""limitless_habit gains ``target`` (weekly_target.progress of the week so far); the state card's habit line
says "target reached this week" once it is. Synthetic state dirs only; nothing sends.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, tier_audit, tools, weekly_target  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, timezone.utc).date()


def back(n):
    return (TODAY - timedelta(days=n)).isoformat()


class WithState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def habit_file(self, days_back=4, checkins=None, **kw):
        h = dict({"habit": "Synthetic habit", "week_of": back(days_back), "checkins": checkins or {}}, **kw)
        (self.st / "habit.json").write_text(json.dumps(h))

    def habit(self):
        return tools.habit(StateReader(self.st), NOW, TODAY, self.env)

    def card_habit_line(self):
        c = card.build(StateReader(self.st), NOW, TODAY, env=self.env)
        return [ln for ln in c["lines"] if ln.startswith("habit")][0]


class HabitTool(WithState):
    def test_target_is_progress_of_the_week_so_far(self):
        self.habit_file(checkins={back(4): "Done", back(3): "No", back(2): "Skipped", back(0): "Done"})
        t = self.habit()["value"]["target"]
        self.assertEqual({k: t[k] for k in ("done", "logged", "target", "reached")},
                         {"done": 2, "logged": 3, "target": 4, "reached": False})
        self.assertEqual(t["label"], {"label": weekly_target.ON_THE_WAY, "tier": "T1", "modality": "self_report"})

    def test_reached(self):
        self.habit_file(checkins={back(i): "Done" for i in range(4)})
        t = self.habit()["value"]["target"]
        self.assertTrue(t["reached"])
        self.assertEqual(t["label"]["label"], weekly_target.REACHED)

    def test_config_target_days(self):
        self.cfg.write_text(json.dumps({"habit_target_days": 2}))
        self.habit_file(checkins={back(1): "Done", back(0): "Done"})
        t = self.habit()["value"]["target"]
        self.assertEqual((t["target"], t["reached"]), (2, True))

    def test_started_week_without_answers_is_not_started(self):
        self.habit_file(days_back=0)
        t = self.habit()["value"]["target"]
        self.assertEqual((t["done"], t["label"]["label"]), (0, weekly_target.NOT_STARTED))

    def test_no_week_has_no_target(self):
        self.assertNotIn("target", json.dumps(self.habit()))
        self.habit_file(days_back=9)                       # last week's file: no confirmed week now
        self.assertNotIn("target", json.dumps(self.habit()))

    def test_sync_days_make_the_label_a_proxy(self):
        (self.st / "habit1.jsonl").write_text(json.dumps({"day": back(1), "met": True}) + "\n")
        self.habit_file()
        t = self.habit()["value"]["target"]
        self.assertEqual((t["done"], t["label"]["modality"]), (1, "proxy"))

    def test_label_is_seen_by_the_tier_audit_and_digit_free(self):
        self.habit_file(checkins={back(0): "Done"})
        words = tier_audit.labels(self.habit())
        self.assertIn(weekly_target.ON_THE_WAY, words)
        self.assertEqual([w for w in words if re.search(r"\d", w)], [])


class Card(WithState):
    def test_reached_appends_the_words(self):
        self.habit_file(checkins={back(i): "Done" for i in range(5)})
        self.assertEqual(self.card_habit_line(),
                         "habit this week: Synthetic habit; today Done; target reached this week")

    def test_not_reached_leaves_the_line_as_it_was(self):
        self.habit_file(checkins={back(0): "Done", back(1): "No"})
        self.assertEqual(self.card_habit_line(), "habit this week: Synthetic habit; today Done")

    def test_card_passes_the_tier_gate(self):
        self.habit_file(checkins={back(i): "Done" for i in range(4)})
        text = card.build(StateReader(self.st), NOW, TODAY, env=self.env)["text"]
        self.assertIn("target reached this week", text)
        self.assertEqual(tier_audit.gate("pre_llm_call", text, False, env=self.env, now=NOW), text)


if __name__ == "__main__":
    unittest.main()
