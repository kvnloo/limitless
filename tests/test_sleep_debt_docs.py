"""docs/sleep-debt.md shows the real output of scripts/sleep_debt_example.py, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "sleep-debt.md"
sys.path.insert(0, str(ROOT))

from limitless import sleep_debt  # noqa: E402


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sleep_debt_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/sleep_debt.py", "limitless_sleep_debt", "docs/sleep-debt.md"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rule_and_its_constants(self):
        text = DOC.read_text()
        for word in ("RECENT_NIGHTS", "BASELINE_NIGHTS", "MIN_RECENT", "MIN_BASELINE", "SOME_SHARE", "A_LOT_SHARE",
                     "sleep.nights", "StateReader.sleep_rows", "sleep.screen_gaps", "tier_audit.gate",
                     "never zero", "(phone estimate)", "unknown: too few nights"):
            self.assertIn(word, text)
        for word in sleep_debt.WORDS:
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("no population norm", "no clock time", "no advice", "no score", "nothing is written or sent"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"\b(supplement|dose|dosing|melatonin|caffeine)\b")


if __name__ == "__main__":
    unittest.main()
