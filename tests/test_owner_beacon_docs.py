"""docs/owner-beacon.md: the operator recipe for a machine that writes the beacon on a schedule and copies it to
the plugin host. Generic placeholders only; the service files are text, nothing is installed by the plugin."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import owner_messages as om  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "owner-beacon.md"


class Recipe(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()
        self.low = self.text.lower()

    def test_placeholders_not_real_names(self):
        for word in ("<plugin host>", "<state dir>"):
            self.assertIn(word, self.text)
        self.assertNotIn("plugin-host:", self.text)

    def test_launchd_and_systemd_examples_as_text_only(self):
        for word in ("launchd", "StartInterval", "systemd", "OnUnitActiveSec", "nothing is installed"):
            self.assertIn(word.lower(), self.low)
        self.assertEqual(sorted(p.name for p in (ROOT / "docs").glob("*.plist")), [])

    def test_an_unchanged_beacon_is_not_copied_again(self):
        self.assertIn("unchanged", self.low)
        self.assertIn("mtime", self.low)
        self.assertRegex(self.text, r"rsync[^\n]*-t")

    def test_says_which_prompts_count(self):
        for src in om.AUTOMATED_SOURCES:
            self.assertIn(src, self.low)
        self.assertIn("not counted", self.low)
        for src in ("cli", "desktop", "gui", "chat platforms", "one-shot"):
            self.assertIn(src, self.low)

    def test_the_writer_section_matches_the_cli(self):
        self.assertIn("bin/limitless-owner-beacon write --out", self.text)
        self.assertTrue(re.search(r"0600", self.text))


if __name__ == "__main__":
    unittest.main()
