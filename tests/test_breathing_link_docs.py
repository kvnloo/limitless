"""docs/breathing-link.md shows the real output of scripts/breathing_link_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "breathing-link.md"


class Docs(unittest.TestCase):
    def run_example(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "breathing_link_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_doc_example_is_the_scripts_real_output(self):
        out = self.run_example()
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(out, blocks)

    def test_the_example_uses_a_synthetic_link_and_shows_both_wordings(self):
        out = self.run_example()
        self.assertIn("example://breathe", out)
        self.assertIn("(with live heart data)", out)
        self.assertIn("(without heart data)", out)
        self.assertIn('"link": "a link is set"', out)

    def test_the_readme_names_the_tool_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_breathing", "wind_down_breathing_link", "docs/breathing-link.md"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("off by default", "no new push", "no new job", "tier_audit.gate", "with live heart data",
                     "without heart data", "raw_in_prompt", "no clock time", "no breath count", "suggest"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
