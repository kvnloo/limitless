"""Attention modes: mode.json load/save (atomic, 0600, fail open to none). Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import modes  # noqa: E402


class LoadSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def test_the_four_modes_and_none(self):
        self.assertEqual(modes.MODES, ("brainstorm", "pm", "copilot", "focused"))
        self.assertEqual(modes.NONE, "none")

    def test_no_file_is_none(self):
        self.assertEqual(modes.load(self.st), "none")

    def test_missing_dir_is_none(self):
        self.assertEqual(modes.load(self.st / "nope"), "none")

    def test_save_then_load_each_mode(self):
        for m in modes.MODES:
            self.assertEqual(modes.save(self.st, m), m)
            self.assertEqual(modes.load(self.st), m)
            self.assertEqual(json.loads((self.st / "mode.json").read_text())["mode"], m)

    def test_file_is_0600_and_no_temp_left(self):
        modes.save(self.st, "focused")
        self.assertEqual(stat.S_IMODE((self.st / "mode.json").stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["mode.json"])

    def test_off_and_none_return_to_none(self):
        for word in ("off", "none", "OFF", " Off "):
            modes.save(self.st, "pm")
            self.assertEqual(modes.save(self.st, word), "none")
            self.assertEqual(modes.load(self.st), "none")

    def test_case_and_spaces_are_ignored(self):
        self.assertEqual(modes.save(self.st, "  Focused "), "focused")
        self.assertEqual(modes.load(self.st), "focused")

    def test_unknown_mode_is_refused_and_keeps_the_file(self):
        modes.save(self.st, "pm")
        for bad in ("sprint", "", None, 3, ["pm"]):
            with self.assertRaises(ValueError):
                modes.save(self.st, bad)
        self.assertEqual(modes.load(self.st), "pm")

    def test_bad_files_fail_open_to_none(self):
        f = self.st / "mode.json"
        for text in ("", "{", "[]", '"focused"', "null", '{"mode": "sprint"}', '{"mode": 1}', '{}',
                     '{"mode": ["focused"]}', "\xff\xfe"):
            f.write_text(text, encoding="utf-8", errors="ignore")
            self.assertEqual(modes.load(self.st), "none", text)

    def test_a_directory_named_mode_json_is_none(self):
        (self.st / "mode.json").mkdir()
        self.assertEqual(modes.load(self.st), "none")

    def test_load_is_case_insensitive_on_disk(self):
        (self.st / "mode.json").write_text('{"mode": "Copilot"}')
        self.assertEqual(modes.load(self.st), "copilot")


if __name__ == "__main__":
    unittest.main()
