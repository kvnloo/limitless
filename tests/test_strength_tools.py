"""The ladder's word on limitless_experiment and limitless_loop: an optional ``strength`` key beside the
envelope, never inside it; the envelope's four fields are as they were. Synthetic ledgers only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, prediction, stop_rule, tools  # noqa: E402

NOW = 1894708800.0           # 2030-01-15T12:00:00Z
W1 = date(2030, 1, 15)
W2 = W1 + timedelta(days=14)
HABIT = "Synthetic walk after lunch"
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
MOSTLY_DONE = ("Done", "Done", "Done", "Done", "Done", "No", "Done")
MOSTLY_NO = ("No", "No", "No", "No", "Done", "No", "No")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        self.st.mkdir()

    def week(self, start, answers, judge=True, decide=True):
        checkins = {(start + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}
        h = {"habit": HABIT, "week_of": start.isoformat(), "checkins": checkins}
        (self.st / f"habit-{start.isoformat()}.json").write_text(json.dumps(h))
        prediction.lock(self.st, start.isoformat(), "Synthetic prediction", "logged", "at_least 4 of 7", write=True,
                        today=start, now=NOW)
        if judge:
            prediction.receipt(self.st, start.isoformat(), write=True, today=start + timedelta(days=7), now=NOW)
        if decide:
            self.assertIsNotNone(stop_rule.record_loop(self.st, h, "Keep", "2030-01-22T00:00:00+00:00", now=NOW))

    def later(self):
        return NOW + 40 * 86400, W1 + timedelta(days=40)

    def assertStrength(self, s):
        self.assertEqual(set(s), {"rung", "words", "why"}, s)
        self.assertEqual(re.findall(r"\d", s["words"] + s["why"]), [], s)


class Experiment(Base):
    def test_nothing_locked_has_no_strength(self):
        self.assertNotIn("strength", tools.experiment(self.st, NOW, W1))

    def test_one_supported_week(self):
        self.week(W1, MOSTLY_DONE)
        out = tools.experiment(self.st, *self.later())
        self.assertStrength(out["strength"])
        self.assertEqual(out["strength"]["words"], "preregistered: one locked week supported it")

    def test_two_supported_weeks(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE)
        self.assertEqual(tools.experiment(self.st, *self.later())["strength"]["rung"], "repeated")

    def test_contradicted_does_not_climb(self):
        self.week(W1, MOSTLY_NO)
        s = tools.experiment(self.st, *self.later())["strength"]
        self.assertIsNone(s["rung"])
        self.assertStrength(s)

    def test_the_envelope_fields_are_unchanged(self):
        self.week(W1, MOSTLY_DONE)
        out = tools.experiment(self.st, *self.later())
        self.assertEqual(set(out), FIELDS | {"label", "note", "strength"})
        self.assertNotIn("strength", json.dumps(out["value"]))
        self.assertEqual(out["value"]["past"][0]["verdict"], "supports")
        self.assertEqual((out["modality"], out["evidence_tier"]), ("derived", "stale"))

    def test_read_only(self):
        self.week(W1, MOSTLY_DONE)
        before = sorted((p.name, p.read_bytes()) for p in self.st.iterdir())
        tools.experiment(self.st, *self.later())
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.st.iterdir()), before)


class Loop(Base):
    def test_no_loop_row_has_no_strength(self):
        out = tools.loop(self.st, NOW, W1)
        self.assertIsNone(out["value"])
        self.assertNotIn("strength", out)

    def test_the_newest_weeks_habit(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE)
        out = tools.loop(self.st, *self.later())
        self.assertStrength(out["strength"])
        self.assertEqual(out["strength"]["words"], "repeated: two locked weeks supported it")

    def test_a_week_with_no_prediction_says_no_evidence(self):
        h = {"habit": HABIT, "week_of": W1.isoformat(), "checkins": {}}
        stop_rule.record_loop(self.st, h, "Drop", "2030-01-22T00:00:00+00:00", now=NOW)
        out = tools.loop(self.st, *self.later())
        self.assertIsNone(out["strength"]["rung"])
        self.assertStrength(out["strength"])

    def test_the_envelope_fields_are_unchanged(self):
        self.week(W1, MOSTLY_DONE)
        out = tools.loop(self.st, *self.later())
        self.assertEqual(set(out), FIELDS | {"label", "strength"})
        self.assertEqual(out["modality"], "self_report")
        self.assertEqual(out["value"]["weeks"][0]["outcome"]["value"], "supports")


class ThroughThePlugin(Base):
    def call(self, name):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json"),
               "LIMITLESS_RAW_IN_PROMPT": "0"}
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=self.later()[0]):
            return json.loads(plugin._handler(plugin.TOOLS[name][1], name)({}))

    def test_both_tools_carry_it(self):
        self.week(W1, MOSTLY_DONE)
        for name in ("limitless_experiment", "limitless_loop"):
            with self.subTest(tool=name):
                out = self.call(name)
                self.assertTrue(FIELDS <= set(out))
                self.assertEqual(out["strength"]["rung"], "preregistered")

    def test_the_descriptions_name_it(self):
        for name in ("limitless_experiment", "limitless_loop"):
            self.assertIn("strength", plugin.TOOLS[name][0]["description"].lower())


if __name__ == "__main__":
    unittest.main()
