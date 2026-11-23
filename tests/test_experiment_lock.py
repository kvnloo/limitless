"""prediction.lock with a stated falsifier and a lag (none, one week or two weeks): stored on the one
prediction row in predictions.jsonl; old rows without them stay valid. Synthetic fixtures only; nothing sends."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import prediction  # noqa: E402

NOW = 1894708800.0
WEEK = date(2030, 1, 15)
FALSIFIER = "Fewer synthetic done days than the week before would show this is wrong"


class LockFalsifierLag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def lock(self, write=True, metric="sleep_h", direction="up", **kw):
        return prediction.lock(self.st, WEEK.isoformat(), "Synthetic prediction", metric, direction, write=write,
                               today=WEEK, now=NOW, **kw)

    def test_the_falsifier_and_lag_are_stored_on_the_row(self):
        r = self.lock(falsifier="  " + FALSIFIER + " ", lag_days=7)
        self.assertEqual(r["action"], prediction.LOCKED, r)
        row = prediction.locked(self.st, WEEK.isoformat())
        self.assertEqual((row["falsifier"], row["lag_days"]), (FALSIFIER, 7))
        self.assertEqual([x["kind"] for x in prediction.rows(self.st)], ["prediction"])

    def test_defaults_are_no_falsifier_and_no_lag(self):
        row = self.lock()["prediction"]
        self.assertEqual((row["falsifier"], row["lag_days"]), (None, 0))

    def test_a_blank_falsifier_is_none(self):
        self.assertIsNone(self.lock(falsifier="   ")["prediction"]["falsifier"])

    def test_a_dry_run_writes_nothing_and_shows_the_fields(self):
        r = self.lock(write=False, falsifier=FALSIFIER, lag_days=14)
        self.assertEqual(r["action"], prediction.WOULD_LOCK)
        self.assertEqual((r["prediction"]["falsifier"], r["prediction"]["lag_days"]), (FALSIFIER, 14))
        self.assertFalse((self.st / prediction.PREDICTIONS_FILE).exists())

    def test_only_the_fixed_lags_are_taken(self):
        for bad in (1, 3, 21, -7, "7", 7.0, True, None):
            r = self.lock(lag_days=bad)
            self.assertEqual(r["action"], prediction.REFUSED, bad)
            self.assertEqual(re.findall(r"\d", r["reason"]), [], r["reason"])
        self.assertFalse((self.st / prediction.PREDICTIONS_FILE).exists())
        self.assertEqual(prediction.LAG_DAYS, (0, 7, 14))

    def test_a_falsifier_that_is_not_words_is_refused(self):
        for bad in (7, ["x"], {"x": 1}):
            r = self.lock(falsifier=bad)
            self.assertEqual(r["action"], prediction.REFUSED, bad)
        self.assertFalse((self.st / prediction.PREDICTIONS_FILE).exists())

    def test_a_lag_needs_a_state_metric(self):
        r = self.lock(metric="logged", direction="at_least 4 of 7", lag_days=7)
        self.assertEqual(r["action"], prediction.REFUSED)
        self.assertIn("state metric", r["reason"])
        self.assertEqual(re.findall(r"\d", r["reason"]), [])
        self.assertEqual(self.lock(metric="logged", direction="at_least 4 of 7")["action"], prediction.LOCKED)

    def test_only_habit_experiments_are_locked(self):
        for text in ("Synthetic supplement before the habit", "A higher dose helps"):
            r = prediction.lock(self.st, WEEK.isoformat(), text, "sleep_h", "up", write=True, today=WEEK, now=NOW)
            self.assertEqual(r["action"], prediction.REFUSED, text)
        r = self.lock(falsifier="if the synthetic pill does nothing")
        self.assertEqual(r["action"], prediction.REFUSED)
        self.assertFalse((self.st / prediction.PREDICTIONS_FILE).exists())

    def test_an_old_row_without_the_fields_stays_valid(self):
        old = {"kind": "prediction", "week_of": WEEK.isoformat(), "text": "Synthetic prediction",
               "metric": "logged", "direction": "at_least 4 of 7", "locked_at": "2030-01-15T00:00:00+00:00"}
        (self.st / prediction.PREDICTIONS_FILE).write_text(json.dumps(old) + "\n")
        self.assertEqual(prediction.locked(self.st, WEEK.isoformat()), old)
        self.assertEqual((prediction.falsifier_of(old), prediction.lag_of(old)), (None, 0))
        self.assertEqual(self.lock()["action"], prediction.REFUSED)   # still one per week


class HabitPredictPassesThem(unittest.TestCase):
    """limitless_habit predict carries falsifier and lag_days through; it still writes only with confirm."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)
        (self.st / "habit.json").write_text(json.dumps({"habit": "Synthetic habit", "week_of": WEEK.isoformat(),
                                                        "checkins": {}}))

    def call(self, args):
        from unittest import mock
        from limitless import plugin
        with mock.patch.dict(os.environ, {"LIMITLESS_STATE": str(self.st),
                                          "LIMITLESS_CONFIG": str(self.st / "none.json")}), \
                mock.patch("time.time", return_value=NOW), \
                mock.patch("limitless.plugin.date") as d:
            d.fromtimestamp.return_value = WEEK
            return json.loads(plugin._handler(plugin.TOOLS["limitless_habit"][1])(args))

    def test_without_confirm_nothing_is_written(self):
        res = self.call({"predict": "Synthetic prediction", "metric": "sleep_h", "direction": "up",
                         "falsifier": FALSIFIER, "lag_days": 7})
        self.assertEqual(res["value"]["action"], prediction.WOULD_LOCK, res)
        self.assertEqual(res["value"]["prediction"]["lag_days"], 7)
        self.assertFalse((self.st / prediction.PREDICTIONS_FILE).exists())

    def test_with_confirm_the_row_carries_them(self):
        res = self.call({"predict": "Synthetic prediction", "metric": "sleep_h", "direction": "up",
                         "falsifier": FALSIFIER, "lag_days": 14, "confirm": True})
        self.assertEqual(res["value"]["action"], prediction.LOCKED, res)
        row = prediction.locked(self.st, WEEK.isoformat())
        self.assertEqual((row["falsifier"], row["lag_days"]), (FALSIFIER, 14))

    def test_the_schema_names_them(self):
        from limitless import plugin
        props = plugin.TOOLS["limitless_habit"][0]["parameters"]["properties"]
        self.assertEqual(props["lag_days"]["enum"], [0, 7, 14])
        self.assertEqual(props["falsifier"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
