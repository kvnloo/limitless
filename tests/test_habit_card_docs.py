"""docs/habit-card.md shows the real output of scripts/habit_card_example.py, states the contract, and the README
points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "habit-card.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "habit_card_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_states_the_contract(self):
        text = DOC.read_text().lower()
        for words in ("unknown is not no", "no score", "never a clock time", "week_number", "verdict_inputs",
                      "record(", "#158289", "schedule-cards.md", "start_s"):
            self.assertIn(words, text)

    def test_the_readme_names_the_module_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("limitless/habit_card.py", text)
        self.assertIn("docs/habit-card.md", text)


if __name__ == "__main__":
    unittest.main()
