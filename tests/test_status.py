"""limitless_status: each input's age, a Not-recording list (>24 h or down), the last run. Synthetic only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock


class Status(unittest.TestCase):
    def setUp(self):
        self.env = tools.status(StateReader(FIX), NOW)
        self.v = self.env["value"]

    def test_envelope(self):
        self.assertEqual(self.env["modality"], "measured")
        self.assertEqual(self.env["age_h"], 0.5)  # inputs.json snapshot is 30 min old
        self.assertEqual(self.env["evidence_tier"], "direct")

    def test_ages_are_current_not_as_of_the_snapshot(self):
        self.assertEqual(self.v["inputs"]["wearable"], {"age_h": 4.2, "state": "recording"})
        self.assertEqual(self.v["inputs"]["phone"], {"age_h": 0.7, "state": "recording"})

    def test_not_recording_is_over_a_day_old_or_down(self):
        self.assertEqual(self.v["inputs"]["scale"]["state"], "not recording")
        self.assertEqual(self.v["inputs"]["bike"], {"age_h": None, "state": "down"})
        self.assertEqual(self.v["not_recording"], ["anki", "bike", "scale"])

    def test_last_run(self):
        run = self.v["last_run"]
        self.assertEqual(run["value"], {"at": "2030-01-15T10:47:00Z", "ok": True})
        self.assertEqual(run["age_h"], 1.2)

    def test_unknown_age_is_unknown_not_down(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inputs.json").write_text('{"at": "2030-01-15T11:30:00Z", "ageHours": {"x": null}}')
            v = tools.status(StateReader(Path(d)), NOW)["value"]
        self.assertEqual(v["inputs"]["x"], {"age_h": None, "state": "unknown"})
        self.assertEqual(v["not_recording"], [])
        self.assertEqual(v["unknown"], ["x"])
        self.assertIsNone(v["last_run"]["value"])
        self.assertIn("runs.jsonl", v["last_run"]["reason"])

    def test_no_inputs_file_is_null_with_reason(self):
        with tempfile.TemporaryDirectory() as d:
            env = tools.status(StateReader(Path(d)), NOW)
        self.assertIsNone(env["value"])
        self.assertIn("inputs.json", env["reason"])


if __name__ == "__main__":
    unittest.main()
