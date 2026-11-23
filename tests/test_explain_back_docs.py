"""docs/explain-back.md shows the real output of scripts/explain_back_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "explain-back.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "explain_back_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_explain_back", "docs/explain-back.md", "explain_back"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("no scoring, streaks or xp", "unlogged", "no push", "no clock time", "raw_in_prompt",
                     "never grades"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
