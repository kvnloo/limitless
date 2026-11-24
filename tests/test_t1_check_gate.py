"""t1_min_agreement and t1_check_file: labeler.from_config uses the local model only when the saved check result
allows it. With no t1_check_file (the default) nothing changes. Reading the gate never runs the model."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import labeler, t1_agreement as ta  # noqa: E402

CMD = "fake-model-cmd --flag"


class Allowed(unittest.TestCase):
    def test_the_default_minimum_is_most(self):
        self.assertEqual(ta.min_agreement({}), "most")
        self.assertEqual(ta.min_agreement({"t1_min_agreement": "nearly"}), "most")
        self.assertTrue(ta.allowed({}, {"verdict": "all"}))
        self.assertTrue(ta.allowed({}, "agrees on most checks"))
        self.assertFalse(ta.allowed({}, "agrees on few checks"))

    def test_the_minimum_can_be_raised_or_lowered(self):
        self.assertFalse(ta.allowed({"t1_min_agreement": "all"}, "agrees on most checks"))
        self.assertTrue(ta.allowed({"t1_min_agreement": "all"}, "agrees on all checks"))
        self.assertTrue(ta.allowed({"t1_min_agreement": "few"}, {"verdict": "few"}))

    def test_unknown_or_unreadable_is_never_allowed(self):
        for cfg in ({}, {"t1_min_agreement": "few"}):
            for r in ("unknown: every call failed", {"verdict": "unknown"}, "", None, "agrees on many checks", {}):
                self.assertFalse(ta.allowed(cfg, r), (cfg, r))


class FromConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state = self.dir / "state"
        self.state.mkdir()

    def lab(self, saved=None, **cfg):
        cfg = dict({"t1_model_cmd": CMD, "state": str(self.state)}, **cfg)
        path = self.dir / "config.json"
        path.write_text(json.dumps(cfg))
        if saved is not None:
            (self.state / "t1-check.txt").write_text(saved)
        boom = mock.Mock(side_effect=AssertionError("the gate started a process"))
        with mock.patch("subprocess.Popen", boom), mock.patch("subprocess.run", boom):
            return labeler.from_config(env={"LIMITLESS_CONFIG": str(path)}, home=self.dir).cmd

    def test_no_check_file_key_keeps_the_current_behaviour(self):
        self.assertEqual(self.lab(), CMD.split())
        self.assertEqual(self.lab(saved="agrees on few checks\n"), CMD.split())

    def test_a_check_file_key_with_no_file_keeps_the_rule_labels(self):
        self.assertIsNone(self.lab(t1_check_file="t1-check.txt"))

    def test_a_passing_check_on_file_lets_the_model_label(self):
        self.assertEqual(self.lab(saved="agrees on most checks\n", t1_check_file="t1-check.txt"), CMD.split())
        self.assertEqual(self.lab(saved="agrees on all checks\n", t1_check_file="t1-check.txt",
                                  t1_min_agreement="all"), CMD.split())

    def test_a_failing_or_unknown_check_keeps_the_rule_labels(self):
        for words in ("agrees on few checks\n", "unknown: every call failed\n", "agrees on all checks 7\n",
                      "garbage\n", ""):
            self.assertIsNone(self.lab(saved=words, t1_check_file="t1-check.txt"), words)
        self.assertIsNone(self.lab(saved="agrees on most checks\n", t1_check_file="t1-check.txt",
                                   t1_min_agreement="all"))

    def test_a_check_file_outside_the_state_dir_keeps_the_rule_labels(self):
        self.assertIsNone(self.lab(saved="agrees on all checks\n", t1_check_file="../t1-check.txt"))
        self.assertIsNone(self.lab(saved="agrees on all checks\n", t1_check_file=str(self.state / "t1-check.txt")))

    def test_rules_only_still_wins(self):
        with labeler.rules_only():
            self.assertIsNone(self.lab(saved="agrees on all checks\n", t1_check_file="t1-check.txt"))

    def test_no_command_is_still_none(self):
        self.assertIsNone(self.lab(saved="agrees on all checks\n", t1_check_file="t1-check.txt", t1_model_cmd=""))


if __name__ == "__main__":
    unittest.main()
