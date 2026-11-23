"""docs/feed-reflex.md shows the real output of scripts/feed_reflex_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "feed-reflex.md"
sys.path.insert(0, str(ROOT))

from limitless import feed_reflex, habit_catalogue  # noqa: E402


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "feed_reflex_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/feed_reflex.py", "limitless_feed_reflex", "docs/feed-reflex.md", "feed_reflex_gap_s"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rule_and_its_constants(self):
        text = DOC.read_text()
        for word in ("REFLEX_GAP_S", "feed_reflex_gap_s", "OFTEN_SHARE", "RARELY_SHARE", "MIN_UNLOCKS",
                     "feed_reflex_often_share", "feed_reflex_rarely_share", "feed_reflex_min_unlocks",
                     "aw_reader.person_rows", "blocks.read_rows", "feeds_evidence.feed_apps", "tier_audit.gate",
                     "week_review:feed_reflex", "never zero", "CIRCUIT_BREAKER", habit_catalogue.CIRCUIT_BREAKER["name"],
                     "feed reflex", "LIMITLESS_RAW_IN_PROMPT"):
            self.assertIn(word, text)
        for word in feed_reflex.WORDS:
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("never blocks, closes or delays an app", "never a clock time", "no score", "no streak",
                     "nothing is written or sent", "desktop rows"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"\b(supplement|dose|dosing|melatonin|caffeine)\b")

    def test_the_example_output_is_synthetic(self):
        text = DOC.read_text()
        self.assertNotRegex(text, r"/(Users|home)/")
        self.assertNotIn("tmp", re.findall(r"```text\n(.*?)```", text, re.S)[0])


if __name__ == "__main__":
    unittest.main()
