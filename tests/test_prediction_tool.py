"""limitless_habit and predictions: it shows a locked prediction and its receipt (digit-free T1 labels);
`predict` locks one and `receipt` writes one only with confirm true, else it says what it would do.
Synthetic fixtures only; nothing sends."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, prediction  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0          # fixture clock, 2030-01-15: the fixture's week of 2030-01-11 is running
DAY = 86400.0
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
PREDICT = {"predict": "Synthetic prediction", "metric": "logged", "direction": "at_least 4 of 7"}


class HabitPredictionTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.hj = self.st / "habit.json"
        self.pj = self.st / prediction.PREDICTIONS_FILE

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args, now=NOW):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=now):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_habit"][1])(args))

    def new_week(self, week_of="2030-01-15", checkins=None):
        self.hj.write_text(json.dumps({"habit": "Synthetic habit", "week_of": week_of, "at": "2030-01-15T07:00:00Z",
                                       "checkins": checkins or {}}))

    def assert_labeled(self, res, label):
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(res["label"]["label"], label)
        self.assertEqual(re.findall(r"\d", res["label"]["label"]), [])

    def test_schema_has_predict_metric_direction_receipt(self):
        props = plugin.TOOLS["limitless_habit"][0]["parameters"]["properties"]
        self.assertEqual(props["predict"]["type"], "string")
        self.assertEqual(props["metric"]["enum"], ["logged", "sleep_h", "readiness"])
        self.assertEqual(props["direction"]["type"], "string")
        self.assertEqual(props["receipt"]["type"], "boolean")
        self.assertNotIn("required", plugin.TOOLS["limitless_habit"][0]["parameters"])

    def test_read_has_no_prediction_key_when_none_is_locked(self):
        res = self.call({})
        self.assertEqual(res["value"]["today"], "Done")
        self.assertNotIn("prediction", res)

    def test_predict_without_confirm_writes_nothing(self):
        self.new_week()
        for extra in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
            res = self.call(dict(PREDICT, **extra))
            self.assert_labeled(res, "would lock this prediction")
            self.assertEqual(res["value"]["action"], "would lock")
            self.assertEqual(res["value"]["prediction"]["week_of"], "2030-01-15")
            self.assertFalse(self.pj.exists())

    def test_predict_with_confirm_locks_for_the_running_week(self):
        self.new_week()
        res = self.call(dict(PREDICT, confirm=True))
        self.assert_labeled(res, "locked this prediction")
        self.assertEqual(res["modality"], "self_report")
        self.assertEqual(prediction.locked(self.st, "2030-01-15")["text"], "Synthetic prediction")

    def test_predict_with_no_running_week_is_for_today(self):
        self.hj.unlink()
        self.call(dict(PREDICT, confirm=True))
        self.assertIsNotNone(prediction.locked(self.st, "2030-01-15"))

    def test_predict_into_a_week_with_checkins_is_refused(self):
        res = self.call(dict(PREDICT, confirm=True))          # fixture week of 2030-01-11 has check-ins
        self.assert_labeled(res, "refused: that week already started and has check-ins logged: lock before the week")
        self.assertFalse(self.pj.exists())

    def test_read_shows_the_locked_prediction(self):
        self.new_week()
        self.call(dict(PREDICT, confirm=True))
        res = self.call({})
        self.assertEqual(res["value"]["habit"], "Synthetic habit")
        p = res["prediction"]
        self.assertEqual((p["text"], p["metric"], p["direction"]), ("Synthetic prediction", "logged", "at_least 4 of 7"))
        self.assertIsNone(p["receipt"])
        self.assertEqual(p["label"], {"label": "prediction locked", "tier": "T1", "modality": "self_report"})

    def test_receipt_without_confirm_writes_nothing_then_confirm_writes_one(self):
        self.new_week(checkins={"2030-01-15": "Done", "2030-01-16": "Done", "2030-01-17": "Done",
                                "2030-01-18": "Done"})
        self.call(dict(PREDICT, confirm=True))
        before = self.pj.read_bytes()
        res = self.call({"receipt": True}, now=NOW + 7 * DAY)
        self.assert_labeled(res, "would write this receipt: supports")
        self.assertEqual(self.pj.read_bytes(), before)
        res = self.call({"receipt": True, "confirm": True}, now=NOW + 7 * DAY)
        self.assert_labeled(res, "wrote this receipt: supports")
        res = self.call({"receipt": True, "confirm": True}, now=NOW + 8 * DAY)
        self.assertEqual(res["value"]["action"], "refused")
        self.assertEqual(len([r for r in prediction.rows(self.st) if r["kind"] == "receipt"]), 1)

    def test_read_after_the_week_shows_the_receipt(self):
        self.new_week(checkins={"2030-01-15": "Done", "2030-01-16": "No"})
        self.call(dict(PREDICT, confirm=True))
        self.call({"receipt": True, "confirm": True}, now=NOW + 7 * DAY)
        res = self.call({}, now=NOW + 7 * DAY)
        self.assertIsNone(res["value"])                        # the habit week itself is over
        self.assertEqual(res["prediction"]["receipt"]["verdict"], "inconclusive")
        self.assertEqual(res["prediction"]["label"]["label"], "receipt: inconclusive")

    def test_receipt_finds_last_weeks_prediction_after_a_new_start(self):
        self.new_week(checkins={"2030-01-15": "Done", "2030-01-16": "Done", "2030-01-17": "Done"})
        self.call(dict(PREDICT, confirm=True))
        r = self.call({"start": "Next habit", "confirm": True}, now=NOW + 7 * DAY)
        self.assertEqual(r["value"]["action"], "started")
        res = self.call({"receipt": True, "confirm": True}, now=NOW + 7 * DAY)
        self.assert_labeled(res, "wrote this receipt: supports")
        self.assertEqual(res["value"]["receipt"]["week_of"], "2030-01-15")

    def test_receipt_with_nothing_locked_is_refused(self):
        res = self.call({"receipt": True, "confirm": True})
        self.assert_labeled(res, "refused: no prediction is locked for that week: no receipt")
        self.assertFalse(self.pj.exists())


if __name__ == "__main__":
    unittest.main()
