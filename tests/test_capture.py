"""limitless_capture appends exactly one line to captures.jsonl and never starts work."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import capture  # noqa: E402

NOW = 1894708800.0


class Capture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        (self.st / "captures.jsonl").write_text('{"at": "2030-01-14T10:00:00+00:00", "text": "older"}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        return (self.st / "captures.jsonl").read_text().splitlines()

    def test_appends_one_json_line(self):
        env = capture.capture(self.st, "idea: try the\nshorter route", NOW)
        self.assertEqual(len(self.lines()), 2)
        row = json.loads(self.lines()[-1])
        self.assertEqual(row, {"at": "2030-01-15T12:00:00+00:00", "text": "idea: try the\nshorter route",
                               "source": "hermes"})
        self.assertEqual(env["value"], {"captured": True, "line": 2})
        self.assertEqual(env["modality"], "self_report")
        self.assertEqual(env["age_h"], 0.0)

    def test_touches_no_other_file_and_spawns_nothing(self):
        boom = mock.Mock(side_effect=AssertionError("capture must not start work"))
        with mock.patch.object(subprocess, "Popen", boom), mock.patch.object(os, "system", boom):
            capture.capture(self.st, "x", NOW)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["captures.jsonl"])

    def test_empty_text_is_refused_with_a_reason(self):
        env = capture.capture(self.st, "   ", NOW)
        self.assertIsNone(env["value"])
        self.assertIn("empty", env["reason"])
        self.assertEqual(len(self.lines()), 1)

    def test_overlong_text_is_refused_not_cut(self):
        env = capture.capture(self.st, "x" * (capture.MAX_CHARS + 1), NOW)
        self.assertIsNone(env["value"])
        self.assertEqual(len(self.lines()), 1)

    def test_missing_state_dir_is_not_created(self):
        gone = self.st / "nope"
        env = capture.capture(gone, "x", NOW)
        self.assertIsNone(env["value"])
        self.assertFalse(gone.exists())


if __name__ == "__main__":
    unittest.main()
