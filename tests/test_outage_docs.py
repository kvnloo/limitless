"""docs/outage.md shows the real output of scripts/outage_example.py, says what the notice never does, and the
README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "outage.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "outage_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_outages", "docs/outage.md", "input_outage", "outage_ignore", "outage_hints",
                     "limitless/outage.py"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = " ".join(DOC.read_text().lower().split())
        for word in ("input_outage", "outage_ignore", "outage_hints", "outage.json", "0600", "never restarts",
                     "no push of its own", "no \"back\" message", "suggest only", "no clock time"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
