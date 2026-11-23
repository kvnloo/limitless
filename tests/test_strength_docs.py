"""docs/evidence-ladder.md shows the ladder, its rules and the real output of scripts/evidence_ladder_example.py;
the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "evidence-ladder.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "evidence_ladder_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_names_every_rung_in_order(self):
        text = DOC.read_text()
        self.assertIn("measured > derived > association > preregistered > repeated > replicated", text)

    def test_the_doc_says_what_never_climbs(self):
        text = DOC.read_text().lower()
        for words in ("contradicts", "inconclusive", "fewer than three logged days", "outside source",
                      "never from the person's own data", "no score", "read-only", "four fields never change"):
            self.assertIn(words, text)

    def test_the_readme_points_at_it(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/strength.py", "docs/evidence-ladder.md", "strength"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
