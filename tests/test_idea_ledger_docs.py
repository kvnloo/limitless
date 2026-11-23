"""docs/idea-ledger.md shows the real output of scripts/idea_ledger_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "idea-ledger.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "idea_ledger_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_command_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_ideas", "limitless-ledger-append", "docs/idea-ledger.md", "idea_ledger"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("no second", "no default path", "raw_in_prompt", "no clock time", "never triages",
                     "no push", "append-only"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
