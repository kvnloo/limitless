"""limitless_habit's optional start: it writes only with confirm true, else it says what it would do.
The result keeps the evidence envelope and a digit-free label. Synthetic fixtures only; nothing sends."""
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

from limitless import plugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0          # fixture clock, 2030-01-15: the fixture's week of 2030-01-11 is running
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


class HabitStartTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.hj = self.st / "habit.json"

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args, now=NOW):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=now):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_habit"][1])(args))

    def finish_week(self):
        self.hj.unlink()          # no week: a start may go ahead

    def assert_envelope(self, res, label):
        self.assertTrue(FIELDS <= set(res), res)
        self.assertIsNotNone(res["value"])
        self.assertEqual(res["modality"], "self_report")
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(res["label"]["label"], label)
        self.assertEqual(re.findall(r"\d", res["label"]["label"]), [])

    def test_schema_has_start_and_confirm(self):
        props = plugin.TOOLS["limitless_habit"][0]["parameters"]["properties"]
        self.assertEqual(props["start"]["type"], "string")
        self.assertEqual(props["confirm"]["type"], "boolean")
        self.assertNotIn("required", plugin.TOOLS["limitless_habit"][0]["parameters"])

    def test_without_start_it_reads_as_before(self):
        res = self.call({})
        self.assertEqual(res["value"]["today"], "Done")

    def test_start_without_confirm_says_what_it_would_do(self):
        self.finish_week()
        for args in ({"start": "Synthetic habit"}, {"start": "Synthetic habit", "confirm": False},
                     {"start": "Synthetic habit", "confirm": "true"}, {"start": "Synthetic habit", "confirm": 1}):
            res = self.call(args)
            self.assert_envelope(res, "would start this habit week")
            self.assertEqual(res["value"]["action"], "would start")
            self.assertFalse(self.hj.exists(), args)

    def test_start_with_confirm_writes(self):
        self.finish_week()
        res = self.call({"start": "Synthetic habit", "confirm": True})
        self.assert_envelope(res, "started this habit week")
        got = json.loads(self.hj.read_text())
        self.assertEqual((got["habit"], got["week_of"], got["checkins"]), ("Synthetic habit", "2030-01-15", {}))

    def test_a_running_week_is_refused_with_a_reason(self):
        before = self.hj.read_bytes()
        res = self.call({"start": "Synthetic habit", "confirm": True})
        self.assert_envelope(res, "refused: a habit week is already running: one habit a week")
        self.assertEqual(res["value"]["action"], "refused")
        self.assertEqual(self.hj.read_bytes(), before)

    def test_a_finished_week_is_kept_when_started(self):
        res = self.call({"start": "Synthetic habit", "confirm": True}, now=NOW + 7 * 86400)
        self.assert_envelope(res, "started this habit week")
        self.assertTrue((self.st / "habit-2030-01-11.json").exists())

    def test_empty_start_is_refused(self):
        self.finish_week()
        res = self.call({"start": " ", "confirm": True})
        self.assert_envelope(res, "refused: the habit text is empty")
        self.assertFalse(self.hj.exists())


if __name__ == "__main__":
    unittest.main()
